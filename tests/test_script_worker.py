"""Original scripts run in the actual isolated Worker, never in this process."""

import hashlib
import json
import time
import unittest

from llm4om.executors import run_container, DEFAULT_IMAGE


class ScriptWorkerTests(unittest.TestCase):
    def capture(self, source):
        raw = source.encode()
        request = {"schema_version": "0.1.0", "source_sha256": hashlib.sha256(raw).hexdigest(),
                   "data_json": "{}", "wall_time_s": 5, "output_limit_bytes": 1048576}
        result = run_container(["python", "-I", "-m", "llm4om.script_worker", "/input/request.json"],
            {"request.json": json.dumps(request).encode(), "model.py": raw},
            {"network": False, "cpu_limit": 1, "memory_limit_mb": 512, "wall_time_s": 10},
            image=DEFAULT_IMAGE, deadline=time.time() + 15)
        self.assertEqual(result.exit_code, 0, result.stderr.decode())
        return json.loads(result.stdout)

    def test_multiple_models_cannot_supply_a_supported_capture(self):
        payload = self.capture('''from gurobipy import Model
first = Model()
x = first.addVar(ub=1, name="x")
first.optimize()
second = Model()
''')
        self.assertEqual(payload["source"]["exit_code"], 0)
        self.assertIsNone(payload["capture"]["transport"])
        self.assertEqual(payload["capture"]["error"], "multiple_script_models")

    def test_raw_script_keeps_exit_diagnostics_and_exports_before_optimize(self):
        source = b'''import json
from gurobipy import Model, GRB
with open("data.json") as stream:
    raw = stream.read()
    assert raw == '{"capacity":4}\\n'
    data = json.loads(raw)
model = Model("public")
x = model.addVar(name="x", vtype=GRB.INTEGER)
model.addConstr(x <= data["capacity"])
model.setObjective(3*x, GRB.MAXIMIZE)
model.optimize()
print("SOURCE", model.ObjVal)
raise RuntimeError("after optimize")
'''
        request = {"schema_version": "0.1.0", "source_sha256": hashlib.sha256(source).hexdigest(),
                   "data_json": '{"capacity":4}\n', "wall_time_s": 15, "output_limit_bytes": 1048576}
        result = run_container(["python", "-I", "-m", "llm4om.script_worker", "/input/request.json"],
            {"request.json": json.dumps(request).encode(), "model.py": source},
            {"network": False, "cpu_limit": 1, "memory_limit_mb": 512, "wall_time_s": 20},
            image=DEFAULT_IMAGE, deadline=time.time() + 30)
        self.assertEqual(result.exit_code, 0, result.stderr.decode())
        payload = json.loads(result.stdout)
        self.assertEqual(payload["source"]["exit_code"], 1)
        self.assertIn("SOURCE 12", payload["source"]["stdout"])
        self.assertIn("after optimize", payload["source"]["stderr"])
        self.assertEqual(payload["capture"]["source_sha256"], request["source_sha256"])
        self.assertEqual(payload["capture"]["optimize_calls"], 1)
        self.assertEqual(payload["capture"]["transport"]["decision_map"], {"x": "x"})
        collection = {"schema_version": "0.1.0", "transport": payload["capture"]["transport"],
                      "source_sha256": request["source_sha256"], "solver_options": {"time_limit_s": 10},
                      "allowed_problem_types": ["lp", "milp"]}
        collected = run_container(["python", "-I", "-m", "llm4om.worker", "--collect-native",
                                   "/input/capture.json", "--solver", "llm4om.solvers.gurobi"],
            {"capture.json": json.dumps(collection).encode()},
            {"network": False, "cpu_limit": 1, "memory_limit_mb": 512, "wall_time_s": 20},
            image=DEFAULT_IMAGE, deadline=time.time() + 30)
        self.assertEqual(collected.exit_code, 0, collected.stderr.decode())
        trusted = json.loads(collected.stdout)
        self.assertEqual(trusted["result"]["variables"], {"x": 4})
        self.assertEqual(trusted["result"]["objective_value"], 12)
        self.assertEqual(trusted["result"]["evidence_origin"], "trusted_gurobi_api")
