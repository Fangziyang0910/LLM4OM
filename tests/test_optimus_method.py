"""OptiMUS keeps clause modeling and exposes public state without source replay."""

import asyncio
import hashlib
import json
import time
import unittest

from llm4om.contracts import RunError
from llm4om.methods import MethodContext
from llm4om.optimus import OptimusFactory
from test_coe_method import Tape, target

REPLIES = ['{"Capacity":{"value":4,"shape":[],"definition":"capacity"}}', "maximize profit 3x",
    '{"constraints":["production is nonnegative integer and bounded by capacity"]}',
    '{"formulation":"0 <= x <= Capacity","new_variables":{"x":{"domain":"integer","shape":[],"definition":"production"}},"auxiliary_constraints":[]}',
    "max 3x", "def build_model(data): pass"]


class OptimusMethodTests(unittest.TestCase):
    def run_tape(self, tape, *, deadline=None, data=None, config=None, repairs=2):
        data = data or {}
        problem = {"problem_id":"public", "revision":"1", "description":"Maximize 3x with integer 0 <= x <= 4.",
            "data_refs":[{"data_id":key,"sha256":hashlib.sha256(value).hexdigest()} for key,value in data.items()]}
        context = MethodContext(tape, data, {"max_repairs":repairs,"wall_time_s":20}, "a"*64,
            resources=tape, deadline=deadline, code_target=target("ortools"))
        return asyncio.run(OptimusFactory().create({"rag_mode":None, **(config or {})}).run(problem,context))

    def test_natural_input_retains_parameter_objective_clause_and_code_stages(self):
        tape = Tape(REPLIES)
        result = self.run_tape(tape)
        self.assertEqual(result.final_candidate_id,"001")
        self.assertEqual([call["role"] for call in tape.requests], ["optimus.parameters", "optimus.objective",
            "optimus.constraints", "optimus.constraint_model", "optimus.objective_model", "optimus.code"])
        self.assertEqual(len([name for name in tape.files if name.startswith("state_")]),6)
        state = tape.assessments[0][1].formulation["representation"]["state"]
        self.assertEqual(state["constraints"][0]["formulation"],"0 <= x <= Capacity")
        self.assertIn("llm4om.solvers.ortools",tape.requests[-1]["messages"][0]["content"])

    def test_each_clause_reuses_variables_and_auxiliary_constraints_reach_code_generation(self):
        replies = list(REPLIES)
        replies[2] = '{"constraints":["capacity","minimum production"]}'
        replies.insert(4, '{"formulation":"x >= 1","new_variables":{},"auxiliary_constraints":["x <= 4"]}')
        tape = Tape(replies)
        self.run_tape(tape)
        self.assertIn('"x"',tape.requests[4]["messages"][-1]["content"])
        self.assertIn("x <= 4",tape.requests[-1]["messages"][-1]["content"])

    def test_failed_code_is_repaired_without_repeating_formulation(self):
        tape = Tape(REPLIES+["def build_model(data): pass # corrected"],exits=(1,0))
        result = self.run_tape(tape)
        self.assertEqual(result.final_candidate_id,"002")
        self.assertEqual(len(tape.requests),7)
        self.assertEqual(tape.assessments[0][1].formulation["representation"],tape.assessments[1][1].formulation["representation"])

    def test_expired_deadline_makes_no_model_calls(self):
        tape = Tape(REPLIES)
        with self.assertRaises(RunError) as caught:
            self.run_tape(tape,deadline=time.time()-1)
        self.assertEqual(caught.exception.code,"deadline_exhausted")
        self.assertEqual(tape.requests,[])

    def test_explicit_declarations_require_values_and_rag_is_not_silently_ignored(self):
        for config,data,code in [({"params_data_id":"params","labels_data_id":"labels"},
                {"params":b'{"Capacity":{"shape":[],"definition":"capacity"}}',"labels":b'{}'},"invalid_method_input"),
                ({"rag_mode":"problem_labels"},{},"rag_resources_unavailable")]:
            tape = Tape(REPLIES)
            with self.assertRaises(RunError) as caught:
                self.run_tape(tape,config=config,data=data)
            self.assertEqual(caught.exception.code,code)
            self.assertEqual(tape.requests,[])

    def test_debug_limit_stops_before_an_extra_call(self):
        tape = Tape(REPLIES,exits=(1,))
        with self.assertRaises(RunError) as caught:
            self.run_tape(tape,repairs=0)
        self.assertEqual(caught.exception.code,"method_debug_exhausted")
        self.assertEqual(len(tape.requests),6)
