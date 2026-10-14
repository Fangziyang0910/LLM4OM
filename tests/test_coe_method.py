"""Expert routing and reflection through the public candidate resource interface."""

import asyncio
import hashlib
import json
import unittest

from llm4om.backends import PyomoBackendFactory
from llm4om.contracts import RunError
from llm4om.methods import LLMResponse, MethodContext, MethodOutcome


class Tape:
    def __init__(self, replies, exits=(0,), collector_error=None):
        self.replies, self.exits = list(replies), list(exits)
        self.requests, self.executions, self.events, self.assessments = [], [], [], []
        self.files = {}
        self.collector_error = collector_error
        self.selection = None

    async def complete(self, request):
        self.requests.append(request)
        text = self.replies.pop(0)
        return LLMResponse(text, str(len(self.requests)), "mock_fixture", hashlib.sha256(text.encode()).hexdigest())

    async def assess(self, candidate_id, proposal, **kwargs):
        self.assessments.append((candidate_id, proposal, kwargs))
        failed = bool(self.exits.pop(0) if self.exits else 0) or self.collector_error is not None
        return {"candidate_id": candidate_id, "has_primal_solution": not failed,
            "termination": None if failed else "optimal", "solve_result_ref": None if failed else {"id": candidate_id},
            "diagnostics": [{"code": "worker_failed", "stage": "execution", "message": "public invocation failed"}] if failed else []}

    def select(self, candidate_id, **kwargs):
        self.selection = {"candidate_id": candidate_id, **kwargs}
        return MethodOutcome("candidate_selected", candidate_id, None)

    def remaining_budget(self):
        return {"candidates": 4-len(self.assessments), "solver_calls": 4-len(self.assessments)}

    def record(self, name, value):
        self.files[name] = value
        return {"sha256": hashlib.sha256(value).hexdigest()}

    def emit(self, event):
        self.events.append(event)


def target(solver="highs"):
    return {**PyomoBackendFactory().describe()["capabilities"]["code_generation"],
        "model_backend": "llm4om.model_backends.pyomo_factory", "solver": "llm4om.solvers." + solver, "solver_name": solver}


def reduced(code="def build_model(data): pass", formulation="max 3x; 0 <= x <= 4, x integer"):
    return json.dumps({"formulation": formulation, "code": code})


class CoEMethodTests(unittest.TestCase):
    def run_tape(self, tape, *, reflection=False, collaboration=2, trials=2, repairs=3):
        from llm4om.coe import CoEFactory
        problem = {"problem_id": "public", "revision": "1", "description": "Maximize 3x for nonnegative integer x <= 4.", "data_refs": []}
        context = MethodContext(tape, {}, {"max_repairs": repairs, "wall_time_s": 30}, "a"*64,
            resources=tape, code_target=target())
        return asyncio.run(CoEFactory().create({"max_collaborate_nums": collaboration,
            "enable_reflection": reflection, "max_trials": trials, "seed": 7}).run(problem, context))

    def test_dynamic_routing_combines_comments_into_a_supplied_formulation_and_target_code(self):
        tape = Tape(["Programming Expert", "first-comment", "Modeling Expert", "second-comment", reduced()])
        result = self.run_tape(tape)
        self.assertEqual(result.final_candidate_id, "001")
        self.assertEqual([call["role"] for call in tape.requests], ["coe.conductor", "coe.Programming Expert",
            "coe.conductor", "coe.Modeling Expert", "coe.reducer"])
        self.assertIn("first-comment", tape.requests[3]["messages"][-1]["content"])
        self.assertIn("llm4om.solvers.highs", tape.requests[-1]["messages"][0]["content"])
        proposal = tape.assessments[0][1]
        self.assertEqual(proposal.formulation["representation"]["state"]["mathematical_model"], "max 3x; 0 <= x <= 4, x integer")
        self.assertEqual(proposal.code.representation_kind, "python_factory")

    def test_backward_reflection_reaches_the_next_trial_and_selection_reuses_its_assessment(self):
        tape = Tape(["Programming Expert", "first-comment", reduced(),
            '{"is_caused_by_you":true,"reason":"runtime error","refined_result":"use corrected model construction"}',
            "Programming Expert", "second-comment", reduced()], exits=(1, 0))
        result = self.run_tape(tape, reflection=True, collaboration=1)
        self.assertEqual(result.final_candidate_id, "002")
        self.assertIn("public invocation failed", tape.requests[3]["messages"][-1]["content"])
        self.assertIn("use corrected model construction", tape.requests[5]["messages"][-1]["content"])
        self.assertEqual(tape.assessments[1][2]["parent_id"], "001")
        self.assertEqual(len(tape.assessments), 2)

    def test_failure_feedback_is_not_ignored_or_selected_as_success(self):
        tape = Tape(["Programming Expert", "comment", reduced()], collector_error="invalid_model")
        with self.assertRaises(RunError) as caught:
            self.run_tape(tape, reflection=True, collaboration=1, trials=1)
        self.assertEqual(caught.exception.code, "method_debug_exhausted")
        self.assertIsNone(tape.selection)

    def test_backward_walk_propagates_unparseable_expert_feedback(self):
        tape = Tape(["Parameter Extractor", "first", "Programming Expert", "second", reduced(),
            "unparseable public response", '{"is_caused_by_you":true,"reason":"parameters","refined_result":"corrected parameters"}',
            "Parameter Extractor", "fixed", "Programming Expert", "fixed code", reduced()], exits=(1, 0))
        self.run_tape(tape, reflection=True)
        self.assertEqual([call["role"] for call in tape.requests[5:7]], ["coe.Programming Expert.backward", "coe.Parameter Extractor.backward"])
        self.assertIn("unparseable public response", tape.requests[6]["messages"][-1]["content"])

    def test_invalid_routing_has_a_deterministic_fallback(self):
        tape = Tape(["invalid-expert", "comment", reduced()])
        self.run_tape(tape, collaboration=1)
        self.assertEqual(json.loads(tape.files["routes.json"])["routes"][0]["expert"], "Modeling Expert")

    def test_code_reviewer_keeps_review_instructions_with_the_selected_target(self):
        tape = Tape(["Code Reviewer", "All public requirements are represented.", reduced()])
        self.run_tape(tape, collaboration=1)
        instruction = tape.requests[1]["messages"][0]["content"]
        self.assertIn("Review the previous model and code", instruction)
        self.assertIn("llm4om.solvers.highs", instruction)
        self.assertNotIn("Return only the Python source", instruction)
