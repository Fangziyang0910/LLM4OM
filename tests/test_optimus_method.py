"""Fixed-source orchestration through the public MethodContext seams."""

import asyncio
import hashlib
import json
import unittest
import time

from llm4om.methods import LLMResponse, MethodContext
from llm4om.contracts import RunError
from llm4om.optimus import OptimusFactory
from llm4om.optimus_runtime import SourceRuntime


REPLIES = [
    "=====\nOBJECTIVE: maximize profit\n=====",
    '["production is bounded by capacity"]',
    '["production is bounded by capacity"]',
    "5 OUT OF 5",
    '{"FORMULATION":"$x <= Capacity$","NEW VARIABLES":{"x":{"shape":[],"type":"integer","definition":"production"}},"AUXILIARY CONSTRAINTS":[]}',
    "1 OUT OF 5",
    "=====\n$max 3x$\n=====",
    "=====\nmodel.addConstr(x <= Capacity)\n=====",
    "=====\nmodel.setObjective(3*x, GRB.MAXIMIZE)\n=====",
]


class Tape:
    def __init__(self, replies=REPLIES, exits=(0,)):
        self.replies = list(replies)
        self.exits = list(exits)
        self.requests = []
        self.files = {}
        self.executions = []
        self.events = []

    async def complete(self, request):
        self.requests.append(request)
        text = self.replies.pop(0)
        return LLMResponse(text, str(len(self.requests)), "mock_fixture", hashlib.sha256(text.encode()).hexdigest())

    async def execute(self, execution_id, code):
        self.executions.append(code)
        return {"execution_id": execution_id, "source": {"status": "completed", "exit_code": self.exits.pop(0),
                "stdout": "source output", "stderr": "source error"}, "collector_error": None}

    def record(self, name, value):
        self.files[name] = value
        return {"sha256": hashlib.sha256(value).hexdigest()}

    def emit(self, event):
        self.events.append(event)


