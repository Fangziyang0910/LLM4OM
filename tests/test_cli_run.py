"""Exercise the offline slice through the user-facing CLI and public bundle."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/specs"


class OfflineRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "runs"

    def run_cli(self, problem: Path = FIXTURE / "problem.json",
                config: Path = FIXTURE / "run.yaml", *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "llm4om", "run", "--problem", str(problem),
             "--config", str(config), "--output", str(self.output), *extra],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True, text=True, cwd=self.temp.name,
        )

    def bundle(self, result: subprocess.CompletedProcess) -> tuple[Path, dict]:
        summary = json.loads(result.stdout)
        path = Path(summary["bundle_path"])
        return path, json.loads((path / "bundle.json").read_text())

    def fixture_copy(self) -> Path:
        destination = Path(self.temp.name) / "input"
        shutil.copytree(FIXTURE, destination)
        return destination

    def test_offline_run_exports_formulation_and_verified_public_data(self) -> None:
        result = self.run_cli(
            FIXTURE / "problem.json", FIXTURE / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        path, bundle = self.bundle(result)
        self.assertEqual(bundle["status"], "artifact_ready")
        self.assertEqual(bundle["mode"], "offline_mock")
        self.assertEqual(bundle["stages"]["formulation"]["status"], "available")
        self.assertEqual(bundle["stages"]["code"]["status"], "pending")
        self.assertEqual(bundle["stages"]["solve"]["status"], "not_available")
        artifact = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
        formulation = json.loads((path / artifact["formulation_ref"]["relative_path"]).read_text())
        self.assertEqual(set(formulation["representation"]),
                         {"sets", "parameters", "variables", "objective", "constraints"})
        self.assertEqual(formulation["representation"]["variables"][0]["domain"], "integer")
        self.assertEqual(formulation["provenance"]["origin"], "hand_authored_design_fixture")
        problem = json.loads((path / "public-problem.json").read_text())
        for ref in problem["data_refs"]:
            raw = (path / ref["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), ref["sha256"])
        self.assertEqual(problem["description"], json.loads((FIXTURE / "problem.json").read_text())["description"])
        self.assertFalse((path / "solve-result.json").exists())
        self.assertFalse(any(file.name == "oracle.json" for file in path.rglob("*")))

    def test_changed_csv_fails_before_mock_and_keeps_failure_bundle(self) -> None:
        inputs = self.fixture_copy()
        (inputs / "data/products.csv").write_text("product_id,profit,cutting,finishing\nA,999,2,1\nB,2,1,2\n")
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        path, bundle = self.bundle(result)
        self.assertEqual(bundle["status"], "failed")
        self.assertEqual(bundle["error"]["code"], "data_hash_mismatch")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["llm_attempts"], 0)
        events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
        self.assertEqual(events[-1]["status"], "failed")

    def test_mock_replay_requires_explicit_offline_mode(self) -> None:
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        _, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "offline_required")

    def test_config_admission_rejects_unsupported_or_invalid_requests(self) -> None:
        inputs = self.fixture_copy()
        original = yaml.safe_load((inputs / "run.yaml").read_text())
        cases = [
            ("method", {"plugin_id": "invented.method", "config": {}}),
            ("schema_version", "99.0.0"),
            ("budget", {**original["budget"], "max_llm_attempts": 0}),
            ("task", {"plugin_id": "hidden.task"}),
            ("method", {**original["method"], "config": {"formulation_mode": "five_element", "output_mode": "python_factory"}}),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                settings = {**original, key: value}
                (inputs / "run.yaml").write_text(yaml.safe_dump(settings))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                path, bundle = self.bundle(result)
                self.assertIn(bundle["error"]["code"], {"invalid_config", "unsupported_config", "unknown_plugin"})
                self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)

    def test_zero_solver_budget_is_valid_for_the_offline_profile(self) -> None:
        inputs = self.fixture_copy()
        settings = yaml.safe_load((inputs / "run.yaml").read_text())
        settings["budget"]["max_solver_calls"] = 0
        settings["budget"]["max_total_tokens"] = 0
        (inputs / "run.yaml").write_text(yaml.safe_dump(settings))
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        path, _ = self.bundle(result)
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 0)

    def test_problem_boundary_rejects_ambiguous_json_and_unsupported_schema(self) -> None:
        inputs = self.fixture_copy()
        original = (inputs / "problem.json").read_text()
        cases = [
            original.replace('"revision": "1"', '"revision": "1", "revision": "2"'),
            original.replace('"revision": "1"', '"revision": NaN'),
            original.replace('"revision": "1"', '"revision": 1e999'),
            original.replace('"schema_version": "0.2.0"', '"schema_version": "99.0.0"'),
            original.replace('"description":', '"unexpected": "field", "description":'),
        ]
        for content in cases:
            with self.subTest(content=content[:40]):
                (inputs / "problem.json").write_text(content)
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                path, bundle = self.bundle(result)
                self.assertIn(bundle["error"]["code"], {"invalid_json", "invalid_problem"})
                self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)

    def test_mock_packet_cannot_be_rebound_to_a_different_problem(self) -> None:
        inputs = self.fixture_copy()
        public = json.loads((inputs / "problem.json").read_text())
        public["description"] = "最小化资源消耗，而不是最大化利润。"
        (inputs / "problem.json").write_text(json.dumps(public))
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        _, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "artifact_problem_mismatch")

    def test_data_paths_cannot_escape_the_problem_directory(self) -> None:
        inputs = self.fixture_copy()
        external = Path(self.temp.name) / "outside.csv"
        external.write_bytes((inputs / "data/products.csv").read_bytes())
        (inputs / "data/linked.csv").symlink_to(external)
        public = json.loads((inputs / "problem.json").read_text())
        for relative in ["../outside.csv", str(external), "data/linked.csv"]:
            with self.subTest(path=relative):
                public["data_refs"][0]["path"] = relative
                (inputs / "problem.json").write_text(json.dumps(public))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                _, bundle = self.bundle(result)
                self.assertEqual(bundle["error"]["code"], "unsafe_path")

    def test_symlink_loops_preserve_a_failure_bundle(self) -> None:
        inputs = self.fixture_copy()
        (inputs / "data/loop.csv").symlink_to("loop.csv")
        public = json.loads((inputs / "problem.json").read_text())
        public["data_refs"][0]["path"] = "data/loop.csv"
        (inputs / "problem.json").write_text(json.dumps(public))
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        _, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "unsafe_path")

    def test_mock_references_are_verified_before_export(self) -> None:
        inputs = self.fixture_copy()
        (inputs / "formulation.json").write_text((inputs / "formulation.json").read_text() + " ")
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        _, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "artifact_hash_mismatch")

    def test_additional_artifact_references_are_rejected_before_export(self) -> None:
        inputs = self.fixture_copy()
        original = json.loads((inputs / "model-artifact.json").read_text())
        dangling = {**original["formulation_ref"], "relative_path": "../outside.json"}
        for key in ["optional_views", "provenance", "requirement_traces"]:
            with self.subTest(key=key):
                model = json.loads(json.dumps(original))
                if key == "provenance":
                    model[key]["extra_ref"] = dangling
                else:
                    model[key] = [{"artifact_ref": dangling}]
                (inputs / "model-artifact.json").write_text(json.dumps(model))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                _, bundle = self.bundle(result)
                self.assertEqual(bundle["error"]["code"], "unsupported_reference")
                self.assertIsNone(bundle["model_artifact_ref"])

    def test_structured_ir_must_belong_to_the_public_problem_revision(self) -> None:
        inputs = self.fixture_copy()
        original_ir = json.loads((inputs / "model-ir.json").read_text())
        original_formulation = json.loads((inputs / "formulation.json").read_text())
        original_model = json.loads((inputs / "model-artifact.json").read_text())
        for key in ["problem_id", "problem_revision"]:
            with self.subTest(key=key):
                ir = {**original_ir, key: "different"}
                raw = json.dumps(ir).encode()
                (inputs / "model-ir.json").write_bytes(raw)
                formulation = json.loads(json.dumps(original_formulation))
                formulation["structured_ir_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                raw = json.dumps(formulation).encode()
                (inputs / "formulation.json").write_bytes(raw)
                model = json.loads(json.dumps(original_model))
                model["formulation_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                (inputs / "model-artifact.json").write_text(json.dumps(model))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                _, bundle = self.bundle(result)
                self.assertEqual(bundle["error"]["code"], "artifact_problem_mismatch")

    def test_structurally_invalid_mock_output_is_not_marked_available(self) -> None:
        inputs = self.fixture_copy()
        original = json.loads((inputs / "formulation.json").read_text())
        original_model = json.loads((inputs / "model-artifact.json").read_text())
        for change in ["missing_constraints", "wrong_bindings", "wrong_revision", "claimed_code",
                       "sets", "parameters", "variables", "constraints"]:
            with self.subTest(change=change):
                formulation = json.loads(json.dumps(original))
                model = json.loads(json.dumps(original_model))
                if change == "missing_constraints":
                    del formulation["representation"]["constraints"]
                elif change == "wrong_bindings":
                    formulation["data_bindings"][0]["sha256"] = "0" * 64
                elif change == "wrong_revision":
                    formulation["problem_revision"] = "2"
                elif change == "claimed_code":
                    model["stage_status"]["code"] = {"status": "available", "reason": None}
                else:
                    formulation["representation"][change] = [{"id": "incomplete"}]
                raw = (json.dumps(formulation, ensure_ascii=False, indent=2) + "\n").encode()
                (inputs / "formulation.json").write_bytes(raw)
                model["formulation_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                (inputs / "model-artifact.json").write_text(json.dumps(model))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                _, bundle = self.bundle(result)
                self.assertIn(bundle["error"]["code"], {"invalid_formulation", "invalid_model_artifact", "artifact_data_mismatch"})
                self.assertIsNone(bundle["model_artifact_ref"])

    def test_literal_parameter_values_must_contain_finite_numbers(self) -> None:
        inputs = self.fixture_copy()
        original_formulation = json.loads((inputs / "formulation.json").read_text())
        original_model = json.loads((inputs / "model-artifact.json").read_text())
        for value, expected in [(None, 1), ({"A": None}, 1), (True, 1), (0, 0), ({"A": 3, "B": 2}, 0)]:
            with self.subTest(value=value):
                formulation = json.loads(json.dumps(original_formulation))
                formulation["representation"]["parameters"][0] = {
                    "id": "profit", "index_sets": ["products"], "value": value}
                raw = json.dumps(formulation).encode()
                (inputs / "formulation.json").write_bytes(raw)
                model = json.loads(json.dumps(original_model))
                model["formulation_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                (inputs / "model-artifact.json").write_text(json.dumps(model))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, expected, result.stderr)
                _, bundle = self.bundle(result)
                if expected:
                    self.assertEqual(bundle["error"]["code"], "invalid_formulation")

    def test_parameter_sources_must_name_at_least_one_existing_column(self) -> None:
        inputs = self.fixture_copy()
        original_formulation = json.loads((inputs / "formulation.json").read_text())
        original_model = json.loads((inputs / "model-artifact.json").read_text())
        for columns in [[], ["missing"], [None]]:
            with self.subTest(columns=columns):
                formulation = json.loads(json.dumps(original_formulation))
                formulation["representation"]["parameters"][0]["source"] = {"data_id": "products", "columns": columns}
                raw = json.dumps(formulation).encode()
                (inputs / "formulation.json").write_bytes(raw)
                model = json.loads(json.dumps(original_model))
                model["formulation_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                (inputs / "model-artifact.json").write_text(json.dumps(model))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                _, bundle = self.bundle(result)
                self.assertEqual(bundle["error"]["code"], "invalid_formulation")

    def test_private_fields_are_rejected_without_exporting_their_values(self) -> None:
        inputs = self.fixture_copy()
        public = json.loads((inputs / "problem.json").read_text())
        secret = "PRIVATE-SENTINEL-DO-NOT-EXPORT"
        public["metadata"]["nested"] = {"api_key": secret, "oracle_path": "oracle.json"}
        (inputs / "problem.json").write_text(json.dumps(public))
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        path, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "private_input")
        for file in path.rglob("*"):
            if file.is_file():
                self.assertNotIn(secret, file.read_text())
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_credential_aliases_and_oracle_payload_fields_never_reach_exports(self) -> None:
        inputs = self.fixture_copy()
        original = json.loads((inputs / "problem.json").read_text())
        for key in ["client_secret", "reference_model", "reference_variables", "independent_checker", "refresh_token"]:
            with self.subTest(key=key):
                public = {**original, "metadata": {key: "HIDDEN-PAYLOAD-SENTINEL"}}
                (inputs / "problem.json").write_text(json.dumps(public))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                path, bundle = self.bundle(result)
                self.assertEqual(bundle["error"]["code"], "private_input")
                for file in path.rglob("*"):
                    if file.is_file():
                        self.assertNotIn("HIDDEN-PAYLOAD-SENTINEL", file.read_text())

    def test_unregistered_metadata_cannot_bypass_public_projection(self) -> None:
        inputs = self.fixture_copy()
        public = json.loads((inputs / "problem.json").read_text())
        public["metadata"] = {"custom_payload": "PRIVATE-UNKNOWN-FIELD"}
        (inputs / "problem.json").write_text(json.dumps(public))
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        path, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "invalid_problem")
        for file in path.rglob("*"):
            if file.is_file():
                self.assertNotIn("PRIVATE-UNKNOWN-FIELD", file.read_text())

    def test_yaml_boundary_rejects_duplicates_nonfinite_values_and_secrets(self) -> None:
        inputs = self.fixture_copy()
        original = (inputs / "run.yaml").read_text()
        cases = [original + '\nschema_version: "0.2.0"\n',
                 original.replace("wall_time_s: 60", "wall_time_s: .inf"),
                 original.replace('response_artifact: "model-artifact.json"', 'response_artifact: "model-artifact.json"\n    api_key: PRIVATE-KEY'),
                 original + "\nrecursive: &loop [*loop]\n"]
        for content in cases:
            with self.subTest(content=content[-70:]):
                (inputs / "run.yaml").write_text(content)
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                path, bundle = self.bundle(result)
                self.assertIn(bundle["error"]["code"], {"invalid_config", "private_input"})
                for file in path.rglob("*"):
                    if file.is_file():
                        self.assertNotIn("PRIVATE-KEY", file.read_text())

    def test_csv_schema_is_checked_before_mock_admission(self) -> None:
        inputs = self.fixture_copy()
        public = json.loads((inputs / "problem.json").read_text())
        for raw in [b"product_id,profit,cutting,finishing\nA,3,2,1\nA,2,1,2\n",
                    b"product_id,profit,cutting,finishing\nA,NaN,2,1\n",
                    b"product_id,profit,cutting,finishing\nA,,2,1\n",
                    b"product_id,wrong_column,cutting,finishing\nA,3,2,1\n"]:
            with self.subTest(raw=raw):
                (inputs / "data/products.csv").write_bytes(raw)
                public["data_refs"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
                (inputs / "problem.json").write_text(json.dumps(public))
                result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
                self.assertEqual(result.returncode, 1)
                path, bundle = self.bundle(result)
                self.assertEqual(bundle["error"]["code"], "invalid_data")
                self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)

    def test_csv_unique_keys_follow_declared_numeric_types(self) -> None:
        inputs = self.fixture_copy()
        raw = b"product_id,profit,cutting,finishing\n1,3,2,1\n1.0,2,1,2\n"
        (inputs / "data/products.csv").write_bytes(raw)
        public = json.loads((inputs / "problem.json").read_text())
        public["data_refs"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
        public["data_refs"][0]["schema"]["columns"][0]["type"] = "integer"
        (inputs / "problem.json").write_text(json.dumps(public))
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        path, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "invalid_data")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)

    def test_saved_evidence_and_report_are_consistent_and_do_not_claim_solving(self) -> None:
        result = self.run_cli(FIXTURE / "problem.json", FIXTURE / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        path, bundle = self.bundle(result)
        for ref in bundle["artifacts"]:
            raw = (path / ref["relative_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), ref["sha256"])
            self.assertEqual(len(raw), ref["size_bytes"])
        report = (path / "reports/report.md").read_text()
        self.assertIn("offline_mock", report)
        self.assertIn("pending", report)
        self.assertIn("not_available", report)
        config = json.loads((path / "public-config.json").read_text())
        self.assertEqual(config["store"]["config"]["root"], ".")
        self.assertEqual(bundle["execution_plan"]["solver"]["status"], "not_available")
        self.assertEqual(bundle["execution_plan"]["solver"]["requested_plugin_id"], "llm4om.solvers.highs")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["llm_attempts"], 1)
        self.assertEqual(ledger["external_llm_requests"], 0)
        self.assertEqual(ledger["solver_calls"], 0)
        evaluation = json.loads((path / "evaluation.json").read_text())
        self.assertEqual(evaluation["semantic_validation"]["status"], "not_available")

    def test_malformed_config_objects_still_produce_readable_failure_bundles(self) -> None:
        inputs = self.fixture_copy()
        settings = yaml.safe_load((inputs / "run.yaml").read_text())
        settings.update(solver=17, reporters=[None])
        (inputs / "run.yaml").write_text(yaml.safe_dump(settings))
        result = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        _, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "invalid_config")

    def test_no_oracle_or_manual_requirement_split_is_needed_and_runs_are_independent(self) -> None:
        inputs = self.fixture_copy()
        (inputs / "oracle.json").unlink()
        (inputs / "expected-evaluation.json").unlink()
        public = json.loads((inputs / "problem.json").read_text())
        public.update(requirements=[], problem_type_hint="unknown")
        for ref in public["data_refs"]:
            ref["sha256"] = None
        raw = json.dumps(public, ensure_ascii=False).encode()
        (inputs / "problem.json").write_bytes(raw)
        model = json.loads((inputs / "model-artifact.json").read_text())
        model["problem_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        (inputs / "model-artifact.json").write_text(json.dumps(model))
        first = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        second = self.run_cli(inputs / "problem.json", inputs / "run.yaml", "--offline")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        first_path, first_bundle = self.bundle(first)
        second_path, second_bundle = self.bundle(second)
        self.assertNotEqual(first_bundle["run_id"], second_bundle["run_id"])
        self.assertNotEqual(first_path, second_path)
        normalized = json.loads((first_path / "public-problem.json").read_text())
        self.assertEqual(normalized["requirements"], [])
        self.assertTrue(all(len(ref["sha256"]) == 64 for ref in normalized["data_refs"]))
        self.assertEqual((inputs / "problem.json").read_bytes(), raw)

    def test_unwritable_store_reports_a_storage_error_without_overwriting_input(self) -> None:
        self.output.write_text("Existing user data.\n")
        result = self.run_cli(FIXTURE / "problem.json", FIXTURE / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "store_unavailable")
        self.assertEqual(self.output.read_text(), "Existing user data.\n")

    def test_artifact_write_failure_is_reported_as_storage_failure(self) -> None:
        script = '''
import os
from pathlib import Path
from unittest.mock import patch
from llm4om.cli import main
replace = os.replace
def fail_artifact_write(source, target, *args, **kwargs):
    if Path(target).name == "formulation.json":
        raise OSError("Injected filesystem write failure.")
    return replace(source, target, *args, **kwargs)
with patch("os.replace", side_effect=fail_artifact_write):
    raise SystemExit(main())
'''
        result = subprocess.run(
            [sys.executable, "-c", script, "run", "--offline", "--problem", str(FIXTURE / "problem.json"),
             "--config", str(FIXTURE / "run.yaml"), "--output", str(self.output)],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True, text=True, cwd=self.temp.name,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "store_unavailable")

    def test_missing_public_input_still_saves_an_input_failure_bundle(self) -> None:
        result = self.run_cli(Path(self.temp.name) / "missing.json", FIXTURE / "run.yaml", "--offline")
        self.assertEqual(result.returncode, 1)
        _, bundle = self.bundle(result)
        self.assertEqual(bundle["error"]["code"], "input_unavailable")


if __name__ == "__main__":
    unittest.main()
