"""Prompt workflows retain modeling steps and compose the selected code target."""

import asyncio
import json
import unittest

from llm4om.backends import GurobiBackendFactory
from llm4om.contracts import RunError
from llm4om.methods import MethodContext
from test_coe_method import Tape, target

CODE = "def build_model(data): pass"


class PromptMethodTests(unittest.TestCase):
    def run_method(self, factory, tape, config=None, code_target=None):
        problem = {"problem_id": "natural", "revision": "1", "description": "Maximize 3x for nonnegative x <= 4.", "data_refs": []}
        context = MethodContext(tape, {}, {"max_repairs": 2, "wall_time_s": 60}, "a"*64,
            resources=tape, code_target=code_target or target())
        return asyncio.run(factory.create(config or {}).run(problem, context))

    def test_math_code_and_debugging_keep_the_selected_target(self):
        from llm4om.or_llm_agent import ORLLMAgentFactory
        for solver in ("highs", "gurobi", "ortools"):
            with self.subTest(solver=solver):
                tape = Tape(["max 3x, 0 <= x <= 4", "raise ValueError('public failure')", CODE], exits=(1, 0))
                outcome = self.run_method(ORLLMAgentFactory(), tape, code_target=target(solver))
                self.assertEqual(outcome.final_candidate_id, "002")
                self.assertEqual([request["role"] for request in tape.requests],
                    ["or_llm_agent.math_model", "or_llm_agent.code", "or_llm_agent.debug"])
                self.assertIn("public invocation failed", tape.requests[-1]["messages"][-1]["content"])
                for request in tape.requests[1:]:
                    self.assertIn("llm4om.solvers." + solver, request["messages"][0]["content"])
                self.assertEqual(tape.assessments[0][1].formulation["representation"], tape.assessments[1][1].formulation["representation"])

    def test_backend_contract_changes_code_prompt_without_changing_the_method(self):
        from llm4om.or_llm_agent import ORLLMAgentFactory
        native = {**GurobiBackendFactory().describe()["capabilities"]["code_generation"],
            "model_backend": "llm4om.model_backends.gurobipy", "solver": "llm4om.solvers.gurobi", "solver_name": "Gurobi"}
        tape = Tape(["max 3x, 0 <= x <= 4", CODE])
        self.run_method(ORLLMAgentFactory(), tape, code_target=native)
        self.assertIn("Build a native gurobipy model", tape.requests[1]["messages"][0]["content"])
        self.assertEqual(tape.assessments[0][1].code.representation_kind, "native_code")

    def test_optitree_uses_modeling_thoughts_with_a_configured_code_target(self):
        from llm4om.optitree import OptiTreeFactory
        tape = Tape(['{"matching_problem_type":"not found","belongs_to_problem_types":false}',
            json.dumps({"formulation": "max 3x, 0 <= x <= 4", "code": CODE})])
        self.run_method(OptiTreeFactory(), tape, code_target=target("ortools"))
        self.assertIn("reason_flow", tape.requests[1]["messages"][-1]["content"])
        self.assertNotIn("example_application", tape.requests[1]["messages"][-1]["content"])
        self.assertIn("llm4om.solvers.ortools", tape.requests[1]["messages"][0]["content"])

    def test_optitree_rejects_an_invented_type(self):
        from llm4om.optitree import OptiTreeFactory
        tape = Tape(['{"matching_problem_type":"invented","belongs_to_problem_types":true}'])
        with self.assertRaises(RunError) as caught:
            self.run_method(OptiTreeFactory(), tape)
        self.assertEqual(caught.exception.code, "invalid_tree_route")
        self.assertEqual(tape.assessments, [])

    def test_valid_infeasible_solver_result_does_not_trigger_code_repair(self):
        from llm4om.or_llm_agent import ORLLMAgentFactory
        class InfeasibleTape(Tape):
            async def assess(self, candidate_id, proposal, **kwargs):
                result = await super().assess(candidate_id, proposal, **kwargs)
                return {**result, "has_primal_solution": False, "termination": "infeasible"}
        tape = InfeasibleTape(["x <= -1 and x >= 0", CODE])
        result = self.run_method(ORLLMAgentFactory(), tape)
        self.assertEqual(result.final_candidate_id, "001")
        self.assertEqual(len(tape.requests), 2)
