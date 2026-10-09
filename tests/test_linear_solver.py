"""Independent micro-models at the approved Compiler and Solver interfaces."""

import unittest

from llm4om.contracts import RunError
from llm4om.highs import solve_highs
from llm4om.linear import compile_ir


def model(domain: str = "continuous", lower: float | None = 0, upper: float | None = None) -> dict:
    return {
        "schema_version": "0.1.0", "ir_kind": "grounded_lp", "problem_type": "lp" if domain == "continuous" else "milp",
        "model_id": "micro-model", "problem_id": "micro-problem", "problem_revision": "1", "data_bindings": [],
        "variables": [{"id": "x", "name": "x", "domain": domain, "lower_bound": lower,
                       "upper_bound": upper, "requirement_ids": []}],
        "objective": {"sense": "max", "expression": {"constant": 0, "terms": [{"variable_id": "x", "coefficient": 1}]},
                      "requirement_ids": []},
        "constraints": [], "assumptions": [], "provenance": {"origin": "hand_authored_solver_fixture"},
    }


def row(sense: str, rhs: float, constant: float = 0) -> dict:
    return {"id": "row", "sense": sense, "rhs": rhs,
            "expression": {"constant": constant, "terms": [{"variable_id": "x", "coefficient": 1}]}, "requirement_ids": []}


