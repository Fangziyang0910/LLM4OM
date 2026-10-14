"""Every automatic method composes with the three real isolated Solvers."""

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

from llm4om import CancellationToken, run_problem, resume_run
from llm4om.workbench import method_presets

ROOT = Path(__file__).resolve().parents[1]
MATH = "max 3A+2B; 2A+B<=8; A+2B<=8; A,B nonnegative integers"
CODE = '''import pyomo.environ as pyo
from llm4om.backends import ModelHandle
def build_model(data):
    m = pyo.ConcreteModel()
    m.x = pyo.Var(domain=pyo.NonNegativeIntegers)
    m.y = pyo.Var(domain=pyo.NonNegativeIntegers)
    m.c1 = pyo.Constraint(expr=2*m.x+m.y<=8)
    m.c2 = pyo.Constraint(expr=m.x+2*m.y<=8)
    m.obj = pyo.Objective(expr=3*m.x+2*m.y, sense=pyo.maximize)
    return ModelHandle(m, {"qty_A": m.x, "qty_B": m.y})
'''
NATIVE_CODE = '''import gurobipy as gp
from llm4om.backends import ModelHandle
def build_model(data):
    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 0)
    env.setParam("LogFile", "")
    env.start()
    m = gp.Model(env=env)
    x = m.addVar(lb=0, vtype=gp.GRB.INTEGER, name="qty_A")
    y = m.addVar(lb=0, vtype=gp.GRB.INTEGER, name="qty_B")
    m.addConstr(2*x+y<=8)
    m.addConstr(x+2*y<=8)
    m.setObjective(3*x+2*y, gp.GRB.MAXIMIZE)
    m.update()
    return ModelHandle(m, {"qty_A": x, "qty_B": y})
'''


def compact():
    representation = deepcopy(json.loads((ROOT / "examples/specs/formulation.json").read_text())["representation"])
    for parameter in representation["parameters"]:
        parameter.pop("source", None)
        parameter["value"] = {"profit": [3, 2], "usage": [[2, 1], [1, 2]], "capacity": [8, 8]}[parameter["id"]]
    ir = json.loads((ROOT / "examples/specs/model-ir.json").read_text())
    return {"representation": representation, "structured_ir": {
        key: ir[key] for key in ("problem_type", "variables", "objective", "constraints", "assumptions")}}


def method_replies(method, code=CODE):
    if method in ("direct", "feedback_repair"):
        return [compact()]
    if method == "autoformulation":
        replies = []
        for stage in ("parameters", "decision_variables", "objective", "equality_constraints", "inequality_constraints"):
            replies.extend([{"hypotheses": [stage]}, {"scores": [0.9]}])
        return replies + [compact(), {"score": 0.95, "reason": "All public requirements are represented."}]
    if method in ("optimus", "optimus_inline"):
        return [{"capacity": {"value": 8, "shape": [], "definition": "resource capacity"}}, "maximize 3A+2B",
            {"constraints": ["2A+B<=8", "A+2B<=8, A and B nonnegative integers"]},
            {"formulation": "2A+B<=8", "new_variables": {"A": {"domain": "integer", "lower_bound": 0},
                "B": {"domain": "integer", "lower_bound": 0}}, "auxiliary_constraints": []},
            {"formulation": "A+2B<=8", "new_variables": {}, "auxiliary_constraints": []}, "max 3A+2B", code]
    if method == "coe":
        return ["Programming Expert", "Use two nonnegative integer decisions and both resource limits.",
            {"formulation": MATH, "code": code}]
    if method == "optitree":
        return [{"matching_problem_type": "not found", "belongs_to_problem_types": False}, {"formulation": MATH, "code": code}]
    return [MATH, code]