class OptimusMethodTests(unittest.TestCase):
    def run_tape(self, tape, *, budget=None, deadline=None, params_override=None):
        params = {"Capacity": {"value": 4, "shape": [], "definition": "capacity"}}
        if params_override is not None:
            params = params_override
        data = {"params": json.dumps(params).encode(), "labels": b'{"type":[],"domain":[]}'}
        problem = {"problem_id": "public", "revision": "1", "description": "Maximize profit 3x with x integer and x <= Capacity.",
                   "data_refs": [{"data_id": key, "sha256": hashlib.sha256(value).hexdigest()} for key, value in data.items()]}
        context = MethodContext(tape, data, budget or {"max_repairs": 3, "wall_time_s": 20}, "a" * 64,
                                resources=tape, deadline=deadline)
        return asyncio.run(OptimusFactory().create({"rag_mode": None, "params_data_id": "params",
                            "labels_data_id": "labels"}).run(problem, context))

    def test_fixed_default_retains_six_states_and_original_script(self):
        tape = Tape()
        outcome = self.run_tape(tape)
        self.assertEqual(outcome.status, "candidate_selected")
        self.assertEqual(len(tape.requests), 9)
        self.assertTrue(all([message["role"] for message in call["messages"]] == ["user"] for call in tape.requests))
        states = [json.loads(value) for name, value in tape.files.items() if name.startswith("state_")]
        self.assertEqual(len(states), 6)
        self.assertEqual(states[0]["parameters"], {"Capacity": {"shape": [], "definition": "capacity"}})
        self.assertEqual(states[3]["constraints"][0]["formulation"], "$x <= Capacity$")
        self.assertEqual(json.loads(tape.executions[0].data_json), {"Capacity": 4})
        self.assertIn('model = Model("OptimizationProblem")', outcome.proposal.code.source)
        self.assertEqual(outcome.proposal.code.source, tape.files["code.py"].decode())
        self.assertEqual(outcome.proposal.formulation["representation_kind"], "native_formulation")
        fidelity = json.loads(tape.files["fidelity-report.json"])
        self.assertEqual(fidelity["status"], "match")
        self.assertEqual(fidelity["reference_entry"], "fixed main.py __main__")

    def reference(self, replies, exits):
        pending = list(replies)
        statuses = list(exits)
        requests, files, executions = [], {}, []
        def complete(messages, model, role):
            requests.append({"messages": messages, "model": model, "role": role})
            return pending.pop(0)
        def execute(filename, source):
            executions.append(source)
            return {"source": {"status": "completed", "exit_code": statuses.pop(0),
                               "stdout": "source output", "stderr": "source error"}}
        runtime = SourceRuntime({
            "params.json": json.dumps({"Capacity": {"value": 4, "shape": [], "definition": "capacity"}}).encode(),
            "labels.json": b'{"type":[],"domain":[]}',
            "desc.txt": b"Maximize profit 3x with x integer and x <= Capacity."},
            complete, execute, lambda name, value: files.update({name: value}))
        error = None
        try:
            runtime.load("main", reference_main=True)
        except Exception as failure:
            error = type(failure)
        return requests, files, executions, runtime.selected, runtime.last_executed, error

    def assert_reference(self, replies, exits):
        reference = self.reference(replies, exits)
        tape = Tape(replies, exits)
        error = None
        outcome = None
        try:
            outcome = self.run_tape(tape)
        except Exception as failure:
            error = failure.details["source_exception"] if isinstance(failure, RunError) else type(failure).__name__
        self.assertEqual(error, reference[5].__name__ if reference[5] else None)
        self.assertEqual([{k: v for k, v in item.items() if k != "request_id"} for item in tape.requests],
                         [{k: v for k, v in item.items() if k != "model"} for item in reference[0]])
        for name, value in reference[1].items():
            self.assertEqual(tape.files[name], value, name)
        self.assertEqual([code.source.encode() for code in tape.executions], reference[2])
        if outcome is not None:
            selection = json.loads(tape.files["source-selection.json"])
            self.assertEqual(selection["source_selected"], reference[3])
            self.assertEqual(selection["last_executed"], reference[4])
        return tape, outcome

    def test_independent_fixed_main_matches_all_repair_selections(self):
        for failures in range(4):
            with self.subTest(failures=failures):
                replies = REPLIES + [f"=====\n# repair {index}\n=====" for index in range(failures)]
                exits = [1] * failures + ([0] if failures < 3 else [])
                tape, outcome = self.assert_reference(replies, exits)
                expected = "code.py" if failures == 0 else f"code_{min(failures, 2)}.py"
                self.assertEqual(outcome.proposal.code.source.encode(), tape.files[expected])
                if failures == 3:
                    self.assertIn("code_3.py", tape.files)
                    self.assertNotEqual(outcome.proposal.code.source.encode(), tape.files["code_3.py"])

    def test_source_low_confidence_keep_remove_modify_and_missing_score(self):
        for action in ("yes", "no", "modify", "missing"):
            with self.subTest(action=action):
                if action == "missing":
                    replies = REPLIES[:3] + ["no confidence score"] * 5 + REPLIES[4:]
                else:
                    replies = REPLIES[:3] + ["2 OUT OF 5", json.dumps({"action": action, "updatedConstraint": "modified constraint"})]
                    replies += REPLIES[6:7] + REPLIES[8:] if action == "no" else REPLIES[4:]
                self.assert_reference(replies, (0,))

    def test_auxiliaries_and_nonmutating_reflection_match_reference(self):
        modeled = json.loads(REPLIES[4])
        modeled["NEW VARIABLES"]["x"]["shape"] = "[]"
        modeled["AUXILIARY CONSTRAINTS"] = ["$x >= 0$"]
        replies = REPLIES[:4] + ["```json\n" + json.dumps(modeled, indent=4) + "\n```", "1 OUT OF 5", "remove all constraints"] + REPLIES[6:8] + ["=====\nmodel.addConstr(x >= 0)\n====="] + REPLIES[8:]
        tape, outcome = self.assert_reference(replies, (0,))
        self.assertEqual(len(outcome.proposal.formulation["representation"]["state"]["constraints"]), 2)

    def test_redundancy_parser_retry_and_variable_collision_match_reference(self):
        self.assert_reference(REPLIES[:2] + ["not a list"] + REPLIES[2:], (0,))
        replies = REPLIES[:2] + ['["first", "second"]', "5 OUT OF 5", "5 OUT OF 5", REPLIES[4], REPLIES[4]]
        tape, outcome = self.assert_reference(replies, ())
        self.assertIsNone(outcome)
        self.assertEqual(tape.executions, [])

    def test_shared_repair_budget_stops_before_another_model_call(self):
        tape = Tape(REPLIES, (1,))
        with self.assertRaises(RunError) as caught:
            self.run_tape(tape, budget={"max_repairs": 0, "wall_time_s": 20})
        self.assertEqual(caught.exception.code, "budget_exhausted")
        self.assertEqual(len(tape.requests), 9)
        self.assertEqual(len(tape.executions), 1)

    def test_expired_deadline_does_not_start_model_or_script_requests(self):
        tape = Tape()
        with self.assertRaises(RunError) as caught:
            self.run_tape(tape, deadline=time.time() - 1)
        self.assertEqual(caught.exception.code, "deadline_exhausted")
        self.assertEqual(tape.requests, [])
        self.assertEqual(tape.executions, [])

    def test_missing_parameter_value_is_not_inferred(self):
        tape = Tape()
        with self.assertRaises(RunError) as caught:
            self.run_tape(tape, params_override={"Capacity": {"shape": [], "definition": "capacity"}})
        self.assertEqual(caught.exception.code, "invalid_method_input")
        self.assertEqual(tape.requests, [])

    def test_malformed_delimiters_and_redundancy_exhaustion_follow_fixed_source(self):
        self.assert_reference(["no objective delimiters"] + REPLIES[1:], (0,))
        self.assert_reference(REPLIES[:2] + ["no list"] * 5, ())
