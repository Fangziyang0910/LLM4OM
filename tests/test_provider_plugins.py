"""Installed Provider behavior through public CLI, HTTP and Solver interfaces."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import yaml


ROOT = Path(__file__).resolve().parents[1]


class ProviderPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packages = self.root / "packages"
        self.inputs = self.root / "input"
        shutil.copytree(ROOT / "examples/specs", self.inputs)

    def cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "llm4om", *arguments], cwd=self.root,
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, timeout=60)

    def install_provider(self):
        project = self.root / "provider"
        shutil.copytree(ROOT / "examples/plugins/fixture_provider", project)
        subprocess.run(["uv", "build", "--offline", "--wheel", "--out-dir", str(self.root / "dist")],
                       cwd=project, check=True, capture_output=True, text=True)
        wheel = next((self.root / "dist").glob("*.whl"))
        subprocess.run(["uv", "pip", "install", "--no-deps", "--target", str(self.packages), str(wheel)],
                       check=True, capture_output=True, text=True)

    def local_provider(self, *, custom_protocol=False):
        formulation = json.loads((self.inputs / "formulation.json").read_text())
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        compact = {"representation": formulation["representation"], "structured_ir": {
            key: ir[key] for key in ("problem_type", "variables", "objective", "constraints", "assumptions")}}
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
                self.send_response(200)
                self.end_headers()
                reply = {"id": "installed-provider-fixture", "model": "fixture-model",
                    "choices": [{"message": {"content": json.dumps(compact)}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 200, "completion_tokens": 300, "total_tokens": 500}}
                self.wfile.write(json.dumps({"result": reply} if custom_protocol else reply).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["llm"] = {"provider_plugin_id": "llm4om.examples.openai_text", "model": "fixture-model",
            "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "INSTALLED_PROVIDER_KEY", "max_retries": 0}}
        settings["budget"]["max_total_tokens"] = 30000
        (self.root / ".env").write_text("INSTALLED_PROVIDER_KEY=synthetic-installed-key\n")
        config = self.inputs / "installed.yaml"
        config.write_text(yaml.safe_dump(settings))
        return config, requests

    def run_installed(self, config):
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config),
                          "--output", str(self.root / "runs"))
        self.assertTrue(result.stdout, result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        return result, path

    def test_plugins_list_includes_common_versioned_provider_manifests(self):
        result = self.cli("plugins", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        items = json.loads(result.stdout)["plugins"]
        providers = {item["manifest"]["plugin_id"]: item for item in items
                     if item["manifest"]["kind"] == "llm_provider"}
        self.assertEqual(set(providers), {"llm4om.providers.mock", "llm4om.providers.openai_compatible",
                                          "llm4om.providers.anthropic"})
        for item in providers.values():
            manifest = item["manifest"]
            self.assertEqual(manifest["schema_version"], "0.2.0")
            self.assertEqual(manifest["capabilities"]["llm_features"], ["text"])
            self.assertIn("config_schema", manifest)
            self.assertIn("contract_range", manifest)
            self.assertEqual(item["origin"]["kind"], "builtin")

    def test_installed_provider_is_listed_preflighted_and_used_by_real_solver(self):
        self.install_provider()
        config, requests = self.local_provider()
        listing = self.cli("plugins", "list")
        self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
        provider = next(item for item in json.loads(listing.stdout)["plugins"]
                        if item["manifest"]["plugin_id"] == "llm4om.examples.openai_text")
        self.assertEqual(provider["origin"]["distribution"], "llm4om-fixture-provider")
        doctor = self.cli("doctor", "--config", str(config))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertEqual(requests, [])
        result, path = self.run_installed(config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        solve = json.loads((path / "candidates/001/solve-result.json").read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(json.loads((path / "candidates/001/solution.json").read_text())["variables"], {"qty_A": 3.0, "qty_B": 2.0})
        trace = json.loads((path / "llm-trace.json").read_text())
        self.assertEqual(trace["attempts"][0]["provider"], "llm4om.examples.openai_text")
        self.assertEqual(trace["attempts"][0]["usage"]["total_tokens"], 500)
        plan = json.loads((path / "admission-plan.json").read_text())
        self.assertEqual(plan["provider_origin"], provider["origin"])
        self.assertEqual(len(requests), 1)
        self.assertNotIn("synthetic-installed-key", "".join(p.read_text() for p in path.rglob("*") if p.is_file()))

    def alter_manifest(self, statement):
        path = self.packages / "llm4om_fixture_provider/__init__.py"
        original = (ROOT / "examples/plugins/fixture_provider/src/llm4om_fixture_provider/__init__.py").read_text()
        path.write_text(original.replace("manifest = super().describe()", "manifest = super().describe()\n        " + statement))
        shutil.rmtree(path.parent / "__pycache__", ignore_errors=True)

    def test_missing_provider_dependency_rejects_before_http(self):
        self.install_provider()
        self.alter_manifest('manifest["dependencies"]["python"] = ["llm4om-absent-provider-dependency"]')
        config, requests = self.local_provider()
        doctor = self.cli("doctor", "--config", str(config))
        self.assertEqual(doctor.returncode, 1, doctor.stdout + doctor.stderr)
        self.assertEqual(json.loads(doctor.stdout)["error"]["code"], "dependency_missing")
        result, path = self.run_installed(config)
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "dependency_missing")
        self.assertEqual(requests, [])
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["external_llm_requests"], 0)

    def test_installed_provider_resume_reuses_saved_reply_and_rejects_source_drift(self):
        self.install_provider()
        config, requests = self.local_provider()
        result, path = self.run_installed(config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        ledger = (path / "budget-ledger.json").read_bytes()
        (self.root / ".env").unlink()
        restored = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertEqual((path / "budget-ledger.json").read_bytes(), ledger)
        history = {name: (path / name).read_bytes() for name in ("events.jsonl", "bundle.json", "admission-plan.json", "budget-ledger.json", "llm-trace.json", "public-problem.json")}
        source = self.packages / "llm4om_fixture_provider/__init__.py"
        source.write_text(source.read_text() + "\n# changed trusted plugin source\n")
        drift = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(drift.returncode, 1, drift.stdout + drift.stderr)
        self.assertEqual(json.loads(drift.stdout)["error"]["code"], "checkpoint_incompatible")
        for name, raw in history.items():
            self.assertEqual((path / name).read_bytes(), raw, name)
        self.assertEqual(len(requests), 1)

    def test_separate_protocol_adapter_runs_in_owned_transport_and_recovers_its_decoder(self):
        self.install_provider()
        source = self.packages / "llm4om_fixture_provider/__init__.py"
        source.write_text(source.read_text() + '''
import json
from urllib.request import Request
class ProtocolProvider(FixtureProvider):
    endpoint_path = "/generate"
    def __init__(self, config, model, credential):
        super().__init__(config, model, credential)
        self.api_version = config["api_version"]
    def _request(self, messages):
        return Request(self.identity, json.dumps({"prompt": messages, "model": self.model}).encode(),
            {"Content-Type": "application/json", "Authorization": "Bearer " + self._credential,
             "X-Api-Version": self.api_version}, method="POST")
    @staticmethod
    def decode_reply(value):
        return OpenAICompatibleProvider.decode_reply(value["result"])
FixtureFactory.provider_type = ProtocolProvider
class ProtocolFactory(FixtureFactory):
    def describe(self):
        manifest = super().describe()
        manifest["config_schema"]["properties"]["api_version"] = {"type": "string", "minLength": 1}
        manifest["config_schema"]["required"].append("api_version")
        return manifest
plugin = ProtocolFactory()
''')
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        config, requests = self.local_provider(custom_protocol=True)
        settings = yaml.safe_load(config.read_text())
        settings["llm"]["config"]["api_version"] = "fixture-2026"
        if os.environ.get("LLM4OM_TEST_IMAGE"):
            executor = yaml.safe_load((self.inputs / "run.yaml").read_text())["executor"]
            executor["config"]["image"] = os.environ["LLM4OM_TEST_IMAGE"]
            settings["executor"] = executor
        config.write_text(yaml.safe_dump(settings))
        result, path = self.run_installed(config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(requests[0]["path"], "/v1/generate")
        self.assertIn("prompt", requests[0]["body"])
        self.assertNotIn("messages", requests[0]["body"])
        self.assertEqual(requests[0]["headers"]["X-Api-Version"], "fixture-2026")
        self.assertEqual(json.loads((path / "candidates/001/solve-result.json").read_text())["objective_value"], 13)
        (self.root / ".env").unlink()
        restored = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertEqual(len(requests), 1)

    def test_installed_provider_role_keeps_actual_route_and_package_identity(self):
        self.install_provider()
        config, requests = self.local_provider()
        settings = yaml.safe_load(config.read_text())
        role = settings["llm"]
        settings["llm"] = {**role, "provider_plugin_id": "llm4om.providers.openai_compatible", "role_models": {"formulation": role}}
        config.write_text(yaml.safe_dump(settings))
        result, path = self.run_installed(config)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = json.loads((path / "admission-plan.json").read_text())
        self.assertEqual(plan["provider_origin"], {"kind": "builtin"})
        self.assertEqual(plan["role_models"]["formulation"]["origin"]["distribution"], "llm4om-fixture-provider")
        attempt = json.loads((path / "llm-trace.json").read_text())["attempts"][0]
        self.assertEqual(attempt["provider"], "llm4om.examples.openai_text")
        self.assertEqual(attempt["role"], "formulation")
        self.assertEqual(len(requests), 1)
        source = self.packages / "llm4om_fixture_provider/__init__.py"
        source.write_text(source.read_text() + "\n# changed role implementation\n")
        restored = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(json.loads(restored.stdout)["error"]["code"], "checkpoint_incompatible")
        self.assertEqual(len(requests), 1)

    def test_provider_manifest_conflicts_and_invalid_declarations_are_safe(self):
        self.install_provider()
        config, requests = self.local_provider()
        for statement, code in [
            ('manifest["kind"] = "solver_backend"', "invalid_plugin_manifest"),
            ('manifest["schema_version"] = "99.0.0"', "invalid_plugin_manifest"),
            ('manifest["plugin_version"] = "unversioned"', "invalid_plugin_manifest"),
            ('manifest["contract_range"] = ">=0.3.0,<0.4.0"', "incompatible_contract"),
            ('manifest["capabilities"]["provider_profile"] = "anything"', "invalid_plugin_manifest"),
            ('manifest["config_schema"] = {"$ref": "https://example.invalid/schema"}', "invalid_plugin_manifest"),
            ('raise RuntimeError("PRIVATE-PROVIDER-ERROR")', "invalid_plugin_manifest"),
        ]:
            with self.subTest(statement=statement):
                self.alter_manifest(statement)
                result = self.cli("plugins", "list")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["error"]["code"], code)
                self.assertNotIn("PRIVATE-PROVIDER-ERROR", result.stdout + result.stderr)
        self.alter_manifest('manifest["capabilities"]["llm_features"] = []')
        doctor = self.cli("doctor", "--config", str(config))
        self.assertEqual(json.loads(doctor.stdout)["error"]["code"], "capability_mismatch")
        source = self.packages / "llm4om_fixture_provider/__init__.py"
        original = (ROOT / "examples/plugins/fixture_provider/src/llm4om_fixture_provider/__init__.py").read_text()
        source.write_text(original.replace('plugin_id = "llm4om.examples.openai_text"', 'plugin_id = "llm4om.providers.openai_compatible"'))
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        listing = self.cli("plugins", "list")
        self.assertEqual(json.loads(listing.stdout)["error"]["code"], "duplicate_plugin")
        self.assertEqual(requests, [])

    def test_provider_constructor_failure_has_safe_admission_evidence(self):
        self.install_provider()
        config, requests = self.local_provider()
        source = self.packages / "llm4om_fixture_provider/__init__.py"
        source.write_text(source.read_text().replace("    provider_type = FixtureProvider", '''    provider_type = FixtureProvider
    def create(self, *args, **kwargs):
        print("PRIVATE-CONSTRUCTOR-ERROR")
        raise RuntimeError("PRIVATE-CONSTRUCTOR-ERROR")'''))
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        result, path = self.run_installed(config)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "invalid_config")
        self.assertNotIn("PRIVATE-CONSTRUCTOR-ERROR", result.stdout + result.stderr)
        self.assertEqual(requests, [])

    def test_installed_decoder_failure_retains_unknown_usage_without_private_diagnostics(self):
        self.install_provider()
        config, requests = self.local_provider()
        source = self.packages / "llm4om_fixture_provider/__init__.py"
        source.write_text(source.read_text().replace('    plugin_id = "llm4om.examples.openai_text"', '''    plugin_id = "llm4om.examples.openai_text"
    @staticmethod
    def decode_reply(value):
        raise RuntimeError("PRIVATE-DECODER-ERROR")'''))
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        result, path = self.run_installed(config)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "invalid_provider_response")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["external_llm_requests"], 1)
        self.assertGreater(ledger["reserved_tokens"], 0)
        self.assertIsNone(ledger["total_tokens"])
        self.assertEqual(len(requests), 1)
        self.assertNotIn("PRIVATE-DECODER-ERROR", result.stdout + result.stderr)

    def test_invalid_normalized_provider_reply_is_rejected_at_the_transport_seam(self):
        self.install_provider()
        config, requests = self.local_provider()
        source = self.packages / "llm4om_fixture_provider/__init__.py"
        source.write_text(source.read_text().replace('    plugin_id = "llm4om.examples.openai_text"', '''    plugin_id = "llm4om.examples.openai_text"
    @staticmethod
    def decode_reply(value):
        reply = OpenAICompatibleProvider.decode_reply(value)
        reply["usage"]["total_tokens"] = True
        return reply'''))
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        result, path = self.run_installed(config)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "invalid_provider_response")
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["solver_calls"], 0)
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
