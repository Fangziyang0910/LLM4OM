"""Exercise installed method discovery and preflight through the CLI."""

import json
import os
import subprocess
import sys
import tempfile
import shutil
from textwrap import indent
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packages = self.root / "packages"
        self.inputs = self.root / "input"
        shutil.copytree(ROOT / "examples/specs", self.inputs)

    def install_method(self, *, run_body: str | None = None, describe_body: str | None = None,
                       create_body: str | None = None) -> None:
        project = self.root / "method"
        shutil.copytree(ROOT / "examples/plugins/fixture_method", project)
        if run_body is not None or describe_body is not None or create_body is not None:
            source = '''import json
from importlib.resources import files
from llm4om.methods import MethodOutcome, ModelProposal
class TestMethod:
    async def run(self, problem, context, *, checkpoint=None):
RUN_BODY
class TestFactory:
    def describe(self):
DESCRIBE_BODY
    def create(self, config):
CREATE_BODY
plugin = TestFactory()
'''
            body = run_body or 'return MethodOutcome("selected", "001", None)'
            describe = describe_body or 'return json.loads(files(__package__).joinpath("manifest.json").read_text())'
            source = source.replace("RUN_BODY", indent(body, "        ")).replace("DESCRIBE_BODY", indent(describe, "        "))
            source = source.replace("CREATE_BODY", indent(create_body or "return TestMethod()", "        "))
            (project / "src/llm4om_fixture_method/__init__.py").write_text(source)
        subprocess.run(["uv", "build", "--offline", "--wheel", "--out-dir", str(self.root / "dist")],
                       cwd=project, check=True, capture_output=True, text=True)
        wheel = next((self.root / "dist").glob("*.whl"))
        subprocess.run(["uv", "pip", "install", "--no-deps", "--target", str(self.packages), str(wheel)],
                       check=True, capture_output=True, text=True)

    def configured_run(self) -> tuple[subprocess.CompletedProcess[str], Path, dict]:
        import yaml
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["method"] = {"plugin_id": "llm4om.examples.objective_offset", "config": {"objective_offset": 7}}
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(self.inputs / "solve.yaml"),
                          "--output", str(self.root / "runs"))
        self.assertTrue(result.stdout, result.stderr[:2000])
        path = Path(json.loads(result.stdout)["bundle_path"])
        return result, path, json.loads((path / "bundle.json").read_text())

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-m", "llm4om", *arguments],
                              env={**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(self.packages)))},
                              capture_output=True, text=True, cwd=self.root)

    def test_plugins_list_reports_the_actual_builtin_method_profile(self) -> None:
        result = self.cli("plugins", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)["plugins"][0]
        self.assertEqual(record["manifest"]["plugin_id"], "llm4om.methods.direct")
        self.assertEqual(record["manifest"]["capabilities"]["method_profile"], "grounded_single/0.2.0")
        self.assertEqual(record["origin"]["kind"], "builtin")

    def test_independently_installed_method_is_discovered_and_used_by_run(self) -> None:
        self.install_method()
        listing = self.cli("plugins", "list")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        external = [item for item in json.loads(listing.stdout)["plugins"]
                    if item["manifest"]["plugin_id"] == "llm4om.examples.objective_offset"][0]
        self.assertEqual(external["origin"]["distribution"], "llm4om-fixture-method")
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertAlmostEqual(solve["objective_value"], 20)
        candidate = json.loads((path / "checks/001/record.json").read_text())
        self.assertEqual(candidate["created_by"]["method_id"], "llm4om.examples.objective_offset")

    def test_installed_method_cannot_override_a_builtin_registry_key(self) -> None:
        self.install_method()
        path = self.packages / "llm4om_fixture_method/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["plugin_id"] = "llm4om.methods.direct"
        path.write_text(json.dumps(manifest))
        result = self.cli("plugins", "list")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "duplicate_plugin")

    def test_manifest_and_contract_versions_fail_before_method_execution(self) -> None:
        self.install_method()
        path = self.packages / "llm4om_fixture_method/manifest.json"
        original = json.loads(path.read_text())
        for key, value, code in [("schema_version", "99.0.0", "invalid_plugin_manifest"),
                                 ("plugin_version", "unversioned", "invalid_plugin_manifest"),
                                 ("plugin_id", "not-namespaced", "invalid_plugin_manifest"),
                                 ("contract_range", ">=0.3.0,<0.4.0", "incompatible_contract"),
                                 ("config_schema", {"$ref": "https://example.invalid/schema.json"}, "invalid_plugin_manifest"),
                                 ("config_schema", {"$ref": "#/$defs/missing"}, "invalid_plugin_manifest"),
                                 ("kind", "solver_backend", "invalid_plugin_manifest")]:
            with self.subTest(field=key):
                path.write_text(json.dumps({**original, key: value}))
                result = self.cli("plugins", "list")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)["error"]["code"], code)

    def test_unknown_method_exception_has_safe_public_diagnostics(self) -> None:
        self.install_method(run_body='print("PRIVATE-METHOD-ERROR-SENTINEL")\nraise RuntimeError("PRIVATE-METHOD-ERROR-SENTINEL")')
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "method_error")
        diagnostic = json.loads((path / bundle["error"]["details_ref"]["relative_path"]).read_text())
        self.assertTrue(diagnostic["frames"])
        self.assertNotIn("PRIVATE-METHOD-ERROR-SENTINEL", result.stderr + result.stdout)
        for file in path.rglob("*"):
            if file.is_file():
                self.assertNotIn(b"PRIVATE-METHOD-ERROR-SENTINEL", file.read_bytes())

    def test_installed_method_exit_does_not_terminate_the_run_process(self) -> None:
        self.install_method(run_body='raise SystemExit("PRIVATE-METHOD-ERROR-SENTINEL")')
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "method_error")
        self.assertNotIn("PRIVATE-METHOD-ERROR-SENTINEL", result.stdout + result.stderr)

    def test_method_calls_cannot_bypass_the_shared_mock_budget(self) -> None:
        self.install_method(run_body='''await context.llm.complete({"messages": [{"role": "user", "content": "first"}]})
await context.llm.complete({"messages": [{"role": "user", "content": "second"}]})
raise RuntimeError("Budget was not enforced.")''')
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "budget_exhausted")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["llm_attempts"], 1)
        self.assertEqual(ledger["solver_calls"], 0)

    def test_method_output_cannot_change_the_public_problem_binding(self) -> None:
        self.install_method(run_body='''reply = await context.llm.complete({"messages": [{"role": "user", "content": "fixture"}]})
payload = json.loads(reply.text)
payload["structured_ir"]["problem_id"] = "another-problem"
return MethodOutcome("selected", "001", ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"]))''')
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "artifact_problem_mismatch")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 0)

    def test_doctor_reports_the_compatible_path_without_creating_a_run(self) -> None:
        result = self.cli("doctor", "--config", str(self.inputs / "solve.yaml"))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["preflight_ok"])
        self.assertEqual(report["execution_plan"]["mode"], "trusted_local")
        self.assertEqual(report["execution_plan"]["solver_id"], "llm4om.solvers.highs")
        self.assertEqual(report["connectivity_checks"]["status"], "not_requested")
        self.assertFalse((self.root / "runs").exists())

    def test_doctor_and_run_reject_unknown_or_incompatible_method_capabilities(self) -> None:
        self.install_method()
        path = self.packages / "llm4om_fixture_method/manifest.json"
        original = json.loads(path.read_text())
        for field, value in [("code_representations", ["native_code"]), ("model_backends", None),
                             ("problem_types", []), ("llm_features", ["tools"]), ("oracle_requirements", ["reference_objective"])]:
            with self.subTest(capability=field):
                manifest = json.loads(json.dumps(original))
                if value is None:
                    del manifest["capabilities"][field]
                else:
                    manifest["capabilities"][field] = value
                path.write_text(json.dumps(manifest))
                result, run_path, bundle = self.configured_run()
                self.assertEqual(result.returncode, 1)
                self.assertEqual(bundle["error"]["code"], "capability_mismatch")
                self.assertEqual(json.loads((run_path / "budget-ledger.json").read_text())["llm_attempts"], 0)
                report = self.cli("doctor", "--config", str(self.inputs / "solve.yaml"))
                self.assertEqual(report.returncode, 1)
                self.assertEqual(json.loads(report.stdout)["error"]["code"], "capability_mismatch")

    def test_doctor_reports_missing_dependencies_and_zero_budget_before_calls(self) -> None:
        import yaml
        self.install_method()
        manifest_path = self.packages / "llm4om_fixture_method/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["dependencies"]["python"] = ["llm4om-absent-test-dependency"]
        manifest_path.write_text(json.dumps(manifest))
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "dependency_missing")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)
        report = self.cli("doctor", "--config", str(self.inputs / "solve.yaml"))
        self.assertEqual(json.loads(report.stdout)["error"]["code"], "dependency_missing")
        manifest["dependencies"]["python"] = []
        manifest_path.write_text(json.dumps(manifest))
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["budget"]["max_solver_calls"] = 0
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        report = self.cli("doctor", "--config", str(self.inputs / "solve.yaml"))
        self.assertEqual(report.returncode, 1)
        self.assertEqual(json.loads(report.stdout)["error"]["code"], "budget_exhausted")

    def test_malformed_method_outcome_still_saves_a_failed_bundle(self) -> None:
        self.install_method(run_body='return MethodOutcome("selected", "001", {})')
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "invalid_method_outcome")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 0)

    def test_method_cannot_request_undeclared_provider_features(self) -> None:
        self.install_method(run_body='await context.llm.complete({"tools": [], "messages": [{"role": "user", "content": "tools"}]})')
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "capability_mismatch")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)

    def test_sync_sdk_runs_an_async_method_inside_an_existing_event_loop(self) -> None:
        script = '''import asyncio, json, sys
from pathlib import Path
from llm4om import run_problem
async def main():
    result = run_problem(Path(sys.argv[1]), Path(sys.argv[2]), output_root=Path(sys.argv[3]))
    print(json.dumps({"status": result.status}))
asyncio.run(main())
'''
        result = subprocess.run([sys.executable, "-c", script, str(self.inputs / "problem.json"),
                                 str(self.inputs / "solve.yaml"), str(self.root / "runs")],
                                 env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "completed")

    def test_doctor_rejects_yaml_values_that_are_not_json_configuration(self) -> None:
        self.install_method()
        manifest_path = self.packages / "llm4om_fixture_method/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["config_schema"]["additionalProperties"] = True
        manifest_path.write_text(json.dumps(manifest))
        self.configured_run()
        path = self.inputs / "solve.yaml"
        path.write_text(path.read_text().replace('  config:\n    objective_offset: 7', '  config:\n    objective_offset: 7\n    date: 2026-10-09'))
        result = self.cli("doctor", "--config", str(path))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_config")

    def test_requested_resources_match_a_subset_of_method_capabilities(self) -> None:
        self.install_method()
        path = self.packages / "llm4om_fixture_method/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["capabilities"]["solvers"].append("llm4om.solvers.gurobi")
        manifest["capabilities"]["execution_modes"].append("container")
        path.write_text(json.dumps(manifest))
        result, run_path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 0)
        plan = json.loads((run_path / bundle["admission_plan_ref"]["relative_path"]).read_text())
        self.assertEqual(plan["solver_id"], "llm4om.solvers.highs")
        report = self.cli("doctor", "--config", str(self.inputs / "solve.yaml"))
        self.assertTrue(json.loads(report.stdout)["preflight_ok"])

    def test_recursive_schema_failure_is_a_safe_admission_error(self) -> None:
        self.install_method()
        path = self.packages / "llm4om_fixture_method/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["config_schema"] = {"$ref": "#"}
        path.write_text(json.dumps(manifest))
        result, run_path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "invalid_plugin_manifest")
        self.assertEqual(json.loads((run_path / "budget-ledger.json").read_text())["llm_attempts"], 0)
        report = self.cli("doctor", "--config", str(self.inputs / "solve.yaml"))
        self.assertEqual(report.returncode, 1)
        self.assertEqual(json.loads(report.stdout)["error"]["code"], "invalid_plugin_manifest")

    def test_rejected_admission_preserves_the_requested_method_configuration(self) -> None:
        self.install_method()
        path = self.packages / "llm4om_fixture_method/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["capabilities"]["solvers"] = []
        path.write_text(json.dumps(manifest))
        result, run_path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        request = json.loads((run_path / bundle["requested_config_ref"]["relative_path"]).read_text())
        self.assertEqual(request["method"]["plugin_id"], "llm4om.examples.objective_offset")
        self.assertEqual(request["method"]["config"], {"objective_offset": 7})
        self.assertEqual(json.loads((run_path / "budget-ledger.json").read_text())["llm_attempts"], 0)

    def test_factory_missing_dependency_is_classified_before_method_calls(self) -> None:
        self.install_method(create_body='raise ModuleNotFoundError("PRIVATE-FACTORY-SENTINEL")')
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(bundle["error"]["code"], "dependency_missing")
        self.assertEqual(bundle["error"]["stage"], "admission")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)
        self.assertNotIn("PRIVATE-FACTORY-SENTINEL", (path / "diagnostics/plugin-error.json").read_text())

    def test_describe_failures_keep_safe_diagnostics_and_entry_point(self) -> None:
        self.install_method(describe_body='raise RuntimeError("PRIVATE-DESCRIBE-SENTINEL")')
        result, path, bundle = self.configured_run()
        self.assertEqual(bundle["error"]["code"], "invalid_plugin_manifest")
        diagnostic = json.loads((path / bundle["error"]["details_ref"]["relative_path"]).read_text())
        self.assertEqual(diagnostic["exception_type"], "RuntimeError")
        self.assertEqual(diagnostic["entry_point"], "fixture_method")
        report = self.cli("doctor", "--config", str(self.inputs / "solve.yaml"))
        self.assertEqual(json.loads(report.stdout)["error"]["details"]["exception_type"], "RuntimeError")
        self.assertNotIn("PRIVATE-DESCRIBE-SENTINEL", result.stdout + result.stderr + report.stdout)
        listing = self.cli("plugins", "list")
        self.assertEqual(json.loads(listing.stdout)["error"]["details"]["entry_point"], "fixture_method")

    def test_cancelled_method_without_internal_checkpoint_refuses_resume(self) -> None:
        import time
        import yaml
        self.install_method(run_body='import asyncio, os\nfrom pathlib import Path\nfrom llm4om.methods import DirectMethod\nmarker = Path(os.environ["FIXTURE_ENTERED"])\nif not marker.exists():\n    marker.write_text("method entered")\n    await asyncio.sleep(30)\nfrom dataclasses import replace\nreturn await DirectMethod().run(problem, replace(context, save_checkpoint=None))')
        marker = self.root / "method-entered"
        os.environ["FIXTURE_ENTERED"] = str(marker)
        self.addCleanup(os.environ.pop, "FIXTURE_ENTERED", None)
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["method"] = {"plugin_id": "llm4om.examples.objective_offset", "config": {"objective_offset": 7}}
        config = self.inputs / "plugin.yaml"
        config.write_text(yaml.safe_dump(settings))
        output = self.root / "runs"
        process = subprocess.Popen([sys.executable, "-m", "llm4om", "run", "--problem", str(self.inputs / "problem.json"),
            "--config", str(config), "--output", str(output)], cwd=self.root,
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(self.packages)))},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 6
            path = None
            while time.monotonic() < deadline:
                paths = [item for item in output.iterdir() if len(item.name) == 32] if output.exists() else []
                if paths and marker.exists():
                    path = paths[0]
                    break
                time.sleep(0.02)
            self.assertIsNotNone(path)
            cancelled = self.cli("cancel", "--run-id", path.name, "--output", str(output))
            self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
            stdout, stderr = process.communicate(timeout=4)
            self.assertEqual(json.loads(stdout)["status"], "cancelled", stderr)
            history = (path / "events.jsonl").read_bytes()
            restored = self.cli("resume", "--run-id", path.name, "--output", str(output))
            self.assertEqual(restored.returncode, 1)
            self.assertEqual(json.loads(restored.stdout)["error"]["code"], "checkpoint_unsupported")
            self.assertEqual((path / "events.jsonl").read_bytes(), history)
            self.assertEqual(len(list(output.glob("*/bundle.json"))), 1)
            rerun = self.cli("resume", "--strategy", "rerun", "--run-id", path.name, "--output", str(output))
            self.assertEqual(rerun.returncode, 0, rerun.stderr + rerun.stdout)
            record = json.loads(rerun.stdout)
            self.assertEqual(record["status"], "completed")
            self.assertNotEqual(record["run_id"], path.name)
            child = Path(record["bundle_path"])
            bundle = json.loads((child / "bundle.json").read_text())
            lineage = json.loads((child / bundle["lineage_ref"]["relative_path"]).read_text())
            self.assertEqual(lineage["parent_run_id"], path.name)
            self.assertEqual(lineage["operation"], "derived_rerun")
            self.assertEqual((path / "events.jsonl").read_bytes(), history)
            self.assertEqual(json.loads((child / "budget-ledger.json").read_text())["llm_attempts"], 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