class RunHarness(unittest.TestCase):
    def run_case(self, method, replies=None, *, solver="highs", backend="pyomo_factory", expected="completed",
                 expected_calls=None, method_config=None, budget=None, data=None, cancel=False, expected_objective=13):
        replies = method_replies(method) if replies is None else replies
        requests = []
        cancellation = CancellationToken()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                request = json.loads(inner.rfile.read(int(inner.headers["Content-Length"])))
                requests.append(request)
                value = replies[len(requests) - 1]
                inner.send_response(200)
                inner.end_headers()
                inner.wfile.write(json.dumps({"choices": [{"message": {"content": value if isinstance(value, str) else json.dumps(value)},
                    "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}}).encode())
                if cancel and len(requests) == len(replies):
                    threading.Timer(2, cancellation.cancel).start()
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
        problem["schema_version"] = "0.3.0"
        problem["data_refs"] = []
        problem["description"] = "Choose nonnegative integer quantities A and B. Maximize 3A+2B, subject to 2A+B<=8 and A+2B<=8."
        for name, value in (data or {}).items():
            (root / (name + ".json")).write_bytes(value)
            problem["data_refs"].append({"data_id": name, "path": name + ".json", "format": "json", "schema": {"type": "object"}, "sha256": None})
        (root / "problem.json").write_text(json.dumps(problem))
        config = yaml.safe_load((ROOT / "examples/specs/gurobi.yaml").read_text())
        preset = method_presets()["llm4om.methods." + method]
        method_settings = {**preset["config"], **(method_config or {})}
        if method == "autoformulation":
            method_settings["rollouts"] = 1
        if method == "coe":
            method_settings.setdefault("max_collaborate_nums", 1)
            method_settings["enable_reflection"] = (method_config or {}).get("enable_reflection", False)
        config["method"] = {"plugin_id": "llm4om.methods." + method, "config": method_settings}
        config["solver"]["plugin_id"] = "llm4om.solvers." + solver
        config["model_backend"]["plugin_id"] = "llm4om.model_backends." + backend
        if method not in ("direct", "feedback_repair", "autoformulation"):
            config.pop("compiler")
        config["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "public-fixture",
            "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "RESEARCH_METHOD_TEST_KEY",
                "max_retries": 0, "max_output_tokens": 2048}}
        config["budget"].update({"max_llm_attempts": 30, "max_total_tokens": 100000, "max_solver_calls": 4,
            "max_candidates": 4, "max_repairs": 2, "wall_time_s": 150, **(budget or {})})
        (root / "config.yaml").write_text(yaml.safe_dump(config))
        with patch.dict(os.environ, {"RESEARCH_METHOD_TEST_KEY": "fixture-not-a-real-key"}):
            result = run_problem(root / "problem.json", root / "config.yaml", output_root=root / "runs", cancellation=cancellation)
        path = result.bundle_path
        bundle = json.loads((path / "bundle.json").read_text())
        error = bundle.get("error") or {}
        details = json.loads((path / error["details_ref"]["relative_path"]).read_text()) if error.get("details_ref") else None
        self.assertEqual(bundle["status"], expected, {"error": error, "details": details})
        self.assertEqual(len(requests), len(replies) if expected_calls is None else expected_calls)
        if expected == "completed":
            solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
            self.assertEqual(solve["objective_value"], expected_objective)
            self.assertEqual(solve["solver_id"], config["solver"]["plugin_id"])
            self.assertEqual(solve["model_backend"], config["model_backend"]["plugin_id"])
            self.assertEqual(solve["evidence_origin"], "trusted_container_worker")
            artifact = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
            formulation = json.loads((path / artifact["formulation_ref"]["relative_path"]).read_text())
            self.assertEqual(formulation["data_bindings"], artifact["data_bindings"])
        return path, bundle, requests


class ResearchMethodRunTests(RunHarness):
    def test_all_seven_methods_with_all_three_real_solvers(self):
        for method in ("direct", "feedback_repair", "optimus", "coe", "optitree", "or_llm_agent", "autoformulation"):
            for solver in ("highs", "gurobi", "ortools"):
                with self.subTest(method=method, solver=solver):
                    path, _, requests = self.run_case(method, solver=solver)
                    ledger = json.loads((path / "budget-ledger.json").read_text())
                    self.assertEqual(ledger["solver_calls"], 1)
                    self.assertEqual(ledger["candidates"], 1)
                    if method in ("optimus", "coe", "optitree", "or_llm_agent"):
                        self.assertIn("llm4om.solvers." + solver, json.dumps(requests))
                        report = json.loads((path / "method/fidelity-report.json").read_text())
                        self.assertEqual(report["code_target"]["solver"], "llm4om.solvers." + solver)

    def test_native_backend_changes_target_for_each_prompt_workflow(self):
        for method in ("optimus", "coe", "optitree", "or_llm_agent"):
            with self.subTest(method=method):
                self.run_case(method, method_replies(method, NATIVE_CODE), solver="gurobi", backend="gurobipy")

    def test_debug_repair_uses_selected_solver_and_does_not_solve_the_final_candidate_twice(self):
        replies = [MATH, "raise ValueError('fixture runtime failure')", CODE]
        path, _, requests = self.run_case("or_llm_agent", replies, solver="ortools")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["solver_calls"], ledger["candidates"], ledger["repairs"]), (2, 2, 1))
        self.assertIn("llm4om.solvers.ortools", json.dumps(requests[-1]))
        self.assertEqual(resume_run(path).status, "completed")
        self.assertEqual(len(requests), 3)
