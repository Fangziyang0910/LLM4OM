"""MAMO public SDK/CLI import and post-run numeric evaluation."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import yaml

from llm4om import MAMOAdapter, evaluate_case, import_dataset, run_problem
from llm4om.contracts import RunError


class MAMOTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.records = {
            "easy_lp": [{"id": 1, "Question": "Choose nonnegative integer x <= 4. Maximize 3x.",
                         "Answer": "12", "Category": "optimization", "Type": "easy_lp"}],
            "complex_lp": [{"id": 1, "Question": "An unresolved domain question with inline $x$.",
                            "Answer": "312987", "Category": "optimization", "Type": "complex_lp"}],
            "ode": [{"id": 1, "Question": "Solve the differential equation.", "Answer": "0",
                     "Category": "ordinary_differential_equation", "Type": "first_order_equation"}],
        }
        self.config = {"schema_version": "0.2.0", "adapter_id": "llm4om.tasks.mamo",
                       "dataset_id": "fixture-mamo", "source_kind": "fixture", "source_version": "test-v1",
                       "files": [], "license_file": None, "reviews": [], "selected": None,
                       "tolerance": {"abs_tol": 1e-6, "rel_tol": 1e-5}}
        self.write_source()

    def write_source(self):
        self.config["files"] = []
        for subset, records in self.records.items():
            raw = b"".join((json.dumps(record) + "\n").encode() for record in records)
            (self.root / (subset + ".jsonl")).write_bytes(raw)
            self.config["files"].append({"subset": subset, "path": subset + ".jsonl",
                                          "sha256": hashlib.sha256(raw).hexdigest()})
        (self.root / "import.json").write_text(json.dumps(self.config))

    def test_import_preserves_question_subset_ids_and_keeps_answers_private(self):
        path = import_dataset(self.root / "import.json", self.root / "snapshot")
        manifest = json.loads(path.read_text())
        self.assertEqual(manifest["adapter_id"], "llm4om.tasks.mamo")
        self.assertEqual(manifest["N_selected"], 2)
        self.assertEqual(manifest["N_eligible"], 0)
        self.assertEqual(manifest["source_exclusions"][0]["records"], 1)
        self.assertEqual(len({case["case_id"] for case in manifest["cases"]}), 2)
        for entry in manifest["cases"]:
            problem = json.loads((path.parent / entry["public_ref"]["relative_path"]).read_text())
            self.assertEqual(problem["description"], self.records[entry["subset"]][0]["Question"])
            self.assertEqual(problem["problem_type_hint"], "unknown")
            self.assertNotIn("Answer", json.dumps(problem))
            self.assertNotIn("312987", json.dumps(problem))
            self.assertEqual(entry["exclusion_reason"], "public_math_review_required")
        oracle = json.loads((path.parent / manifest["cases"][1]["oracle_ref"]["relative_path"]).read_text())
        self.assertEqual(oracle["record"]["Answer"], "312987")
        self.assertEqual((path.parent / "private").stat().st_mode & 0o777, 0o700)
        cli = subprocess.run([sys.executable, "-m", "llm4om", "import", "--config", str(self.root / "import.json"),
                              "--output", str(self.root / "cli-snapshot")], capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertTrue(Path(json.loads(cli.stdout)["manifest_path"]).is_file())

    def test_public_review_freezes_selected_eligibility_and_rounding(self):
        question = self.records["easy_lp"][0]["Question"]
        self.config["reviews"] = [{"subset": "easy_lp", "sample_id": "1",
            "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "classification": "milp", "domain_policy": "x is a nonnegative integer",
            "rounding_policy": {"kind": "none", "decimal_places": None},
            "evidence": [{"aspect": aspect, "start": 0, "end": len(question), "text": question}
                         for aspect in ("problem_type", "variable_domains", "rounding")],
            "reviewer": "public-fixture-review", "reason": None}]
        self.config["selected"] = ["easy_lp:1"]
        self.write_source()
        path = import_dataset(self.root / "import.json", self.root / "snapshot")
        manifest = json.loads(path.read_text())
        self.assertEqual((manifest["N_imported"], manifest["N_selected"], manifest["N_eligible"]), (2, 1, 1))
        first, second = manifest["cases"]
        self.assertTrue(first["eligible"])
        self.assertIsNone(first["exclusion_reason"])
        self.assertFalse(second["selected"])
        problem = json.loads((path.parent / first["public_ref"]["relative_path"]).read_text())
        self.assertEqual(problem["problem_type_hint"], "milp")
        self.assertEqual(first["review"]["rounding_policy"], {"kind": "none", "decimal_places": None})
        self.assertEqual(manifest["tolerance"], {"abs_tol": 1e-6, "rel_tol": 1e-5})
        self.assertEqual([case.case_id for case in MAMOAdapter().iter_cases(path)], [first["case_id"]])
        first["review"]["domain_policy"] = None
        path.write_text(json.dumps(manifest))
        with self.assertRaises(RunError):
            list(MAMOAdapter().iter_cases(path))

    def test_malformed_or_mutated_sources_are_rejected_before_snapshot_publication(self):
        original = dict(self.records["easy_lp"][0])
        mutations = [{**original, "id": True}, {**original, "Answer": "NaN"},
                     {**original, "Question": " "}, {**original, "Category": "ordinary_differential_equation"},
                     {**original, "unexpected": "value"}]
        for index, record in enumerate(mutations):
            with self.subTest(index=index):
                self.records["easy_lp"] = [record]
                self.write_source()
                output = self.root / f"invalid-{index}"
                with self.assertRaises(RunError):
                    import_dataset(self.root / "import.json", output)
                self.assertFalse(output.exists())
        self.records["easy_lp"] = [original, original]
        self.write_source()
        with self.assertRaises(RunError):
            import_dataset(self.root / "import.json", self.root / "duplicate")
        self.records["easy_lp"] = [original]
        self.write_source()
        source = self.root / "easy_lp.jsonl"
        source.write_bytes(source.read_bytes().replace(b'"id": 1', b'"id": 1, "id": 2'))
        self.config["files"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        (self.root / "import.json").write_text(json.dumps(self.config))
        with self.assertRaises(RunError):
            import_dataset(self.root / "import.json", self.root / "duplicate-keys")
        self.write_source()
        source.write_bytes(source.read_bytes() + b"\n")
        with self.assertRaises(RunError) as caught:
            import_dataset(self.root / "import.json", self.root / "changed")
        self.assertEqual(caught.exception.code, "source_hash_mismatch")

    def test_failed_selected_case_keeps_its_numeric_comparison_denominator(self):
        question = self.records["easy_lp"][0]["Question"]
        self.config["reviews"] = [{"subset": "easy_lp", "sample_id": "1",
            "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "classification": "milp", "domain_policy": "x is a nonnegative integer",
            "rounding_policy": {"kind": "none", "decimal_places": None},
            "evidence": [{"aspect": aspect, "start": 0, "end": len(question), "text": question}
                         for aspect in ("problem_type", "variable_domains", "rounding")],
            "reviewer": "public-fixture-review", "reason": None}]
        self.config["selected"] = ["easy_lp:1"]
        self.write_source()
        path = import_dataset(self.root / "import.json", self.root / "snapshot")
        entry = json.loads(path.read_text())["cases"][0]
        problem = path.parent / entry["public_ref"]["relative_path"]
        run = run_problem(problem, self.root / "missing.yaml", output_root=self.root / "runs")
        evaluation = evaluate_case(path, entry["case_id"], run.bundle_path, self.root / "evaluation.json")
        self.assertEqual(evaluation["run_status"], "failed")
        self.assertEqual(evaluation["objective_match_denominator"], 1)
        self.assertEqual(evaluation["objective_match_rate"], 0)
        self.assertEqual(evaluation["objective_match"]["status"], "not_available")
        self.assertEqual(evaluation["independent_feasibility"]["status"], "not_available")
        self.assertEqual(evaluation["semantic_validation"]["status"], "not_available")
        self.assertIsNone(evaluation["checker_error"])
        self.assertNotIn("oracle_ref", json.dumps(evaluation))
        self.assertNotIn("Answer", json.dumps(evaluation))
        for name in (entry["public_ref"]["relative_path"], entry["oracle_ref"]["relative_path"],
                     "private/easy_lp.jsonl", "evaluation-policy.json"):
            with self.subTest(changed_material=name):
                material = path.parent / name
                original = material.read_bytes()
                material.write_bytes(b"{}\n")
                try:
                    broken = evaluate_case(path, entry["case_id"], run.bundle_path,
                                           self.root / (name.replace("/", "-") + "-error.json"))
                    self.assertIsNotNone(broken["checker_error"])
                    self.assertEqual(broken["objective_match_denominator"], 1)
                    self.assertEqual(broken["objective_match_rate"], 0)
                    self.assertNotIn("oracle_ref", json.dumps(broken))
                finally:
                    material.write_bytes(original)

    def test_actual_solver_numeric_zero_and_public_rounding_boundaries(self):
        cases = [(0, "0", False, "pass"), (0.001, "0", False, "fail"),
                 (0.49, "0", True, "pass"), (0.5, "1", True, "pass"),
                 (-1.5, "-2", True, "pass"), (0.49, "0.4", True, "fail")]
        for index, (constant, answer, rounded, expected) in enumerate(cases):
            with self.subTest(constant=constant, answer=answer):
                question = f"Choose continuous x=0. Maximize x+({constant})."
                if rounded:
                    question += " Report the nearest integer; round exact halves away from zero."
                self.records["easy_lp"][0].update(Question=question, Answer=answer)
                self.config["reviews"] = [{"subset": "easy_lp", "sample_id": "1",
                    "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                    "classification": "lp", "domain_policy": "continuous x fixed at zero",
                    "rounding_policy": {"kind": "decimal_half_away_from_zero" if rounded else "none",
                                        "decimal_places": 0 if rounded else None},
                    "evidence": [{"aspect": aspect, "start": 0, "end": len(question), "text": question}
                                 for aspect in ("problem_type", "variable_domains", "rounding")],
                    "reviewer": "public-fixture-review", "reason": None}]
                self.config["selected"] = ["easy_lp:1"]
                self.write_source()
                manifest = import_dataset(self.root / "import.json", self.root / f"snapshot-{index}")
                entry = json.loads(manifest.read_text())["cases"][0]
                compact = {"representation": {"sets": [], "parameters": [],
                    "variables": [{"id": "x", "index_sets": [], "domain": "continuous", "lower_bound": 0,
                                   "upper_bound": 0, "requirement_ids": []}],
                    "objective": {"sense": "max", "expression_text": f"x+({constant})", "requirement_ids": []},
                    "constraints": []}, "structured_ir": {"problem_type": "lp",
                    "variables": [{"id": "x", "name": "x", "domain": "continuous", "lower_bound": 0,
                                   "upper_bound": 0, "requirement_ids": []}],
                    "objective": {"sense": "max", "expression": {"constant": constant,
                        "terms": [{"variable_id": "x", "coefficient": 1}]}, "requirement_ids": []},
                    "constraints": [], "assumptions": []}}
                requests = []
                class Handler(BaseHTTPRequestHandler):
                    def do_POST(self):
                        requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(json.dumps({"choices": [{"message": {"content": json.dumps(compact)},
                            "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 100,
                            "total_tokens": 200}}).encode())
                    def log_message(self, *args):
                        pass
                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    settings = yaml.safe_load((Path(__file__).parents[1] / "examples/specs/solve.yaml").read_text())
                    settings["budget"]["max_total_tokens"] = 30000
                    settings["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "synthetic-public-model",
                        "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "MAMO_TEST_KEY"}}
                    (self.root / "run.yaml").write_text(yaml.safe_dump(settings))
                    with patch.dict(os.environ, {"MAMO_TEST_KEY": "synthetic"}):
                        run = run_problem(manifest.parent / entry["public_ref"]["relative_path"], self.root / "run.yaml",
                                          output_root=self.root / "runs")
                    self.assertEqual(run.status, "completed")
                    evaluation = evaluate_case(manifest, entry["case_id"], run.bundle_path,
                                               self.root / f"evaluation-{index}.json")
                    self.assertIsNone(evaluation["checker_error"], evaluation)
                    self.assertEqual(evaluation["objective_match"]["status"], expected)
                    self.assertEqual(evaluation["objective_match_denominator"], 1)
                    self.assertEqual(evaluation["semantic_validation"]["status"], "not_available")
                    self.assertNotIn("Answer", json.dumps(requests))
                    self.assertNotIn("312987", json.dumps(requests))
                finally:
                    server.shutdown()
                    server.server_close()
