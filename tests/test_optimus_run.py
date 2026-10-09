"""Synthetic HTTP plus actual isolated Gurobi through the shared SDK."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml

from llm4om import CancellationToken, run_problem, resume_run
from test_optimus_method import REPLIES


class OptimusRunTests(unittest.TestCase):
    def run_case(self, replies=REPLIES, *, budget=None, crash=False, rag_mode=None, cancel_at_source=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        requests = []
        cancellation = CancellationToken()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(request)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": replies[len(requests)-1]},
                    "finish_reason": "stop"}], "usage": {"prompt_tokens": 200, "completion_tokens": 100,
                    "total_tokens": 300}}).encode())
                if cancel_at_source and len(requests) == len(replies):
                    threading.Timer(1, cancellation.cancel).start()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        (root / "params.json").write_text(json.dumps({"Capacity": {"value": 4, "shape": [], "definition": "capacity"}}))
        (root / "labels.json").write_text('{"type":[],"domain":[]}')
        problem = {"schema_version": "0.3.0", "problem_id": "public", "revision": "1",
            "description": "Maximize profit 3x with integer production x <= Capacity.", "language": "en",
            "problem_type_hint": "milp", "requirements": [], "assumptions": [], "source": {"kind": "hand_authored"},
            "data_refs": [{"data_id": name, "path": name + ".json", "format": "json", "schema": {"type": "object"},
                           "sha256": None} for name in ("params", "labels")]}
        (root / "problem.json").write_text(json.dumps(problem))
        config = yaml.safe_load((Path(__file__).parents[1] / "examples/specs/gurobi.yaml").read_text())
        config["method"] = {"plugin_id": "llm4om.methods.optimus", "config": {
            "rag_mode": rag_mode, "params_data_id": "params", "labels_data_id": "labels"}}
        config.pop("compiler")
        config["model_backend"]["plugin_id"] = "llm4om.model_backends.gurobipy"
        config["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "synthetic-tape",
            "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "S06B_SYNTHETIC_KEY",
                       "max_output_tokens": 1024, "max_retries": 0}}
        config["budget"].update(max_llm_attempts=30, max_total_tokens=100000, max_solver_calls=6, max_repairs=3, wall_time_s=120)
        if budget is not None:
            config["budget"].update(budget)
        (root / "config.yaml").write_text(yaml.safe_dump(config))
        with patch.dict(os.environ, {"S06B_SYNTHETIC_KEY": "synthetic-no-real-key"}):
            if crash:
                import subprocess, sys
                script = """
import os, sys
from pathlib import Path
from llm4om.cli import main
crash_point = sys.argv.pop(1)
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    path = Path(target)
    if crash_point == 'admitted' and path.name == 'checkpoint.json':
        import json
        state = json.loads(path.read_text())['payload']['state']
        if state.get('method_executions'):
            os._exit(91)
    if crash_point != 'admitted' and path.name == 'result.json' and 'executions' in path.parts and 'history' not in path.parts:
        os._exit(91)
    return result
os.replace = crash
raise SystemExit(main())
"""
                completed = subprocess.run([sys.executable, "-c", script, "admitted" if crash == "admitted" else "published", "run", "--problem", str(root / "problem.json"),
                    "--config", str(root / "config.yaml"), "--output", str(root / "runs")], capture_output=True, timeout=60)
                self.assertEqual(completed.returncode, 91, completed.stderr.decode())
                path = next(item for item in (root / "runs").iterdir() if len(item.name) == 32)
                result = resume_run(path)
            else:
                result = run_problem(root / "problem.json", root / "config.yaml", output_root=root / "runs",
                                     cancellation=cancellation)
        bundle = json.loads((result.bundle_path / "bundle.json").read_text())
        return result, bundle, requests

    def test_complete_source_workflow_uses_final_execution_once(self):
        result, bundle, requests = self.run_case()
        self.assertEqual(result.status, "completed", bundle["error"])
        self.assertEqual(len(requests), 9)
        solved = json.loads((result.bundle_path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solved["objective_value"], 12)
        ledger = json.loads((result.bundle_path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["solver_calls"], 2)
        self.assertEqual(ledger["script_executions"], 1)
        self.assertEqual(ledger["collector_calls"], 1)

        recovered = resume_run(result.bundle_path)
        self.assertEqual(recovered.status, "completed")
        self.assertEqual(len(requests), 9)

    def test_execution_publication_crash_reuses_the_matching_result(self):
        result, bundle, requests = self.run_case(crash=True)
        self.assertEqual(result.status, "completed", bundle["error"])
        self.assertEqual(len(requests), 9)
        ledger = json.loads((result.bundle_path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["solver_calls"], 2)

    def test_unknown_admitted_script_is_not_executed_again(self):
        result, bundle, requests = self.run_case(crash="admitted")
        self.assertEqual(result.status, "failed")
        self.assertEqual(bundle["error"]["code"], "execution_outcome_unknown")
        self.assertEqual(len(requests), 9)
        ledger = json.loads((result.bundle_path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["script_executions"], 1)
        self.assertEqual(ledger.get("collector_calls", 0), 0)

    def test_cancelling_source_removes_owned_container(self):
        replies = list(REPLIES)
        replies[-1] = "=====\nimport time\ntime.sleep(30)\nmodel.setObjective(3*x, GRB.MAXIMIZE)\n====="
        result, bundle, requests = self.run_case(replies, cancel_at_source=True)
        self.assertEqual(result.status, "cancelled", bundle["error"])
        self.assertEqual(bundle["error"]["code"], "run_cancelled")
        self.assertEqual(len(requests), 9)
        worker = json.loads((result.bundle_path / "method/executions/source-code/worker.json").read_text())
        self.assertEqual(worker["status"], "cancelled")
        import subprocess
        self.assertTrue(worker["container_id"])
        inspected = subprocess.run(["docker", "inspect", worker["container_id"]], capture_output=True)
        self.assertNotEqual(inspected.returncode, 0)

    def test_lp_uses_actual_continuous_native_model(self):
        replies = list(REPLIES)
        replies[4] = replies[4].replace('"integer"', '"continuous"')
        result, bundle, requests = self.run_case(replies)
        self.assertEqual(result.status, "completed", bundle["error"])
        solved = json.loads((result.bundle_path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solved["objective_value"], 12)

    def test_collector_failure_does_not_trigger_source_repair(self):
        replies = list(REPLIES)
        replies[-1] = "=====\nmodel.setObjective(x*x, GRB.MAXIMIZE)\n====="
        result, bundle, requests = self.run_case(replies)
        self.assertEqual(result.status, "failed")
        self.assertEqual(bundle["error"]["code"], "collector_failed")
        self.assertEqual(len(requests), 9)
        self.assertIsNone(bundle["solve_result_ref"])

    def test_solver_budget_stops_before_script_admission(self):
        result, bundle, requests = self.run_case(budget={"max_solver_calls": 1})
        self.assertEqual(bundle["error"]["code"], "budget_exhausted")
        ledger = json.loads((result.bundle_path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["solver_calls"], 0)

    def test_requested_rag_fails_before_http(self):
        result, bundle, requests = self.run_case(rag_mode="problem_labels")
        self.assertEqual(result.status, "failed")
        self.assertEqual(requests, [])