class LinearSolverTests(unittest.TestCase):
    def test_constant_problem_with_no_original_variables_is_solved(self) -> None:
        ir = model()
        ir["variables"] = []
        ir["objective"]["expression"] = {"constant": 7, "terms": []}
        result = solve_highs(compile_ir(ir), {})
        self.assertEqual(result["termination"], "optimal")
        self.assertEqual(result["variables"], {})
        self.assertAlmostEqual(result["objective_value"], 7)

    def test_constants_equality_minimization_and_duplicate_terms_keep_their_meaning(self) -> None:
        ir = model()
        ir["objective"]["expression"]["constant"] = 7
        ir["objective"]["expression"]["terms"].append({"variable_id": "x", "coefficient": 2})
        ir["constraints"] = [row("le", 4, constant=1)]
        result = solve_highs(compile_ir(ir), {})
        self.assertEqual(result["termination"], "optimal")
        self.assertAlmostEqual(result["variables"]["x"], 3)
        self.assertAlmostEqual(result["objective_value"], 16)
        ir["objective"]["sense"] = "min"
        ir["objective"]["expression"] = {"constant": -7, "terms": [{"variable_id": "x", "coefficient": -2}]}
        ir["constraints"] = [row("eq", 5, constant=2)]
        result = solve_highs(compile_ir(ir), {})
        self.assertAlmostEqual(result["variables"]["x"], 3)
        self.assertAlmostEqual(result["objective_value"], -13)

    def test_integer_fractional_bounds_and_binary_intersection_are_preserved(self) -> None:
        ir = model("integer", lower=0.2, upper=2.8)
        ir["objective"]["sense"] = "min"
        result = solve_highs(compile_ir(ir), {})
        self.assertAlmostEqual(result["variables"]["x"], 1)
        ir = model("binary", lower=-2, upper=4)
        result = solve_highs(compile_ir(ir), {})
        self.assertAlmostEqual(result["variables"]["x"], 1)

    def test_infeasible_and_unbounded_termination_remain_distinct(self) -> None:
        ir = model()
        ir["constraints"] = [row("ge", 2), {**row("le", 1), "id": "other"}]
        result = solve_highs(compile_ir(ir), {})
        self.assertEqual(result["termination"], "infeasible")
        self.assertFalse(result["has_primal_solution"])
        self.assertIsNone(result["variables"])
        self.assertIsNone(result["objective_value"])
        result = solve_highs(compile_ir(model()), {})
        self.assertEqual(result["termination"], "unbounded")
        self.assertEqual(result["raw_status"], "kUnbounded")
        result = solve_highs(compile_ir(model("integer", lower=0.2, upper=0.8)), {})
        self.assertEqual(result["termination"], "infeasible")
        self.assertIsNone(result["best_bound"])
        self.assertIsNone(result["reported_gap"])

    def test_unsupported_structures_domains_and_nonfinite_numbers_are_rejected(self) -> None:
        for kind in ["duplicate", "bounds", "lp_integer", "nonlinear", "nan", "boolean"]:
            with self.subTest(kind=kind):
                ir = model()
                if kind == "duplicate":
                    ir["variables"].append(dict(ir["variables"][0]))
                elif kind == "bounds":
                    ir["variables"][0].update(lower_bound=2, upper_bound=1)
                elif kind == "lp_integer":
                    ir["variables"][0]["domain"] = "integer"
                elif kind == "nonlinear":
                    ir["objective"]["expression"]["quadratic_terms"] = []
                else:
                    ir["objective"]["expression"]["constant"] = float("nan") if kind == "nan" else True
                with self.assertRaises(RunError) as error:
                    compile_ir(ir)
                self.assertEqual(error.exception.code, "invalid_ir")

    def test_compilation_is_deterministic_and_omits_nonmathematical_metadata(self) -> None:
        ir = model(upper=3)
        ir["provenance"]["unused_note"] = "PRIVATE-METADATA-NOT-NEEDED-IN-CODE"
        first = compile_ir(ir)
        self.assertEqual(first.source, compile_ir(ir).source)
        self.assertNotIn("PRIVATE-METADATA-NOT-NEEDED-IN-CODE", first.source)

    def test_overflow_during_constraint_shift_is_rejected(self) -> None:
        ir = model()
        ir["constraints"] = [row("le", -1e308, constant=1e308)]
        with self.assertRaises(RunError) as error:
            compile_ir(ir)
        self.assertEqual(error.exception.code, "invalid_ir")

    def test_solver_validates_and_honors_numeric_time_limits(self) -> None:
        code = compile_ir(model(upper=3))
        for options in [{"unsupported": 1}, {"time_limit_s": -1}, {"time_limit_s": float("nan")},
                        {"time_limit_s": True}, {"time_limit_s": 10**400}]:
            with self.subTest(options=options):
                with self.assertRaises(RunError) as error:
                    solve_highs(code, options)
                self.assertEqual(error.exception.code, "invalid_solver_options")
        result = solve_highs(code, {"time_limit_s": 2147483648})
        self.assertEqual(result["termination"], "optimal")

    def test_overflow_when_merging_repeated_terms_is_rejected(self) -> None:
        ir = model(upper=3)
        ir["objective"]["expression"]["terms"] = [{"variable_id": "x", "coefficient": 1e308}] * 2
        with self.assertRaises(RunError) as error:
            compile_ir(ir)
        self.assertEqual(error.exception.code, "invalid_ir")

    def test_integer_literals_that_cannot_be_preserved_as_doubles_are_rejected(self) -> None:
        ir = model("integer", lower=9007199254740993, upper=9007199254740993)
        with self.assertRaises(RunError) as error:
            compile_ir(ir)
        self.assertEqual(error.exception.code, "invalid_ir")
        ir = model(upper=3)
        ir["objective"]["expression"]["terms"] = [
            {"variable_id": "x", "coefficient": 9007199254740992},
            {"variable_id": "x", "coefficient": 1},
        ]
        with self.assertRaises(RunError) as error:
            compile_ir(ir)
        self.assertEqual(error.exception.code, "invalid_ir")

    def test_solver_rejects_numbers_that_highs_would_silently_change(self) -> None:
        cases = [model(upper=1e30), model(), model()]
        cases[1]["constraints"] = [row("le", 1)]
        cases[1]["constraints"][0]["expression"]["terms"][0]["coefficient"] = 1e-12
        cases[2]["objective"]["expression"]["terms"][0]["coefficient"] = 1e-12
        for ir in cases:
            with self.subTest(ir=ir):
                with self.assertRaises(RunError) as error:
                    solve_highs(compile_ir(ir), {})
                self.assertEqual(error.exception.code, "unsupported_numeric_range")


if __name__ == "__main__":
    unittest.main()
