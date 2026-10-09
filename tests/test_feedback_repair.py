"""Bounded public-feedback repair through CLI, real HTTP and real Solvers."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class FeedbackRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "input"
        shutil.copytree(ROOT / "examples/specs", self.inputs)
        formulation = json.loads((self.inputs / "formulation.json").read_text())
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        self.compact = {"representation": formulation["representation"], "structured_ir": {
            key: ir[key] for key in ("problem_type", "variables", "objective", "constraints", "assumptions")}}
        self.settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        self.settings["method"]["plugin_id"] = "llm4om.methods.feedback_repair"
        self.settings["budget"].update(max_llm_attempts=3, max_total_tokens=30000, max_candidates=3,
                                      max_repairs=2, max_solver_calls=3, wall_time_s=90)

    def run_responses(self, responses: list[dict | str], *, crash_script: str | None = None) -> tuple[Path, dict, list[dict]]:
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner) -> None:
                request = json.loads(inner.rfile.read(int(inner.headers["Content-Length"])))
                requests.append(request)
                value = responses[min(len(requests) - 1, len(responses) - 1)]
                inner.send_response(200)
                inner.end_headers()
                inner.wfile.write(json.dumps({"id": "synthetic-feedback-response", "model": "synthetic-model",
                    "choices": [{"message": {"content": value if isinstance(value, str) else json.dumps(value)},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}}).encode())
            def log_message(inner, *args) -> None:
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.settings["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "synthetic-model",
            "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "REPAIR_TEST_KEY",
                       "max_output_tokens": 2048, "max_retries": 0}}
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(self.settings))
        entry = [sys.executable, "-c", crash_script] if crash_script is not None else [sys.executable, "-m", "llm4om"]
        environment = {**os.environ, "REPAIR_TEST_KEY": "synthetic-repair-key", "PYTHONPATH": str(ROOT / "src")}
        result = subprocess.run([*entry, "run", "--problem", str(self.inputs / "problem.json"),
            "--config", str(self.inputs / "solve.yaml"), "--output", str(self.root / "runs")],
            env=environment,
            cwd=self.root, capture_output=True, text=True, timeout=100)
        if crash_script is not None:
            self.assertEqual(result.returncode, 91, result.stdout + result.stderr)
            run = next(p for p in (self.root / "runs").iterdir() if (p / "checkpoint.json").exists())
            environment.pop("REPAIR_TEST_KEY")
            result = subprocess.run([sys.executable, "-m", "llm4om", "resume", "--run-id", run.name,
                "--output", str(run.parent)], env=environment, cwd=self.root, capture_output=True, text=True, timeout=100)
        self.assertTrue(result.stdout, result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        return path, json.loads((path / "bundle.json").read_text()), requests

    def test_compile_feedback_drives_one_child_then_reuses_real_highs(self) -> None:
        invalid = deepcopy(self.compact)
        invalid["structured_ir"]["objective"]["expression"]["terms"][0]["variable_id"] = "missing"
        correction = {**self.compact, "repair_stage": "formulation",
                      "change_reason": "Restore the declared decision ID and keep both resource constraints."}
        path, bundle, requests = self.run_responses([invalid, correction])
        self.assertEqual(bundle["status"], "completed", bundle.get("error"))
        self.assertEqual(bundle["final_candidate_id"], "002")
        self.assertEqual(len(requests), 2)
        feedback = json.loads(requests[1]["messages"][-1]["content"])["feedback"]
        self.assertEqual(feedback["assessment"]["diagnostics"][0]["code"], "invalid_ir")
        child = json.loads((path / "candidates/002/candidate.json").read_text())
        self.assertEqual(child["parent_ids"], ["001"])
        self.assertIn("keep both", child["change_reason"])
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["external_llm_requests"], ledger["candidates"], ledger["repairs"], ledger["solver_calls"]), (2, 2, 1, 1))
        parent = json.loads((path / "candidates/001/formulation-snapshot.json").read_text())
        child_artifact = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
        self.assertNotEqual(parent["formulation_ref"], child_artifact["formulation_ref"])
        changes = json.loads((path / "candidates/002/formulation-changes.json").read_text())
        self.assertEqual(changes["ir_changed_sections"], ["objective"])

    def test_zero_repairs_keeps_invalid_attempt_and_returns_explicit_exhaustion(self) -> None:
        invalid = deepcopy(self.compact)
        invalid["structured_ir"]["objective"]["expression"]["terms"][0]["variable_id"] = "missing"
        self.settings["budget"]["max_repairs"] = 0
        path, bundle, requests = self.run_responses([invalid])
        self.assertEqual(bundle["status"], "failed")
        self.assertEqual(bundle["error"]["code"], "method_exhausted")
        self.assertEqual(len(requests), 1)
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["candidates"], 1)

    def test_malformed_generation_is_a_counted_parent_with_private_raw_reply(self) -> None:
        correction = {**self.compact, "repair_stage": "formulation", "change_reason": "Replace invalid JSON with the complete public mathematical output."}
        path, bundle, requests = self.run_responses(["MALFORMED-RAW-RESPONSE-SENTINEL {", correction])
        self.assertEqual(bundle["status"], "completed", bundle.get("error"))
        self.assertEqual(bundle["final_candidate_id"], "002")
        parent = json.loads((path / "candidates/001/assessment.json").read_text())
        self.assertEqual(parent["diagnostics"][0]["code"], "invalid_json")
        self.assertEqual(parent["diagnostics"][0]["origin"], "method_decoder")
        self.assertEqual(parent["status"], "invalid")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["repairs"], ledger["external_llm_requests"]), (2, 1, 2))
        for file in path.rglob("*"):
            if file.is_file():
                self.assertNotIn(b"MALFORMED-RAW-RESPONSE-SENTINEL", file.read_bytes())
        self.assertNotIn("MALFORMED-RAW-RESPONSE-SENTINEL", requests[1]["messages"][-1]["content"])

    def test_llm_budget_exhaustion_retains_attempts_without_an_extra_request(self) -> None:
        invalid = deepcopy(self.compact)
        invalid["structured_ir"]["objective"]["expression"]["terms"][0]["variable_id"] = "missing"
        self.settings["budget"]["max_llm_attempts"] = 1
        path, bundle, requests = self.run_responses([invalid])
        self.assertEqual(bundle["error"]["code"], "method_exhausted")
        self.assertEqual(len(requests), 1)
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["external_llm_requests"], 1)

    def test_removed_business_constraint_is_recorded_and_cannot_win_by_feasibility(self) -> None:
        invalid = deepcopy(self.compact)
        invalid["structured_ir"]["objective"]["expression"]["terms"][0]["variable_id"] = "missing"
        removed = deepcopy(self.compact)
        removed["representation"]["constraints"].pop()
        removed["structured_ir"]["constraints"].pop()
        removed.update(repair_stage="formulation", change_reason="Delete the finishing capacity to get a feasible candidate.")
        self.settings["budget"]["max_repairs"] = 1
        path, bundle, requests = self.run_responses([invalid, removed])
        self.assertEqual(bundle["status"], "failed")
        self.assertIsNone(bundle["final_candidate_id"])
        child = json.loads((path / "candidates/002/assessment.json").read_text())
        self.assertEqual(child["diagnostics"][0]["code"], "requirement_coverage_lost")
        changes = json.loads((path / "candidates/002/formulation-changes.json").read_text())
        self.assertEqual(changes["requirements_lost"], ["R-FINISHING"])
        self.assertEqual(changes["constraint_ids_removed"], ["capacity_finishing"])
        self.assertEqual(len(requests), 2)
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 0)

    def test_code_only_factory_repair_preserves_the_original_formulation_reference(self) -> None:
        self.settings["method"]["config"]["output_mode"] = "python_factory"
        self.settings["executor"] = {"plugin_id": "llm4om.executors.container", "config": {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 512, "wall_time_s": 15}}
        first = {"representation": self.compact["representation"], "python_factory": "def build_model(data):\n    broken !\n"}
        second = {"python_factory": (ROOT / "examples/factories/production.py").read_text(),
            "repair_stage": "code", "change_reason": "Fix Python syntax while retaining the original mathematical formulation."}
        path, bundle, requests = self.run_responses([first, second])
        self.assertEqual(bundle["status"], "completed", bundle.get("error"))
        parent = json.loads((path / "candidates/001/formulation-snapshot.json").read_text())
        child = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
        self.assertEqual(child["formulation_ref"], parent["formulation_ref"])
        code = json.loads((path / child["code_ref"]["relative_path"]).read_text())
        self.assertEqual(code["source_formulation_ref"], parent["formulation_ref"])
        self.assertNotEqual(code["provenance"]["generation"]["call_id"],
            json.loads((path / parent["formulation_ref"]["relative_path"]).read_text())["provenance"]["call_id"])
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(solve["evidence_origin"], "trusted_container_worker")
        self.assertEqual(len(requests), 2)
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 2)

    def test_code_label_cannot_hide_a_changed_mathematical_domain(self) -> None:
        self.settings["method"]["config"]["output_mode"] = "python_factory"
        self.settings["executor"] = {"plugin_id": "llm4om.executors.container", "config": {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 512, "wall_time_s": 15}}
        self.settings["budget"]["max_repairs"] = 1
        first = {"representation": self.compact["representation"], "python_factory": "def build_model(data):\n    broken !\n"}
        second = {"representation": deepcopy(self.compact["representation"]),
            "python_factory": (ROOT / "examples/factories/production.py").read_text(),
            "repair_stage": "code", "change_reason": "Relax the decision domain but label this a code fix."}
        second["representation"]["variables"][0]["domain"] = "continuous"
        path, bundle, requests = self.run_responses([first, second])
        self.assertEqual(bundle["status"], "failed")
        assessment = json.loads((path / "candidates/002/assessment.json").read_text())
        self.assertEqual(assessment["diagnostics"][0]["code"], "invalid_code_repair")
        self.assertEqual(json.loads((path / "candidates/002/formulation-changes.json").read_text())["changed_sections"], ["variables"])
        self.assertEqual(len(requests), 2)
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 1)

    def test_native_gurobi_code_repair_uses_real_isolated_solver_and_source_formulation(self) -> None:
        self.settings["method"]["config"]["output_mode"] = "native_gurobipy"
        self.settings["model_backend"]["plugin_id"] = "llm4om.model_backends.gurobipy"
        self.settings["solver"]["plugin_id"] = "llm4om.solvers.gurobi"
        self.settings["executor"] = {"plugin_id": "llm4om.executors.container", "config": {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 512, "wall_time_s": 15}}
        first = {"representation": self.compact["representation"], "native_gurobipy": "def build_model(data):\n    broken !\n"}
        second = {"native_gurobipy": (ROOT / "examples/factories/production_gurobi.py").read_text(),
            "repair_stage": "code", "change_reason": "Correct the Python source while preserving the source mathematical formulation."}
        path, bundle, requests = self.run_responses([first, second])
        self.assertEqual(bundle["status"], "completed", bundle.get("error"))
        parent = json.loads((path / "candidates/001/formulation-snapshot.json").read_text())
        child = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
        self.assertEqual(child["formulation_ref"], parent["formulation_ref"])
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual((solve["solver_id"], solve["objective_value"]), ("llm4om.solvers.gurobi", 13))
        self.assertEqual(len(requests), 2)

    def test_crash_before_method_accepts_assessment_replays_without_credentials_or_more_budget(self) -> None:
        self.settings["budget"].update(max_candidates=1, max_repairs=0, max_llm_attempts=1, max_solver_calls=1)
        script = '''import json, os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    if Path(target).name == "events.jsonl" and "history" not in Path(target).parts:
        record = json.loads(Path(target).read_text().splitlines()[-1])
        if record.get("kind") == "candidate_assessed":
            os._exit(91)
    return result
os.replace = crash
sys.exit(main())'''
        path, bundle, requests = self.run_responses([self.compact], crash_script=script)
        self.assertEqual(bundle["status"], "completed", bundle.get("error"))
        self.assertEqual(len(requests), 1)
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["solver_calls"], ledger["external_llm_requests"]), (1, 1, 1))

    def test_legitimate_infeasibility_is_selectable_without_deleting_constraints(self) -> None:
        import hashlib
        capacities = self.inputs / "data/capacities.csv"
        capacities.write_text("resource_id,capacity\ncutting,-1\nfinishing,8\n")
        problem = json.loads((self.inputs / "problem.json").read_text())
        for data in problem["data_refs"]:
            if data["data_id"] == "capacities":
                data["sha256"] = hashlib.sha256(capacities.read_bytes()).hexdigest()
        (self.inputs / "problem.json").write_text(json.dumps(problem))
        self.compact["structured_ir"]["constraints"][0]["rhs"] = -1
        self.settings["budget"]["max_repairs"] = 0
        path, bundle, requests = self.run_responses([self.compact])
        self.assertEqual(bundle["status"], "completed", bundle.get("error"))
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["termination"], "infeasible")
        self.assertFalse(solve["has_primal_solution"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(bundle["final_candidate_id"], "001")

    def test_pending_unknown_request_does_not_resend_on_method_resume(self) -> None:
        script = '''import json, os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    if Path(target).name == "state.json":
        value = json.loads(Path(target).read_text())
        if value.get("attempts") and value["attempts"][-1]["status"] == "unknown":
            os._exit(91)
    return result
os.replace = crash
sys.exit(main())'''
        path, bundle, requests = self.run_responses([self.compact], crash_script=script)
        self.assertEqual(bundle["status"], "failed")
        self.assertEqual(bundle["error"]["code"], "provider_outcome_unknown")
        self.assertEqual(len(requests), 0)
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["external_llm_requests"], 1)
        self.assertGreater(ledger["reserved_tokens"], 0)
        self.assertEqual(ledger["solver_calls"], 0)
