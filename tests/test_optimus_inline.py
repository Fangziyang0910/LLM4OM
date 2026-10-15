"""The existing inline plugin ID remains an alias for natural-language input."""

import asyncio
import hashlib
import unittest
from llm4om.methods import MethodContext
from llm4om.optimus import OptimusInlineFactory
from test_coe_method import Tape, target
from test_optimus_method import REPLIES


class OptimusInlineTests(unittest.TestCase):
    def test_public_uploaded_data_needs_no_special_parameter_files(self):
        tape = Tape(REPLIES)
        raw = b'{"Capacity":4}'
        problem = {"problem_id":"natural","revision":"1","description":"Maximize 3x, integer 0 <= x <= Capacity.",
            "data_refs":[{"data_id":"business_data","sha256":hashlib.sha256(raw).hexdigest()}]}
        context = MethodContext(tape,{"business_data":raw},{"max_repairs":2,"wall_time_s":20},"a"*64,
            resources=tape,code_target=target())
        result = asyncio.run(OptimusInlineFactory().create({"rag_mode":None}).run(problem,context))
        self.assertEqual(result.status,"selected")
        self.assertIn("Capacity",tape.requests[0]["messages"][-1]["content"])
        self.assertEqual(tape.assessments[0][1].code.data_bindings,problem["data_refs"])
