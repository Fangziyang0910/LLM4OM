"""Installed compilers through CLI, owned Worker and actual Solver interfaces."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import yaml
from llm4om import resolve_compiler

ROOT = Path(__file__).resolve().parents[1]


class CompilerPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packages = self.root / "packages"
        self.inputs = self.root / "input"
        shutil.copytree(ROOT / "examples/specs", self.inputs)

    def cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "llm4om", *arguments], cwd=self.root,
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, timeout=90)

    def test_builtin_compiler_declares_actual_deterministic_profile(self):
        result = self.cli("plugins", "list")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        compilers = [item for item in json.loads(result.stdout)["plugins"] if item["manifest"]["kind"] == "compiler"]
        self.assertEqual(len(compilers), 1)
        manifest = compilers[0]["manifest"]
        self.assertEqual(manifest["plugin_id"], "llm4om.compilers.lp_ir_to_pyomo")
        self.assertEqual(manifest["capabilities"]["compiler_profile"], "grounded_lpir_pyomo/0.1.0")
        self.assertTrue(manifest["capabilities"]["deterministic"])
        self.assertEqual(manifest["capabilities"]["model_backends"], ["llm4om.model_backends.pyomo_factory"])

    def install_compiler(self):
        project = self.root / "compiler"
        shutil.copytree(ROOT / "examples/plugins/fixture_compiler", project)
        subprocess.run(["uv", "build", "--offline", "--wheel", "--out-dir", str(self.root / "dist")], cwd=project,
                       check=True, capture_output=True, text=True)
        wheel = next((self.root / "dist").glob("*.whl"))
        subprocess.run(["uv", "pip", "install", "--no-deps", "--target", str(self.packages), str(wheel)],
                       check=True, capture_output=True, text=True)

    def config(self):
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["compiler"] = {"plugin_id": "llm4om.examples.ast_compiler", "config": {"marker": "selected_compiler"}}
        if os.environ.get("LLM4OM_TEST_COMPILER_IMAGE"):
            settings["executor"] = yaml.safe_load((self.inputs / "run.yaml").read_text())["executor"]
            settings["executor"]["config"]["image"] = os.environ["LLM4OM_TEST_COMPILER_IMAGE"]
        path = self.inputs / "compiler.yaml"
        path.write_text(yaml.safe_dump(settings))
        return path

    def test_installed_compiler_actual_source_and_config_are_used_by_owned_worker(self):
        self.install_compiler()
        config = self.config()
        doctor = self.cli("doctor", "--config", str(config))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        selected = json.loads(doctor.stdout)["execution_plan"]["compiler"]
        self.assertEqual(selected["origin"]["distribution"], "llm4om-fixture-compiler")
        self.assertEqual(selected["config"], {"marker": "selected_compiler"})
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config),
                          "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        self.assertIn("COMPILER_MARKER = 'selected_compiler'", (path / "checks/001/model.py").read_text())
        solve = json.loads((path / "checks/001/solve-result.json").read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(json.loads((path / "checks/001/solution.json").read_text())["variables"], {"qty_A": 3.0, "qty_B": 2.0})
        code = json.loads((path / "checks/001/code-artifact.json").read_text())
        self.assertEqual(code["provenance"]["compiler_id"], "llm4om.examples.ast_compiler")

    def test_missing_compiler_in_worker_rejects_before_generation_or_solver_attempt(self):
        self.install_compiler()
        config = self.config()
        settings = yaml.safe_load(config.read_text())
        settings["executor"] = yaml.safe_load((self.inputs / "run.yaml").read_text())["executor"]
        config.write_text(yaml.safe_dump(settings))
        doctor = self.cli("doctor", "--config", str(config))
        self.assertEqual(doctor.returncode, 1, doctor.stdout + doctor.stderr)
        self.assertEqual(json.loads(doctor.stdout)["error"]["code"], "compiler_unavailable")
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["llm_attempts"], ledger["solver_calls"]), (0, 0))

    def test_saved_compiler_source_or_configuration_cannot_be_silently_changed_on_resume(self):
        self.install_compiler()
        config = self.config()
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        before = (path / "events.jsonl").read_bytes()
        source = self.packages / "llm4om_fixture_compiler/__init__.py"
        source.write_text(source.read_text() + "\n# changed installed compiler\n")
        resumed = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(json.loads(resumed.stdout)["error"]["code"], "checkpoint_incompatible")
        self.assertEqual((path / "events.jsonl").read_bytes(), before)

    def test_compiler_rejects_unsupported_problem_types_before_generation(self):
        self.install_compiler()
        source = self.packages / "llm4om_fixture_compiler/__init__.py"
        source.write_text(source.read_text().replace("return manifest", 'manifest["capabilities"]["problem_types"] = ["lp"]\n        return manifest'))
        config = self.config()
        doctor = self.cli("doctor", "--config", str(config))
        self.assertEqual(doctor.returncode, 1, doctor.stdout + doctor.stderr)
        self.assertEqual(json.loads(doctor.stdout)["error"]["code"], "capability_mismatch")

    def test_compiler_manifest_config_and_dependency_errors_reject_at_admission(self):
        self.install_compiler()
        source = self.packages / "llm4om_fixture_compiler/__init__.py"
        original = source.read_text()
        for change, expected in (
            ('manifest["contract_range"] = ">=0.3.0,<0.4.0"', "incompatible_contract"),
            ('manifest["capabilities"]["deterministic"] = False', "invalid_plugin_manifest"),
            ('manifest["dependencies"]["python"] = ["llm4om-missing-compiler-dependency"]', "dependency_missing"),
            ('manifest["plugin_id"] = "llm4om.compilers.lp_ir_to_pyomo"', "duplicate_plugin"),
        ):
            with self.subTest(expected=expected):
                source.write_text(original.replace("return manifest", change + "\n        return manifest"))
                shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
                doctor = self.cli("doctor", "--config", str(self.config()))
                self.assertEqual(doctor.returncode, 1, doctor.stdout + doctor.stderr)
                self.assertEqual(json.loads(doctor.stdout)["error"]["code"], expected)
        source.write_text(original)
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        config = self.config()
        settings = yaml.safe_load(config.read_text())
        settings["compiler"]["config"]["marker"] = "invalid marker"
        config.write_text(yaml.safe_dump(settings))
        doctor = self.cli("doctor", "--config", str(config))
        self.assertEqual(json.loads(doctor.stdout)["error"]["code"], "invalid_config")

    def test_worker_rejects_source_or_symbol_drift_before_solving(self):
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        selection = {"plugin_id": "llm4om.compilers.lp_ir_to_pyomo"}
        compiler = resolve_compiler(selection, "llm4om.model_backends.pyomo_factory")
        code = compiler.compile(ir)
        for field, value in (("source_sha256", "0" * 64),
                ("symbol_map", {**code.symbol_map, "variables": {"qty_A": 1, "qty_B": 0}})):
            with self.subTest(field=field):
                request = {"ir": ir, "source_sha256": hashlib.sha256(code.source.encode()).hexdigest(),
                    "symbol_map": code.symbol_map, "solver_options": {}, "compiler": selection,
                    "compiler_identity": compiler.binding, "target_backend": compiler.target_backend}
                request[field] = value
                result = subprocess.run([sys.executable, "-m", "llm4om.worker", "--solve-stdin"],
                    input=json.dumps(request), capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["error"]["code"], "code_hash_mismatch")

    def test_invalid_compiler_symbols_reject_before_solver_and_keep_safe_diagnostics(self):
        self.install_compiler()
        source = self.packages / "llm4om_fixture_compiler/__init__.py"
        source.write_text(source.read_text().replace("return CompiledCode(source, code.symbol_map)",
            'code.symbol_map["variables"]["unknown_decision"] = 0\n        return CompiledCode(source, code.symbol_map)'))
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        config = self.config()
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        bundle = json.loads((path / "bundle.json").read_text())
        self.assertEqual(bundle["error"]["code"], "compilation_error")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 0)

    def test_installed_compiler_preserves_continuous_domain_and_linear_optimum(self):
        self.install_compiler()
        problem = json.loads((self.inputs / "problem.json").read_text())
        problem["revision"] = "continuous-1"
        problem["problem_type_hint"] = "lp"
        problem["requirements"][1]["text"] = "A and B are nonnegative real quantities."
        (self.inputs / "problem.json").write_text(json.dumps(problem))
        for name in ("model-artifact.json", "formulation.json", "model-ir.json"):
            path = self.inputs / name
            value = json.loads(path.read_text())
            if name != "model-artifact.json":
                value["problem_revision"] = "continuous-1"
            if name == "formulation.json":
                for variable in value["representation"]["variables"]:
                    variable["domain"] = "continuous"
            if name == "model-ir.json":
                value["problem_type"] = "lp"
                for variable in value["variables"]:
                    variable["domain"] = "continuous"
            path.write_text(json.dumps(value))
        formulation_path = self.inputs / "formulation.json"
        formulation = json.loads(formulation_path.read_text())
        raw_ir = (self.inputs / "model-ir.json").read_bytes()
        formulation["structured_ir_ref"].update(sha256=hashlib.sha256(raw_ir).hexdigest(), size_bytes=len(raw_ir))
        formulation_path.write_text(json.dumps(formulation))
        artifact_path = self.inputs / "model-artifact.json"
        artifact = json.loads(artifact_path.read_text())
        for field, name in (("problem_ref", "problem.json"), ("formulation_ref", "formulation.json")):
            raw = (self.inputs / name).read_bytes()
            artifact[field].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        artifact_path.write_text(json.dumps(artifact))
        config = self.config()
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        self.assertAlmostEqual(json.loads((path / "checks/001/solve-result.json").read_text())["objective_value"], 40 / 3)


if __name__ == "__main__":
    unittest.main()
