"""Task and Evaluator registration through the public CLI and frozen evidence."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil
import hashlib
import yaml

ROOT = Path(__file__).resolve().parents[1]


class TaskPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packages = self.root / "packages"

    def cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "llm4om", *arguments], cwd=self.root,
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, timeout=60)

    def test_builtin_task_and_evaluator_manifests_are_in_the_common_registry(self):
        result = self.cli("plugins", "list")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        items = json.loads(result.stdout)["plugins"]
        tasks = [item["manifest"] for item in items if item["manifest"]["kind"] == "task_adapter"]
        evaluators = [item["manifest"] for item in items if item["manifest"]["kind"] == "evaluator"]
        self.assertEqual({item["plugin_id"] for item in tasks}, {"llm4om.tasks.nl4opt", "llm4om.tasks.nlp4lp", "llm4om.tasks.mamo", "llm4om.tasks.checker_fixture"})
        self.assertEqual(len(evaluators), 4)
        by_id = {item["plugin_id"]: item for item in evaluators}
        for manifest in tasks:
            caps = manifest["capabilities"]
            self.assertEqual(caps["task_profile"], "frozen_task/0.1.0")
            self.assertEqual(caps["oracle_separation"], "separate_public_private/0.1.0")
            evaluator = by_id[caps["default_evaluator_id"]]
            self.assertEqual(evaluator["capabilities"]["protocol_ids"], caps["protocol_ids"])

    def install_task(self):
        project = self.root / "task"
        shutil.copytree(ROOT / "examples/plugins/fixture_task", project)
        subprocess.run(["uv", "build", "--offline", "--wheel", "--out-dir", str(self.root / "dist")], cwd=project,
                       check=True, capture_output=True, text=True)
        wheel = next((self.root / "dist").glob("*.whl"))
        subprocess.run(["uv", "pip", "install", "--no-deps", "--target", str(self.packages), str(wheel)],
                       check=True, capture_output=True, text=True)

    def write_task(self):
        inputs = self.root / "input"
        shutil.copytree(ROOT / "examples/specs", inputs)
        reference = inputs / "reference.json"
        reference.write_text(json.dumps({"value": 13, "private_sentinel": "HIDDEN-TASK-SENTINEL"}))
        settings = {"schema_version": "0.1.0", "adapter_id": "llm4om.examples.micro_task",
            "adapter_config": {"dataset_id": "installed-production"}, "evaluation": {"evaluator_plugin_id": "llm4om.examples.micro_evaluator", "config": {"abs_tol": 0}},
            "problem_path": "problem.json", "problem_sha256": hashlib.sha256((inputs / "problem.json").read_bytes()).hexdigest(),
            "reference_path": "reference.json", "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest()}
        config = inputs / "import.json"
        config.write_text(json.dumps(settings))
        return inputs, config

    def import_task(self, config):
        result = self.cli("import", "--config", str(config), "--output", str(self.root / "snapshot"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest_path = Path(json.loads(result.stdout)["manifest_path"])
        return manifest_path, json.loads(manifest_path.read_text())

    def solved_task(self):
        inputs, config = self.write_task()
        manifest_path, manifest = self.import_task(config)
        entry = manifest["cases"][0]
        run = self.cli("run", "--problem", str(manifest_path.parent / entry["public_ref"]["relative_path"]),
            "--config", str(self.run_config(inputs)), "--output", str(self.root / "runs"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return manifest_path, manifest, Path(json.loads(run.stdout)["bundle_path"])

    def run_config(self, inputs):
        if not os.environ.get("LLM4OM_TEST_IMAGE"):
            return inputs / "solve.yaml"
        settings = yaml.safe_load((inputs / "run.yaml").read_text())
        settings["executor"]["config"]["image"] = os.environ["LLM4OM_TEST_IMAGE"]
        path = inputs / "container-test.yaml"
        path.write_text(yaml.safe_dump(settings))
        return path

    def evaluate(self, manifest_path, manifest, run, name="evaluation.json"):
        return self.cli("evaluate", "--manifest", str(manifest_path), "--case-id", manifest["cases"][0]["case_id"],
                        "--run", str(run), "--output", str(self.root / name))

    def modify_package(self, old, new):
        path = self.packages / "llm4om_fixture_task/__init__.py"
        value = path.read_text()
        self.assertIn(old, value)
        path.write_text(value.replace(old, new))
        shutil.rmtree(path.parent / "__pycache__", ignore_errors=True)

    def test_installed_task_import_run_and_evaluator_use_frozen_privileged_selection(self):
        self.install_task()
        inputs, config = self.write_task()
        manifest_path, manifest = self.import_task(config)
        bindings = manifest["plugin_bindings"]
        self.assertEqual(bindings["task_adapter"]["origin"]["distribution"], "llm4om-fixture-task")
        self.assertEqual(bindings["evaluator"]["config"], {"abs_tol": 0})
        entry = manifest["cases"][0]
        public = manifest_path.parent / entry["public_ref"]["relative_path"]
        self.assertNotIn("HIDDEN-TASK-SENTINEL", public.read_text())
        run = self.cli("run", "--problem", str(public), "--config", str(self.run_config(inputs)), "--output", str(self.root / "runs"))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        path = Path(json.loads(run.stdout)["bundle_path"])
        self.assertEqual(json.loads((path / "candidates/001/solve-result.json").read_text())["objective_value"], 13)
        result = self.cli("evaluate", "--manifest", str(manifest_path), "--case-id", entry["case_id"], "--run", str(path), "--output", str(self.root / "evaluation.json"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evaluation = json.loads(result.stdout)
        self.assertEqual(evaluation["objective_match_numerator"], 1)
        self.assertEqual(evaluation["objective_match_denominator"], 1)
        self.assertEqual(evaluation["case_binding"]["status"], "pass")
        self.assertEqual(evaluation["plugin_identity"]["binding_status"], "frozen")
        self.assertNotIn("HIDDEN-TASK-SENTINEL", result.stdout)
        self.assertNotIn("oracle_ref", result.stdout)
        self.assertNotIn("HIDDEN-TASK-SENTINEL", "".join(p.read_text() for p in path.rglob("*") if p.is_file()))

    def test_privileged_oracle_fields_cannot_enter_public_evaluator_export(self):
        self.install_task()
        self.modify_package("return evaluate_outcome(case, outcome, result, compare)",
            'result = evaluate_outcome(case, outcome, result, compare)\n        result["oracle_ref"] = {"namespace": "task_private", "relative_path": "private/reference.json"}\n        return result')
        manifest_path, manifest, run = self.solved_task()
        result = self.evaluate(manifest_path, manifest, run)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_evaluation_result")
        self.assertFalse((self.root / "evaluation.json").exists())
        self.assertNotIn("task_private", result.stdout + result.stderr)

    def test_post_import_config_or_package_changes_reject_without_mutating_saved_evidence(self):
        self.install_task()
        manifest_path, manifest, run = self.solved_task()
        original = manifest_path.read_bytes()
        manifest["plugin_bindings"]["evaluator"]["config"]["abs_tol"] = 1
        manifest_path.write_text(json.dumps(manifest))
        changed = self.evaluate(manifest_path, manifest, run)
        self.assertEqual(changed.returncode, 1, changed.stdout + changed.stderr)
        self.assertEqual(json.loads(changed.stdout)["error"]["code"], "checkpoint_incompatible")
        self.assertFalse((self.root / "evaluation.json").exists())

        manifest_path.write_bytes(original)
        manifest = json.loads(original)
        history = (run / "events.jsonl").read_bytes()
        source = self.packages / "llm4om_fixture_task/__init__.py"
        source.write_text(source.read_text() + "\n# changed installed code\n")
        drift = self.evaluate(manifest_path, manifest, run)
        self.assertEqual(json.loads(drift.stdout)["error"]["code"], "checkpoint_incompatible")
        self.assertEqual(manifest_path.read_bytes(), original)
        self.assertEqual((run / "events.jsonl").read_bytes(), history)
        self.assertFalse((self.root / "evaluation.json").exists())

    def test_unknown_evaluator_exception_preserves_eligible_denominator_and_safe_error(self):
        self.install_task()
        self.modify_package("        manifest, entry = parse_reference_json(case.manifest), parse_reference_json(case.entry)",
                            '        print("PRIVATE-EVALUATOR-ERROR")\n        raise RuntimeError("PRIVATE-EVALUATOR-ERROR")')
        manifest_path, manifest, run = self.solved_task()
        result = self.evaluate(manifest_path, manifest, run)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["objective_match_numerator"], 0)
        self.assertEqual(record["objective_match_denominator"], 1)
        self.assertEqual(record["checker_error"]["code"], "evaluator_error")
        self.assertNotIn("PRIVATE-EVALUATOR-ERROR", result.stdout + result.stderr)
        self.assertTrue((self.root / "evaluation.json").exists())

    def test_wrong_case_counts_and_undeclared_evidence_reject_public_result(self):
        self.install_task()
        source = self.packages / "llm4om_fixture_task/__init__.py"
        original = source.read_text()
        for statement in ['result["case_id"] = "different-case"', 'result["N_eligible"] = 0', 'result["source"]["oracle"] = {"value": 13}', 'result["objective_match_denominator"] = 0',
                          'result["semantic_validation"] = {"status": "pass"}', 'result["objective_match_rate"] = float("nan")']:
            with self.subTest(statement=statement):
                source.write_text(original.replace("return evaluate_outcome(case, outcome, result, compare)",
                    "result = evaluate_outcome(case, outcome, result, compare)\n        " + statement + "\n        return result"))
                shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
                manifest_path, manifest, run = self.solved_task()
                result = self.evaluate(manifest_path, manifest, run)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_evaluation_result")
                self.assertFalse((self.root / "evaluation.json").exists())
                shutil.rmtree(self.root / "input")
                shutil.rmtree(self.root / "snapshot")

    def test_result_must_identify_the_actual_run_and_keep_metric_status_consistent(self):
        self.install_task()
        source = self.packages / "llm4om_fixture_task/__init__.py"
        original = source.read_text()
        for statement in ['result["run_id"] = "another-run"', 'result["run_status"] = "failed"',
                          'result["objective_match"]["status"] = "not_available"']:
            with self.subTest(statement=statement):
                source.write_text(original.replace("return evaluate_outcome(case, outcome, result, compare)",
                    "result = evaluate_outcome(case, outcome, result, compare)\n        " + statement + "\n        return result"))
                shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
                manifest_path, manifest, run = self.solved_task()
                try:
                    result = self.evaluate(manifest_path, manifest, run)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_evaluation_result")
                    self.assertFalse((self.root / "evaluation.json").exists())
                finally:
                    shutil.rmtree(self.root / "input")
                    shutil.rmtree(self.root / "snapshot")
                    (self.root / "evaluation.json").unlink(missing_ok=True)

    def test_incompatible_protocol_or_missing_dependency_rejects_before_snapshot_publication(self):
        self.install_task()
        inputs, config = self.write_task()
        settings = json.loads(config.read_text())
        settings["evaluation"]["evaluator_plugin_id"] = "llm4om.evaluators.nl4opt"
        settings["evaluation"]["config"] = {}
        config.write_text(json.dumps(settings))
        result = self.cli("import", "--config", str(config), "--output", str(self.root / "snapshot"))
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "capability_mismatch")
        self.assertFalse((self.root / "snapshot").exists())
        settings["evaluation"]["evaluator_plugin_id"] = "llm4om.examples.micro_evaluator"
        settings["evaluation"]["config"] = {"abs_tol": 0}
        config.write_text(json.dumps(settings))
        self.modify_package('"dependencies": {"python": []}', '"dependencies": {"python": ["llm4om-absent-task-dependency"]}')
        result = self.cli("import", "--config", str(config), "--output", str(self.root / "snapshot"))
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "dependency_missing")
        self.assertFalse((self.root / "snapshot").exists())

    def test_legacy_builtin_snapshot_uses_explicit_unbound_identity_without_rewriting_it(self):
        inputs, config = self.write_task()
        record = {"document": "Original public problem.", "vars": [], "var_mentions": [], "params": [],
                  "var_mention_to_first_var": {}, "first_var_to_mentions": {}, "obj_declaration": {},
                  "const_declarations": [], "spans": [], "tokens": [], "_input_hash": 7, "order_mapping": {}}
        raw = (json.dumps({"7": record}) + "\n").encode()
        (inputs / "dev.jsonl").write_bytes(raw)
        config.write_text(json.dumps({"schema_version": "0.1.0", "dataset_id": "fixture-legacy", "source_kind": "fixture",
            "source_version": "test-v1", "split": "dev", "path": "dev.jsonl", "sha256": hashlib.sha256(raw).hexdigest()}))
        manifest_path, manifest = self.import_task(config)
        manifest.pop("plugin_bindings")
        (manifest_path.parent / "private/import-seal.json").unlink()
        manifest_path.write_text(json.dumps(manifest))
        original = manifest_path.read_bytes()
        result = self.evaluate(manifest_path, manifest, self.root / "missing-run")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["plugin_identity"]["binding_status"], "legacy_unbound")
        self.assertEqual(record["N_eligible"], 0)
        self.assertEqual(manifest_path.read_bytes(), original)

    def test_doctor_task_preflights_registered_selections_without_reading_private_source(self):
        self.install_task()
        inputs, config = self.write_task()
        (inputs / "reference.json").unlink()
        result = self.cli("doctor", "--task-config", str(config))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = json.loads(result.stdout)["execution_plan"]
        self.assertEqual(plan["task_adapter"]["manifest"]["plugin_id"], "llm4om.examples.micro_task")
        self.assertEqual(plan["evaluator"]["manifest"]["plugin_id"], "llm4om.examples.micro_evaluator")
        self.assertFalse((self.root / "snapshot").exists())

    def test_frozen_task_census_must_match_actual_selected_unique_cases(self):
        self.install_task()
        self.modify_package('"N_selected": 1, "N_eligible": 1, "cases": [entry]',
                            '"N_selected": 2, "N_eligible": 1, "cases": [entry]')
        _, config = self.write_task()
        result = self.cli("import", "--config", str(config), "--output", str(self.root / "snapshot"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_manifest")
        self.assertFalse((self.root / "snapshot").exists())



if __name__ == "__main__":
    unittest.main()
