"""AutoFormulation search uses self-evaluation, symbolic pruning and public solving."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest

from llm4om.methods import MethodContext, MethodOutcome
from test_coe_method import Tape
from test_linear_solver import model, row


class SearchTape(Tape):
    def __init__(self, replies, invalid_first=False):
        super().__init__(replies)
        self.assessments = []
        self.invalid_first = invalid_first

    def remaining_budget(self):
        return {"candidates": 4 - len(self.assessments), "solver_calls": 4, "llm_attempts": len(self.replies),
            "total_tokens": 100000, "wall_time_s": 100}

    async def assess(self, candidate_id, proposal, **kwargs):
        self.assessments.append(proposal)
        if self.invalid_first and candidate_id == "001":
            return {"candidate_id": candidate_id, "has_primal_solution": False, "termination": None,
                "solve_result_ref": None, "diagnostics": [{"code": "invalid_ir", "stage": "compile"}]}
        return {"candidate_id": candidate_id, "has_primal_solution": True, "termination": "optimal",
            "solve_result_ref": {"id": candidate_id}, "diagnostics": []}

    def select(self, candidate_id, **kwargs):
        self.selection = {"candidate_id": candidate_id, **kwargs}
        return MethodOutcome("candidate_selected", candidate_id, None)


class AutoFormulationTests(unittest.TestCase):
    def compact(self):
        root = Path(__file__).resolve().parents[1] / "examples/specs"
        formulation = json.loads((root / "formulation.json").read_text())
        ir = json.loads((root / "model-ir.json").read_text())
        return {"representation": formulation["representation"], "structured_ir": {
            key: ir[key] for key in ("problem_type", "variables", "objective", "constraints", "assumptions")}}

    def test_mcts_explores_distinct_branches_and_selects_by_semantic_reward(self):
        self.check_two_branches()

    def test_invalid_leaf_receives_zero_reward_and_search_continues(self):
        self.check_two_branches(invalid_first=True)

    def check_two_branches(self, invalid_first=False):
        from llm4om.autoformulation import AutoFormulationFactory
        replies = []
        for stage in range(5):
            replies.extend([json.dumps({"hypotheses": [f"stage-{stage}-A", f"stage-{stage}-B"]}), '{"scores":[0.8,0.7]}'])
        first = self.compact()
        if invalid_first:
            first["structured_ir"]["objective"]["expression"]["terms"][0]["variable_id"] = "missing"
        replies.extend([json.dumps(first), '{"score":0.4,"reason":"first formulation has an unjustified assumption"}'])
        # UCT explores the unvisited second branch at the first stage.
        for stage in range(1, 5):
            replies.extend([json.dumps({"hypotheses": [f"second-stage-{stage}"]}), '{"scores":[0.9]}'])
        changed = self.compact()
        changed["structured_ir"]["constraints"][0]["rhs"] += 1
        replies.extend([json.dumps(changed), '{"score":0.9,"reason":"all stated requirements are covered"}'])
        tape = SearchTape(replies, invalid_first=invalid_first)
        problem = {"problem_id": "natural", "revision": "1", "description": "Public production planning problem.", "data_refs": []}
        context = MethodContext(tape, {}, {"max_repairs": 0, "wall_time_s": 100}, "a" * 64, resources=tape)
        result = asyncio.run(AutoFormulationFactory().create({"rollouts": 2, "branching": 2}).run(problem, context))
        self.assertEqual(result.final_candidate_id, "002")
        self.assertEqual(len(tape.assessments), 2)
        tree = json.loads(tape.files["search-tree.json"])
        self.assertEqual(tree["nodes"][0]["visits"], 2)
        self.assertEqual(len(tree["nodes"][0]["children"]), 2)
        self.assertNotIn("objective_value", json.dumps(tape.selection))

    def test_smt_prunes_scaled_equivalent_constraints_but_keeps_changed_models(self):
        from llm4om.autoformulation import equivalent_models
        original = model(upper=4)
        original["constraints"] = [row("le", 3)]
        same = deepcopy(original)
        same["constraints"][0]["expression"]["terms"][0]["coefficient"] = 2
        same["constraints"][0]["rhs"] = 6
        self.assertTrue(equivalent_models(original, same))
        same["constraints"][0]["rhs"] = 4
        self.assertFalse(equivalent_models(original, same))
        same = deepcopy(original)
        same["objective"]["expression"]["constant"] = 1
        self.assertFalse(equivalent_models(original, same))
