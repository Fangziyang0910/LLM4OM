"""Public data admission retains bytes and rejects invalid JSON before modeling."""

import json
from pathlib import Path
import unittest

from llm4om.contracts import RunError, validate_problem, validate_data, validate_formulation


class PublicJSONTests(unittest.TestCase):
    def test_native_formulation_preserves_original_state(self):
        problem = {"problem_id": "public", "revision": "1", "data_refs": []}
        native = {"schema_version": "0.3.0", "formulation_id": "native",
                  "problem_id": "public", "problem_revision": "1",
                  "representation_kind": "native_formulation",
                  "representation": {"schema": "source_state/0.1.0", "state": {
                      "parameters": {"Capacity": {"shape": [], "definition": "capacity"}},
                      "constraints": [{"description": {"Description": "modified clause"}}]}},
                  "data_bindings": [], "structured_ir_ref": None,
                  "provenance": {"origin": "source_native"}}
        original = json.dumps(native)
        validate_formulation(native, problem)
        self.assertEqual(json.dumps(native), original)
        native["representation"]["schema"] = ""
        with self.assertRaises(RunError):
            validate_formulation(native, problem)

    def test_json_object_data_are_admitted_without_csv_columns(self):
        problem = json.loads((Path(__file__).parents[1] / "examples/specs/problem.json").read_text())
        problem["schema_version"] = "0.3.0"
        problem["data_refs"] = [{"data_id": "params", "path": "params.json",
                                 "format": "json", "sha256": None,
                                 "schema": {"type": "object"}}]
        validate_problem(problem)
        validate_data(b'{"Capacity":{"value":4,"shape":[],"definition":"capacity"}}', problem["data_refs"][0])
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"oracle":{}}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(RunError):
                validate_data(raw, problem["data_refs"][0])
