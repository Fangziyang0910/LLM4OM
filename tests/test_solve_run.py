"""Verify compilation and genuine HiGHS solving through the public CLI."""

import hashlib
import json
import os
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class SolveRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inputs = Path(self.temp.name) / "input"
        shutil.copytree(ROOT / "examples/specs", self.inputs)
        (self.inputs / "oracle.json").write_text("PRIVATE-ORACLE-SOLVE-SENTINEL\n")
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        (self.inputs / "run.yaml").write_text(yaml.safe_dump(settings))

    def run_cli(self, *, isolated_packages: Path | None = None) -> tuple[subprocess.CompletedProcess, Path, dict]:
        python_args = [sys.executable, "-S"] if isolated_packages else [sys.executable]
        pythonpath = str(ROOT / "src") + (os.pathsep + str(isolated_packages) if isolated_packages else "")
        result = subprocess.run(
            [*python_args, "-m", "llm4om", "run", "--problem", str(self.inputs / "problem.json"),
             "--config", str(self.inputs / "run.yaml"), "--output", str(Path(self.temp.name) / "runs")],
            env={**os.environ, "PYTHONPATH": pythonpath, "LLM4OM_LLM_API_KEY": "PRIVATE-KEY-SOLVE-SENTINEL"},
            capture_output=True, text=True, cwd=self.temp.name,
        )
        self.assertTrue(result.stdout, result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        return result, path, json.loads((path / "bundle.json").read_text())

    def replace_ir(self, ir: dict) -> None:
        raw = (json.dumps(ir, indent=2) + "\n").encode()
        (self.inputs / "model-ir.json").write_bytes(raw)
        formulation = json.loads((self.inputs / "formulation.json").read_text())
        formulation["structured_ir_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        raw = (json.dumps(formulation, ensure_ascii=False, indent=2) + "\n").encode()
        (self.inputs / "formulation.json").write_bytes(raw)
        artifact = json.loads((self.inputs / "model-artifact.json").read_text())
        artifact["formulation_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        (self.inputs / "model-artifact.json").write_text(json.dumps(artifact))

    def test_milp_is_compiled_to_code_and_solved_by_real_highs(self) -> None:
        result, path, bundle = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(bundle["status"], "completed")
        self.assertEqual(bundle["mode"], "trusted_local")
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["termination"], "optimal")
        self.assertTrue(solve["has_primal_solution"])
        self.assertAlmostEqual(solve["objective_value"], 13)
        solution = json.loads((path / solve["solution_ref"]["relative_path"]).read_text())
        self.assertAlmostEqual(solution["variables"]["qty_A"], 3)
        self.assertAlmostEqual(solution["variables"]["qty_B"], 2)
        artifact = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
        self.assertEqual(artifact["stage_status"]["code"]["status"], "available")
        code = json.loads((path / artifact["code_ref"]["relative_path"]).read_text())
        self.assertEqual(code["provenance"]["origin"], "deterministic_compilation")
        self.assertTrue((path / code["representation_ref"]["relative_path"]).is_file())
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["solver_calls"], 1)
        self.assertEqual(ledger["external_llm_requests"], 0)
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        ir["objective"]["expression"]["constant"] = 7
        self.replace_ir(ir)
        result, path, bundle = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertAlmostEqual(solve["objective_value"], 20)
        solution = json.loads((path / solve["solution_ref"]["relative_path"]).read_text())
        self.assertEqual(solution["variables"], {"qty_A": 3, "qty_B": 2})

    def test_lp_relaxation_preserves_continuous_domains(self) -> None:
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        ir["problem_type"] = "lp"
        for variable in ir["variables"]:
            variable["domain"] = "continuous"
        self.replace_ir(ir)
        result, path, bundle = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["termination"], "optimal")
        self.assertAlmostEqual(solve["objective_value"], 40 / 3)
        solution = json.loads((path / solve["solution_ref"]["relative_path"]).read_text())
        self.assertAlmostEqual(solution["variables"]["qty_A"], 8 / 3)
        self.assertAlmostEqual(solution["variables"]["qty_B"], 8 / 3)

    def test_invalid_ir_is_rejected_before_a_solver_call(self) -> None:
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        ir["objective"]["expression"]["terms"][0]["variable_id"] = "nonexistent"
        self.replace_ir(ir)
        result, path, bundle = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "invalid_ir")
        self.assertEqual(bundle["error"]["stage"], "code")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 0)

    def test_zero_solver_budget_rejects_before_mock_or_compilation(self) -> None:
        settings = yaml.safe_load((self.inputs / "run.yaml").read_text())
        settings["budget"]["max_solver_calls"] = 0
        (self.inputs / "run.yaml").write_text(yaml.safe_dump(settings))
        result, path, bundle = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "budget_exhausted")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["llm_attempts"], 0)
        self.assertEqual(ledger["solver_calls"], 0)

    def test_missing_optional_solver_dependency_fails_before_mock(self) -> None:
        packages = Path(self.temp.name) / "base-packages"
        packages.mkdir()
        for name in ("yaml", "jsonschema", "attrs", "attr", "pyrsistent"):
            spec = importlib.util.find_spec(name)
            self.assertIsNotNone(spec)
            shutil.copytree(Path(spec.origin).parent, packages / name)
        result, path, bundle = self.run_cli(isolated_packages=packages)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "solver_unavailable")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)

    def test_native_admission_failure_keeps_compiled_code_and_execution_diagnostic(self) -> None:
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        ir["variables"][0]["upper_bound"] = 1e30
        self.replace_ir(ir)
        result, path, bundle = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "unsupported_numeric_range")
        self.assertEqual(bundle["stages"]["code"]["status"], "available")
        artifact = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
        self.assertIsNotNone(artifact["code_ref"])
        execution = json.loads((path / bundle["execution_result_ref"]["relative_path"]).read_text())
        self.assertEqual(execution["status"], "failed")
        self.assertIsNone(execution["solve_result_ref"])
        self.assertEqual(bundle["execution_plan"]["compiler"]["status"], "available")
        self.assertEqual(bundle["execution_plan"]["solver"]["status"], "failed")
        self.assertEqual(json.loads((path / "evaluation.json").read_text())["code_validation"]["status"], "pass")

    def test_bundle_records_real_execution_and_keeps_all_references_valid(self) -> None:
        result, path, bundle = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(bundle["execution_plan"]["solver"]["status"], "available")
        self.assertEqual(bundle["execution_plan"]["executor"]["resolved_plugin_id"], "llm4om.executors.trusted_local")
        execution = json.loads((path / bundle["execution_result_ref"]["relative_path"]).read_text())
        self.assertEqual(execution["mode"], "trusted_local")
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(execution["solve_result_ref"], bundle["solve_result_ref"])
        build = json.loads((path / "candidates/001/build.json").read_text())
        self.assertEqual(build["source_ir_ref"]["schema_version"], "0.1.0")
        candidate = json.loads((path / "candidates/001/candidate.json").read_text())
        self.assertEqual(candidate["status"], "selected")
        self.assertEqual(candidate["artifact_ref"], bundle["model_artifact_ref"])
        self.assertEqual(bundle["final_candidate_id"], "001")
        environment = json.loads((path / "environment-lock.json").read_text())
        self.assertEqual(environment["mode"], "trusted_local")
        self.assertIn("highspy", environment["packages"])
        for ref in bundle["artifacts"]:
            raw = (path / ref["relative_path"]).read_bytes()
            self.assertNotIn(b"PRIVATE-ORACLE-SOLVE-SENTINEL", raw)
            self.assertNotIn(b"PRIVATE-KEY-SOLVE-SENTINEL", raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), ref["sha256"])
            if ref["media_type"] == "application/json":
                value = json.loads(raw)
                self.verify_refs(value, path)
        for line in (path / "events.jsonl").read_text().splitlines():
            self.verify_refs(json.loads(line), path)
        evaluation = json.loads((path / "evaluation.json").read_text())
        self.assertEqual(evaluation["code_validation"]["status"], "pass")
        self.assertEqual(evaluation["semantic_validation"]["status"], "not_available")
        self.assertIn("13", (path / "reports/report.md").read_text())

    def verify_refs(self, value: object, path: Path) -> None:
        if isinstance(value, dict):
            if "relative_path" in value and "sha256" in value:
                raw = (path / value["relative_path"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), value["sha256"])
                self.assertEqual(len(raw), value["size_bytes"])
                self.assertEqual(value["namespace"], "run_public")
            for child in value.values():
                self.verify_refs(child, path)
        elif isinstance(value, list):
            for child in value:
                self.verify_refs(child, path)


if __name__ == "__main__":
    unittest.main()
