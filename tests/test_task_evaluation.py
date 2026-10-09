"""Fixed-source import and evaluation through public SDK and CLI seams."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml
from pathlib import Path

from llm4om import import_dataset, NL4OptAdapter, NL4OptEvaluator, run_problem
from llm4om.contracts import RunError


class TaskEvaluationTests(unittest.TestCase):
    def test_import_freezes_original_public_document_and_private_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = {"document": "Original problem.", "vars": [], "var_mentions": [], "params": [],
                      "var_mention_to_first_var": {}, "first_var_to_mentions": {},
                      "obj_declaration": {}, "const_declarations": [], "spans": [], "tokens": [],
                      "_input_hash": 7, "order_mapping": {}}
            raw = (json.dumps({"7": record}) + "\n").encode()
            (root / "dev.jsonl").write_bytes(raw)
            config = {"schema_version": "0.1.0", "dataset_id": "fixture-nl4opt", "source_kind": "fixture",
                      "source_version": "test-v1", "split": "dev", "path": "dev.jsonl",
                      "sha256": hashlib.sha256(raw).hexdigest()}
            (root / "import.json").write_text(json.dumps(config))
            manifest = import_dataset(root / "import.json", root / "snapshot")
            case = next(NL4OptAdapter().iter_cases(manifest))
            problem = json.loads(case.public_problem.read_text())
            self.assertEqual(problem["description"], "Original problem.")
            self.assertEqual(problem["problem_type_hint"], "unknown")
            self.assertEqual(problem["assumptions"], [])
            self.assertNotIn("obj_declaration", problem)
            self.assertEqual(json.loads(manifest.read_text())["N_eligible"], 0)
            result = subprocess.run([sys.executable, "-m", "llm4om", "import", "--config",
                                     str(root / "import.json"), "--output", str(root / "cli")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            record["vars"] = [42]
            raw = (json.dumps({"7": record}) + "\n").encode()
            (root / "dev.jsonl").write_bytes(raw)
            config["sha256"] = hashlib.sha256(raw).hexdigest()
            (root / "import.json").write_text(json.dumps(config))
            with self.assertRaises(RunError):
                import_dataset(root / "import.json", root / "invalid")
            self.assertTrue(Path(json.loads(result.stdout)["manifest_path"]).is_file())
            record["vars"] = []
            line = (json.dumps({"7": record}) + "\n").encode()
            (root / "dev.jsonl").write_bytes(line + line)
            config["sha256"] = hashlib.sha256(line + line).hexdigest()
            (root / "import.json").write_text(json.dumps(config))
            with self.assertRaises(RunError) as duplicate:
                import_dataset(root / "import.json", root / "duplicate")
            self.assertEqual(duplicate.exception.code, "duplicate_or_invalid_id")
            case.public_problem.write_text("{}")
            with self.assertRaises(RunError) as changed:
                list(NL4OptAdapter().iter_cases(manifest))
            self.assertEqual(changed.exception.code, "snapshot_hash_mismatch")


    def test_import_rejects_duplicate_ids_malformed_bytes_and_false_official_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for raw, changes in [(b'{"1":{}}\n{"1":{}}\n', {}),
                                 (b'{"1": {"document":"x", "document":"y"}}\n', {}),
                                 (b'\xff\n', {}), (b'{}\r\n', {}),
                                 (b'{}\n', {"source_kind": "official", "dataset_id": "nl4opt"}),
                                 (b'{}\n', {"sha256": "0" * 64}),
                                 (b'{"1":{"document":"x"}}\n', {})]:
                (root / "data.jsonl").write_bytes(raw)
                config = {"schema_version": "0.1.0", "dataset_id": "fixture-nl4opt", "source_kind": "fixture",
                          "source_version": "test-v1", "split": "dev", "path": "data.jsonl",
                          "sha256": hashlib.sha256(raw).hexdigest(), **changes}
                (root / "config.json").write_text(json.dumps(config))
                with self.subTest(raw=raw, changes=changes):
                    with self.assertRaises(RunError):
                        import_dataset(root / "config.json", root / "snapshot")
                    self.assertFalse((root / "snapshot").exists())

    def test_failed_actual_run_is_retained_without_independent_pass_or_private_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = (json.dumps({"7": {"document": "Choose A and B.", "vars": [], "var_mentions": [], "params": [],
                "var_mention_to_first_var": {}, "first_var_to_mentions": {}, "obj_declaration": {},
                "const_declarations": [], "spans": [], "tokens": [], "_input_hash": 7, "order_mapping": {}}}) + "\n").encode()
            (root / "dev.jsonl").write_bytes(raw)
            config = {"schema_version": "0.1.0", "dataset_id": "fixture-nl4opt", "source_kind": "fixture",
                      "source_version": "test-v1", "split": "dev",
                      "path": "dev.jsonl", "sha256": hashlib.sha256(raw).hexdigest()}
            (root / "config.json").write_text(json.dumps(config))
            manifest = import_dataset(root / "config.json", root / "snapshot")
            case = next(NL4OptAdapter().iter_cases(manifest))
            self.assertEqual(case.case_id, "fixture-nl4opt:test-v1:dev:7")
            # Missing public config produces an actual persisted application failure.
            outcome = run_problem(case.public_problem, root / "missing.yaml", output_root=root / "runs")
            evaluation = NL4OptEvaluator().evaluate(case, outcome.bundle_path)
            self.assertEqual(evaluation["run_status"], "failed")
            from llm4om import CancellationToken
            cancellation = CancellationToken()
            cancellation.cancel()
            cancelled = run_problem(case.public_problem, root / "missing.yaml", output_root=root / "runs", cancellation=cancellation)
            cancelled_evaluation = NL4OptEvaluator().evaluate(case, cancelled.bundle_path)
            self.assertEqual(cancelled_evaluation["run_status"], "cancelled")
            self.assertIsNone(cancelled_evaluation["checker_error"])
            self.assertEqual(cancelled_evaluation["N_evaluated"], 1)

            self.assertEqual(evaluation["objective_match"]["status"], "not_available")
            self.assertEqual(evaluation["N_eligible"], 0)
            self.assertIsNone(evaluation["objective_match_rate"])
            self.assertEqual(evaluation["semantic_validation"]["status"], "not_available")
            self.assertEqual(evaluation["execution"]["status"], "not_available")
            self.assertNotIn("oracle_ref", json.dumps(evaluation))
            self.assertNotIn("obj_declaration", json.dumps(evaluation))
            cli = subprocess.run([sys.executable, "-m", "llm4om", "evaluate", "--manifest", str(manifest),
                                  "--case-id", case.case_id, "--run", str(outcome.bundle_path),
                                  "--output", str(root / "evaluation.json")], capture_output=True, text=True)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertEqual(json.loads((root / "evaluation.json").read_text())["run_status"], "failed")
            for name, file, missing in [("public", case.public_problem, False), ("private", case.oracle_ref, False),
                                        ("missing-public", case.public_problem, True), ("missing-private", case.oracle_ref, True)]:
                with self.subTest(changed_snapshot=name):
                    original = file.read_bytes()
                    if missing:
                        file.unlink()
                    else:
                        file.write_bytes(b"{}\n")
                    output = root / f"{name}-error.json"
                    result = subprocess.run([sys.executable, "-m", "llm4om", "evaluate", "--manifest", str(manifest),
                        "--case-id", case.case_id, "--run", str(outcome.bundle_path), "--output", str(output)],
                        capture_output=True, text=True)
                    file.write_bytes(original)
                    self.assertEqual(result.returncode, 1)
                    self.assertTrue(output.is_file(), result.stdout)
                    error = json.loads(output.read_text())
                    self.assertIsNotNone(error["checker_error"])
                    self.assertEqual(error["N_selected"], 1)
                    self.assertEqual(error["N_eligible"], 0)
                    self.assertNotIn("oracle_ref", json.dumps(error))

    def test_imported_case_http_container_outcome_keeps_evidence_separate_and_private(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = {"document": "Choose nonnegative integer A,B. Maximize 3*A+2*B subject to 2*A+B<=8 and A+2*B<=8.",
                "vars": ["PRIVATE-ANNOTATION-SENTINEL"], "var_mentions": [], "params": [],
                "var_mention_to_first_var": {}, "first_var_to_mentions": {}, "obj_declaration": {},
                "const_declarations": [], "spans": [], "tokens": [], "_input_hash": 7, "order_mapping": {}}
            raw = (json.dumps({"7": record}) + "\n").encode()
            (root / "dev.jsonl").write_bytes(raw)
            config = {"schema_version": "0.1.0", "dataset_id": "fixture-nl4opt", "source_kind": "fixture",
                      "source_version": "test-v1", "split": "dev", "path": "dev.jsonl",
                      "sha256": hashlib.sha256(raw).hexdigest()}
            (root / "import.json").write_text(json.dumps(config))
            manifest = import_dataset(root / "import.json", root / "snapshot")
            case = next(NL4OptAdapter().iter_cases(manifest))
            formulation = json.loads((repo / "examples/specs/formulation.json").read_text())
            ir = json.loads((repo / "examples/specs/model-ir.json").read_text())
            for parameter, value in zip(formulation["representation"]["parameters"], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
                parameter.pop("source")
                parameter["value"] = value
            compact = {"representation": formulation["representation"], "structured_ir": {
                key: ir[key] for key in ("problem_type", "variables", "objective", "constraints", "assumptions")}}
            requests = []
            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({"id": "local-fixture", "model": "fixture", "choices": [
                        {"message": {"content": json.dumps(compact)}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}}).encode())
                def log_message(self, *args):
                    pass
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            settings = yaml.safe_load((repo / "examples/specs/run.yaml").read_text())
            settings["budget"]["max_total_tokens"] = 30000
            settings["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "fixture",
                "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "S07_TEST_KEY"}}
            (root / "run.yaml").write_text(yaml.safe_dump(settings))
            response = subprocess.run([sys.executable, "-m", "llm4om", "run", "--problem", str(case.public_problem),
                "--config", str(root / "run.yaml"), "--output", str(root / "runs")], cwd=root,
                env={**os.environ, "S07_TEST_KEY": "synthetic"}, capture_output=True, text=True)
            self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
            outcome = Path(json.loads(response.stdout)["bundle_path"])
            result = NL4OptEvaluator().evaluate(case, outcome)
            self.assertIsNone(result["checker_error"], result)
            self.assertEqual(result["execution"], {"status": "completed", "mode": "container"})
            self.assertEqual(result["candidate_primal"]["reported_objective"], 13)
            self.assertEqual(result["formulation_validation"]["status"], "pass")
            self.assertEqual(result["objective_match"]["status"], "not_available")
            self.assertEqual(result["semantic_validation"]["status"], "not_available")
            exported = "\n".join(path.read_text() for path in outcome.rglob("*") if path.is_file())
            for text in (exported, json.dumps(requests)):
                self.assertNotIn("PRIVATE-ANNOTATION-SENTINEL", text)
                self.assertNotIn("oracle_ref", text)
                self.assertNotIn("dev.jsonl", text)
                self.assertNotIn(str(case.oracle_ref), text)
            public_prompt = json.loads(requests[0]["messages"][1]["content"])
            self.assertEqual(public_prompt["problem"]["description"], record["document"])
            self.assertEqual(public_prompt["data"], {})
            # Another imported public revision cannot borrow this run's evidence.
            record["document"] = "A different public problem."
            other_raw = (json.dumps({"7": record}) + "\n").encode()
            (root / "dev.jsonl").write_bytes(other_raw)
            config["sha256"] = hashlib.sha256(other_raw).hexdigest()
            (root / "import.json").write_text(json.dumps(config))
            other_manifest = import_dataset(root / "import.json", root / "other-snapshot")
            other_case = next(NL4OptAdapter().iter_cases(other_manifest))
            wrong = NL4OptEvaluator().evaluate(other_case, outcome)
            self.assertEqual(wrong["checker_error"]["code"], "outcome_case_mismatch")
            self.assertEqual(wrong["formulation_validation"]["status"], "error")
            original_bundle = (outcome / "bundle.json").read_text()
            unsupported = json.loads(original_bundle)
            unsupported["schema_version"] = "999.0.0"
            (outcome / "bundle.json").write_text(json.dumps(unsupported))
            version_error = NL4OptEvaluator().evaluate(case, outcome)
            self.assertEqual(version_error["checker_error"]["code"], "invalid_outcome")
            (outcome / "bundle.json").write_text(original_bundle)
            for name in ["artifact.json", "formulation.json", "structured-ir.json", "model.py"]:
                with self.subTest(changed_evidence=name):
                    file = outcome / "candidates/001" / name
                    original = file.read_bytes()
                    file.write_bytes(b"corrupted evidence\n")
                    broken = NL4OptEvaluator().evaluate(case, outcome)
                    file.write_bytes(original)
                    self.assertIsNotNone(broken["checker_error"])
                    self.assertEqual(broken["formulation_validation"]["status"], "error")
                    self.assertEqual(broken["code_validation"]["status"], "error")
            # Corrupted evidence is a retained checker error, never a pass.
            (outcome / "candidates/001/solve-result.json").write_text("{}")
            broken = NL4OptEvaluator().evaluate(case, outcome)
            self.assertEqual(broken["checker_error"]["code"], "evidence_hash_mismatch")
            self.assertEqual(broken["candidate_primal"]["status"], "error")


class ImportResourceTests(unittest.TestCase):
    def test_frozen_import_does_not_create_live_run_or_leak_descriptors(self) -> None:
        record={'document':'Fixture problem.','vars':[],'var_mentions':[],'params':[],
        'var_mention_to_first_var':{},'first_var_to_mentions':{},'obj_declaration':{},'const_declarations':[],
        'spans':[],'tokens':[],'_input_hash':7,'order_mapping':{}}
        raw=(json.dumps({'7':record})+'\n').encode()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'dev.jsonl').write_bytes(raw)
            cfg={'schema_version':'0.1.0','dataset_id':'fixture-nl4opt','source_kind':'fixture','source_version':'probe-v1',
            'split':'dev','path':'dev.jsonl','sha256':hashlib.sha256(raw).hexdigest()}
            (root/'import.json').write_text(json.dumps(cfg))
            before=len(os.listdir('/proc/self/fd'))
            manifests=[import_dataset(root/'import.json',root/f'snapshot{i}') for i in range(3)]
            self.assertEqual(len(os.listdir('/proc/self/fd')),before)
            for manifest in manifests:
                self.assertFalse((manifest.parent/'control.json').exists())
                case=json.loads(manifest.read_text())['cases'][0]
                self.assertEqual(case['public_ref']['relative_path'],'public/7.json')
