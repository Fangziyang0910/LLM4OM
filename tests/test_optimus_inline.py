"""Explicit input variant, using unchanged pinned main and public resources."""

import asyncio
import hashlib
import json
import unittest
from llm4om.methods import MethodContext
from llm4om.optimus import OptimusFactory, OptimusInlineFactory, INLINE_VARIANT
from test_optimus_method import Tape, REPLIES


class OptimusInlineTests(unittest.TestCase):
    def test_no_external_declarations_keeps_source_main_and_public_data(self):
        tape = Tape([reply.replace('Capacity', '4') for reply in REPLIES])
        raw = b'{"Capacity":4}'
        problem = {"problem_id":"inline-public", "revision":"1", "description":"Maximize 3x for nonnegative integer x <= 4.",
            "data_refs":[{"data_id":"parameters", "sha256":hashlib.sha256(raw).hexdigest()}]}
        context = MethodContext(tape, {"parameters":raw}, {"max_repairs":3,"wall_time_s":20}, "a"*64, resources=tape)
        outcome = asyncio.run(OptimusInlineFactory().create({"rag_mode":None}).run(problem,context))
        self.assertEqual(outcome.status,'candidate_selected')
        self.assertEqual(len(tape.requests),9)
        state = json.loads(tape.files['state_1_params.json'])
        self.assertEqual(state['parameters'],{})
        self.assertIn('Capacity',state['description'])
        self.assertEqual(json.loads(tape.executions[0].data_json),{})
        self.assertEqual(json.loads(tape.files['fidelity-report.json'])['status'],'match')
        self.assertEqual(outcome.proposal.artifact['provenance']['variant_id'],INLINE_VARIANT)
        self.assertEqual(json.loads(tape.files['public-input-projection.json'])['data_sha256']['parameters'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(OptimusFactory().describe()['config_schema']['required'],['rag_mode'])

    def test_primary_optimus_entry_accepts_natural_language_without_parameter_files(self):
        tape = Tape([reply.replace('Capacity', '4') for reply in REPLIES])
        problem = {"problem_id":"natural", "revision":"1", "description":"Maximize 3x for nonnegative integer x <= 4.", "data_refs":[]}
        context = MethodContext(tape, {}, {"max_repairs":3,"wall_time_s":20}, "a"*64, resources=tape)
        outcome = asyncio.run(OptimusFactory().create({"rag_mode":None}).run(problem,context))
        self.assertEqual(outcome.status, 'candidate_selected')
        self.assertEqual(json.loads(tape.files['state_1_params.json'])['parameters'], {})
