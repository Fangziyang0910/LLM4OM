"""Natural-language method runs with HTTP fixtures and real isolated Solvers."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml

from llm4om import run_problem


ROOT = Path(__file__).resolve().parents[1]
CODE = '''import gurobipy as gp
m = gp.Model()
x = m.addVar(lb=0, vtype=gp.GRB.INTEGER, name="qty_A")
y = m.addVar(lb=0, vtype=gp.GRB.INTEGER, name="qty_B")
m.addConstr(2*x+y<=8)
m.addConstr(x+2*y<=8)
m.setObjective(3*x+2*y, gp.GRB.MAXIMIZE)
m.optimize()
'''


class ResearchMethodRunTests(unittest.TestCase):
    def run_case(self, method, replies, *, native=True):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                request = json.loads(inner.rfile.read(int(inner.headers["Content-Length"])))
                requests.append(request)
                value = replies[len(requests) - 1]
                inner.send_response(200)
                inner.end_headers()
                inner.wfile.write(json.dumps({"choices": [{"message": {"content": value if isinstance(value, str) else json.dumps(value)},
                    "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}}).encode())
            def log_message(inner, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        problem = json.loads((ROOT / "examples/specs/problem.json").read_text())
        problem["data_refs"] = []
        problem["description"] = "Choose nonnegative integer quantities A and B. Maximize 3A+2B, subject to 2A+B<=8 and A+2B<=8."
        (root / "problem.json").write_text(json.dumps(problem))
        config = yaml.safe_load((ROOT / "examples/specs/gurobi.yaml").read_text())
        config["method"] = {"plugin_id": "llm4om.methods." + method, "config": {"rollouts": 1} if method == "autoformulation" else {}}
        config["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "public-fixture",
            "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "RESEARCH_METHOD_TEST_KEY",
                "max_retries": 0, "max_output_tokens": 2048}}
        config["budget"].update(max_llm_attempts=20, max_total_tokens=50000, max_solver_calls=6,
            max_candidates=2, max_repairs=2, wall_time_s=150)
        if native:
            config.pop("compiler")
            config["model_backend"]["plugin_id"] = "llm4om.model_backends.gurobipy"
        else:
            config["solver"]["plugin_id"] = "llm4om.solvers.ortools"
        (root / "config.yaml").write_text(yaml.safe_dump(config))
        with patch.dict(os.environ, {"RESEARCH_METHOD_TEST_KEY": "fixture-not-a-real-key"}):
            result = run_problem(root / "problem.json", root / "config.yaml", output_root=root / "runs")
        path = result.bundle_path
        bundle = json.loads((path / "bundle.json").read_text())
        error = bundle.get("error") or {}
        details = json.loads((path / error["details_ref"]["relative_path"]).read_text()) if error.get("details_ref") else None
        self.assertEqual(bundle["status"], "completed", {"error": error, "details": details})
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(len(requests), len(replies))
        artifact = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
        formulation = json.loads((path / artifact["formulation_ref"]["relative_path"]).read_text())
        self.assertEqual(formulation["data_bindings"], [])
        self.assertTrue((path / "method/fidelity-report.json").is_file())
        return path, bundle

    def test_or_llm_agent_debugs_and_collects_real_gurobi_without_parameter_files(self):
        path, _ = self.run_case("or_llm_agent", ["max 3A+2B, 2A+B<=8, A+2B<=8, A,B nonnegative integers",
            "raise ValueError('fixture runtime failure')", CODE])
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["script_executions"], 2)
        self.assertEqual(ledger["collector_calls"], 1)

    def test_optitree_retrieves_thoughts_and_collects_real_gurobi(self):
        self.run_case("optitree", [{"matching_problem_type": "not found", "belongs_to_problem_types": False},
            {"formulation": "max 3A+2B; 2A+B<=8; A+2B<=8; A,B nonnegative integers", "code": CODE}])

    def test_autoformulation_search_compiles_and_solves_with_real_ortools(self):
        replies = []
        for stage in ("parameters", "decision_variables", "objective", "equality_constraints", "inequality_constraints"):
            replies.extend([{"hypotheses": [stage]}, {"scores": [0.9]}])
        representation = deepcopy(json.loads((ROOT / "examples/specs/formulation.json").read_text())["representation"])
        for parameter in representation["parameters"]:
            parameter.pop("source", None)
            parameter["value"] = {"profit": [3, 2], "usage": [[2, 1], [1, 2]], "capacity": [8, 8]}[parameter["id"]]
        ir = json.loads((ROOT / "examples/specs/model-ir.json").read_text())
        replies.extend([{"representation": representation, "structured_ir": {
            key: ir[key] for key in ("problem_type", "variables", "objective", "constraints", "assumptions")}},
            {"score": 0.95, "reason": "Every public requirement is represented."}])
        path, _ = self.run_case("autoformulation", replies, native=False)
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["solver_calls"], 1)
        self.assertEqual(ledger["candidates"], 1)
