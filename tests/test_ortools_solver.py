"""Real OR-Tools solving through the public Backend/Solver contract."""

import unittest
import json
import subprocess
import sys

from llm4om.contracts import RunError
from llm4om.linear import compile_ir
from llm4om.solvers import solve
from test_linear_solver import model, row


class ORToolsSolverTests(unittest.TestCase):
    def test_highs_and_ortools_solve_in_either_library_load_order(self):
        for order in (("highs", "ortools"), ("ortools", "highs")):
            with self.subTest(order=order):
                script = "from llm4om.linear import compile_ir\nfrom llm4om.solvers import solve\nimport json\n"
                script += "ir=json.loads(" + repr(json.dumps(model(upper=3))) + ")\n"
                script += "for engine in " + repr(order) + ":\n"
                script += "    result=solve(compile_ir(ir),{},'llm4om.solvers.'+engine)\n"
                script += "    assert result['termination']=='optimal' and result['objective_value']==3\n"
                process = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
    def solve(self, ir, options=None):
        return solve(compile_ir(ir), options or {}, "llm4om.solvers.ortools")

    def test_continuous_and_integer_models_preserve_constants_and_bounds(self):
        for domain, expected in (("continuous", 3.5), ("integer", 3)):
            with self.subTest(domain=domain):
                ir = model(domain)
                ir["objective"]["expression"]["constant"] = 7
                ir["constraints"] = [row("le", 4.5, constant=1)]
                result = self.solve(ir)
                self.assertEqual(result["termination"], "optimal")
                self.assertAlmostEqual(result["variables"]["x"], expected)
                self.assertAlmostEqual(result["objective_value"], 7 + expected)
                self.assertEqual(result["evidence_origin"], "trusted_ortools_api")

    def test_infeasible_unbounded_and_constant_models(self):
        ir = model()
        ir["constraints"] = [row("ge", 2), {**row("le", 1), "id": "other"}]
        result = self.solve(ir)
        self.assertEqual(result["termination"], "infeasible")
        self.assertIsNone(result["variables"])
        self.assertEqual(self.solve(model())["termination"], "unbounded")
        ir["variables"], ir["constraints"] = [], []
        ir["objective"]["expression"] = {"constant": 7, "terms": []}
        self.assertAlmostEqual(self.solve(ir)["objective_value"], 7)

    def test_invalid_options_are_rejected(self):
        for options in ({"time_limit_s": -1}, {"time_limit_s": True}, {"unsupported": 1}):
            with self.subTest(options=options), self.assertRaises(RunError):
                self.solve(model(upper=3), options)
