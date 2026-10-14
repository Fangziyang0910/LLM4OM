"""Prompt methods operate on natural descriptions and mediated public feedback."""

import asyncio
import hashlib
import json
import unittest

from llm4om.methods import MethodContext
from test_coe_method import Tape


CODE = 'import gurobipy as gp\nm=gp.Model()\nx=m.addVar(name="x")\nm.addConstr(x<=4)\nm.setObjective(3*x,gp.GRB.MAXIMIZE)\nm.optimize()\n'


class PromptMethodTests(unittest.TestCase):
    def run_method(self, factory, tape, config=None):
        problem = {"problem_id": "natural", "revision": "1", "description": "Maximize 3x for nonnegative x <= 4.", "data_refs": []}
        context = MethodContext(tape, {}, {"max_repairs": 2, "wall_time_s": 60}, "a" * 64, resources=tape)
        return asyncio.run(factory.create(config or {}).run(problem, context))

    def test_or_llm_agent_separates_math_code_and_feedback_debugging(self):
        from llm4om.or_llm_agent import ORLLMAgentFactory
        tape = Tape(["max 3x, 0 <= x <= 4", "raise ValueError('public failure')", CODE], exits=(1, 0))
        outcome = self.run_method(ORLLMAgentFactory(), tape)
        self.assertEqual([request["role"] for request in tape.requests],
            ["or_llm_agent.math_model", "or_llm_agent.code", "or_llm_agent.debug"])
        self.assertIn("public invocation failed", tape.requests[-1]["messages"][-1]["content"])
        self.assertEqual(outcome.proposal.formulation["representation"]["state"]["mathematical_model"], "max 3x, 0 <= x <= 4")
        self.assertEqual(len(tape.executions), 2)

    def test_optitree_retrieves_hierarchical_thoughts_before_generation(self):
        from llm4om.optitree import OptiTreeFactory
        tape = Tape([json.dumps({"matching_problem_type": "not found", "belongs_to_problem_types": False}),
            json.dumps({"formulation": "max 3x, 0 <= x <= 4", "code": CODE})])
        outcome = self.run_method(OptiTreeFactory(), tape)
        self.assertEqual(tape.requests[0]["role"], "optitree.classify")
        self.assertEqual(tape.requests[1]["role"], "optitree.reasoner")
        self.assertIn("reason_flow", tape.requests[1]["messages"][-1]["content"])
        self.assertNotIn("example_application", tape.requests[1]["messages"][-1]["content"])
        self.assertEqual(len(tape.executions), 1)
        self.assertEqual(outcome.proposal.formulation["representation"]["state"]["mathematical_model"], "max 3x, 0 <= x <= 4")

    def test_optitree_rejects_invented_type_instead_of_silently_using_another_method(self):
        from llm4om.contracts import RunError
        from llm4om.optitree import OptiTreeFactory
        tape = Tape(['{"matching_problem_type":"invented","belongs_to_problem_types":true}'])
        with self.assertRaises(RunError) as caught:
            self.run_method(OptiTreeFactory(), tape)
        self.assertEqual(caught.exception.code, "invalid_tree_route")
        self.assertEqual(tape.executions, [])
