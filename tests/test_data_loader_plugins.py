"""Public loading, actual LLM exposure and original-data solve through CLI."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DataLoaderPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "input"
        self.packages = self.root / "packages"
        shutil.copytree(ROOT / "examples/specs", self.inputs)

    def cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "llm4om", *arguments], cwd=self.root,
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, timeout=60)

    def local_provider(self, *, factory=False):
        formulation = json.loads((self.inputs / "formulation.json").read_text())
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        compact = {"representation": formulation["representation"], "structured_ir": {
            key: ir[key] for key in ("problem_type", "variables", "objective", "constraints", "assumptions")}}
        if factory:
            compact = {"representation": formulation["representation"], "python_factory": (ROOT / "examples/factories/production.py").read_text()}
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"id": "public-data-view-fixture", "model": "fixture-model",
                    "choices": [{"message": {"content": json.dumps(compact)}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 200, "completion_tokens": 300, "total_tokens": 500}}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "fixture-model",
            "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "DATA_VIEW_TEST_KEY", "max_retries": 0}}
        settings["budget"]["max_total_tokens"] = 30000
        (self.root / ".env").write_text("DATA_VIEW_TEST_KEY=synthetic-data-view-key\n")
        return settings, requests

    def run_config(self, settings):
        config = self.inputs / "data-view.yaml"
        config.write_text(yaml.safe_dump(settings))
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config),
                          "--output", str(self.root / "runs"))
        self.assertTrue(result.stdout, result.stderr)
        return result, Path(json.loads(result.stdout)["bundle_path"])

    def install_plugin(self, fixture):
        project = self.root / fixture
        wheel_dir = project / "dist"
        shutil.copytree(ROOT / "examples/plugins" / fixture, project)
        subprocess.run(["uv", "build", "--offline", "--wheel", "--out-dir", str(wheel_dir)],
                       cwd=project, check=True, capture_output=True, text=True)
        wheel = next(wheel_dir.glob("*.whl"))
        subprocess.run(["uv", "pip", "install", "--no-deps", "--target", str(self.packages), str(wheel)],
                       check=True, capture_output=True, text=True)

    def test_bounded_csv_is_the_actual_llm_view_and_original_data_still_solves(self):
        settings, requests = self.local_provider()
        settings["data_loader"] = {"plugin_id": "llm4om.data_loaders.public", "config": {}}
        settings["data_view"] = {"max_rows": 1,
            "columns": ["product_id", "profit", "resource_id", "capacity"], "max_bytes": 256}
        result, path = self.run_config(settings)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(requests), 1)
        payload = json.loads(requests[0]["messages"][-1]["content"])
        self.assertEqual(payload["data"]["products"], "product_id,profit\r\nA,3\r\n")
        self.assertFalse(payload["data_views"]["products"]["complete"])
        self.assertEqual(payload["data_views"]["products"]["total_rows"], 2)
        self.assertEqual(payload["data_views"]["products"]["columns"], ["product_id", "profit"])
        original = (self.inputs / "data/products.csv").read_bytes()
        self.assertEqual((path / "data/0.csv").read_bytes(), original)
        views = json.loads((path / "data-views.json").read_text())["views"]
        self.assertEqual(views["products"]["source_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual((path / views["products"]["content_ref"]["relative_path"]).read_bytes().decode(), payload["data"]["products"])
        solve = json.loads((path / "candidates/001/solve-result.json").read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(json.loads((path / "candidates/001/solution.json").read_text())["variables"], {"qty_A": 3.0, "qty_B": 2.0})
        plan = json.loads((path / "admission-plan.json").read_text())
        self.assertEqual(plan["data_loader"]["manifest"]["kind"], "data_loader")
        trace = json.loads((path / "llm-trace.json").read_text())
        self.assertEqual(json.loads((path / trace["data_views_ref"]["relative_path"]).read_text())["views"], views)

    def test_csv_type_failure_identifies_row_and_column_before_any_model_request(self):
        settings, requests = self.local_provider()
        source = self.inputs / "data/products.csv"
        source.write_text("product_id,profit,cutting,finishing\nA,NaN,2,1\nB,2,1,2\n")
        problem = json.loads((self.inputs / "problem.json").read_text())
        problem["data_refs"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        (self.inputs / "problem.json").write_text(json.dumps(problem))
        result, path = self.run_config(settings)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(requests, [])

        bundle = json.loads((path / "bundle.json").read_text())
        self.assertEqual(bundle["error"]["code"], "invalid_data")
        diagnostic = json.loads((path / bundle["error"]["details_ref"]["relative_path"]).read_text())
        self.assertEqual(diagnostic["row"], 2)
        self.assertEqual(diagnostic["column"], "profit")
        self.assertEqual(diagnostic["reason"], "finite_numeric_type")

    def test_oversized_public_data_rejects_before_loading_or_generation(self):
        settings, requests = self.local_provider()
        source = self.inputs / "data/products.csv"
        source.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
        result, path = self.run_config(settings)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(requests, [])
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "invalid_data")

    def test_installed_loader_changes_actual_column_order_and_freezes_its_identity(self):
        self.install_plugin("fixture_data_loader")
        settings, requests = self.local_provider()
        settings["data_loader"] = {"plugin_id": "llm4om.examples.reversed_columns", "config": {"reverse_columns": True}}
        result, path = self.run_config(settings)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(requests[0]["messages"][-1]["content"])
        self.assertEqual(payload["data"]["products"], "finishing,cutting,profit,product_id\r\n1,2,3,A\r\n2,1,2,B\r\n")
        self.assertFalse(payload["data_views"]["products"]["complete"])
        plan = json.loads((path / "admission-plan.json").read_text())
        self.assertEqual(plan["data_loader"]["origin"]["distribution"], "llm4om-fixture-data-loader")
        self.assertEqual(plan["data_loader"]["config"], {"reverse_columns": True})
        ledger = (path / "budget-ledger.json").read_bytes()
        resumed = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertEqual((path / "budget-ledger.json").read_bytes(), ledger)
        self.assertEqual(len(requests), 1)
        module = self.packages / "llm4om_fixture_data_loader/__init__.py"
        module.write_text(module.read_text() + "\n# changed installed loader bytes\n")
        rejected = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(json.loads(rejected.stdout)["error"]["code"], "checkpoint_incompatible")
        self.assertEqual((path / "budget-ledger.json").read_bytes(), ledger)

    def test_loader_cannot_misreport_exposed_rows_or_columns(self):
        self.install_plugin("fixture_data_loader")
        module = self.packages / "llm4om_fixture_data_loader/__init__.py"
        module.write_text(module.read_text().replace("columns=columns, kind=\"rows\", complete=False",
            "columns=('profit',), rows=0, kind=\"rows\", complete=False"))
        settings, requests = self.local_provider()
        settings["data_loader"] = {"plugin_id": "llm4om.examples.reversed_columns", "config": {"reverse_columns": True}}
        result, path = self.run_config(settings)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(requests, [])
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "invalid_data_view")

    def test_large_json_exposes_only_a_declared_schema_summary(self):
        settings, requests = self.local_provider()
        source = self.inputs / "data/parameters.json"
        source.write_text(json.dumps({"values": list(range(1000)), "unit": "public-only"}))
        problem = json.loads((self.inputs / "problem.json").read_text())
        problem["schema_version"] = "0.3.0"
        problem["data_refs"].append({"data_id": "parameters", "path": "data/parameters.json", "format": "json",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "schema": {"type": "object"}})
        (self.inputs / "problem.json").write_text(json.dumps(problem))
        settings["data_view"] = {"max_bytes": 256}
        result, path = self.run_config(settings)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(requests[0]["messages"][-1]["content"])
        self.assertEqual(json.loads(payload["data"]["parameters"]), {"format": "json", "total_keys": 2, "keys": ["values", "unit"]})
        self.assertEqual(payload["data_views"]["parameters"]["kind"], "summary")
        self.assertFalse(payload["data_views"]["parameters"]["complete"])
        self.assertEqual((path / "data/2.json").read_bytes(), source.read_bytes())

    def test_method_requiring_full_data_rejects_an_incomplete_view_before_generation(self):
        self.install_plugin("fixture_method")
        settings, requests = self.local_provider()
        settings["method"] = {"plugin_id": "llm4om.examples.objective_offset", "config": {"objective_offset": 7}}
        settings["data_view"] = {"max_rows": 1}
        result, path = self.run_config(settings)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(requests, [])
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "capability_mismatch")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["llm_attempts"], ledger["solver_calls"]), (0, 0))

    def test_unknown_loader_and_invalid_limits_reject_before_generation(self):
        settings, requests = self.local_provider()
        for selection, exposure, code in (
                ({"plugin_id": "llm4om.examples.missing"}, {}, "unknown_plugin"),
                ({"plugin_id": "llm4om.data_loaders.public", "config": {"arbitrary_path": "/private"}}, {}, "invalid_config"),
                ({"plugin_id": "llm4om.data_loaders.public"}, {"max_rows": -1}, "invalid_config"),
                ({"plugin_id": "llm4om.data_loaders.public"}, {"mode": "full", "max_rows": 1}, "data_view_limit")):
            with self.subTest(code=code, exposure=exposure):
                settings.update(data_loader=selection, data_view=exposure)
                result, path = self.run_config(settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], code)
        self.assertEqual(requests, [])

    def test_csv_keys_and_nullability_and_json_private_nonfinite_duplicate_fields_remain_strict(self):
        settings, requests = self.local_provider()
        original = json.loads((self.inputs / "problem.json").read_text())
        for raw, reason in (("product_id,profit,cutting,finishing\nA,,2,1\n", "nullability"),
                            ("product_id,profit,cutting,finishing\nA,3,2,1\nA,2,1,2\n", "duplicate_key")):
            with self.subTest(reason=reason):
                source = self.inputs / "data/products.csv"
                source.write_text(raw)
                problem = json.loads(json.dumps(original))
                problem["data_refs"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
                (self.inputs / "problem.json").write_text(json.dumps(problem))
                result, path = self.run_config(settings)
                self.assertNotEqual(result.returncode, 0)
                bundle = json.loads((path / "bundle.json").read_text())
                self.assertEqual(bundle["error"]["code"], "invalid_data")
                diagnostic = json.loads((path / bundle["error"]["details_ref"]["relative_path"]).read_text())
                self.assertEqual(diagnostic["reason"], reason)
        for raw, code in ((b'{"a":1,"a":2}', "invalid_json"), (b'{"a":NaN}', "invalid_json"),
                          (b'{"oracle":{"reference_objective":13}}', "private_input")):
            with self.subTest(code=code):
                source = self.inputs / "data/parameters.json"
                source.write_bytes(raw)
                problem = {**original, "schema_version": "0.3.0", "data_refs": [{"data_id": "parameters",
                    "path": "data/parameters.json", "format": "json", "sha256": hashlib.sha256(raw).hexdigest(),
                    "schema": {"type": "object"}}]}
                (self.inputs / "problem.json").write_text(json.dumps(problem))
                result, path = self.run_config(settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], code)
        self.assertEqual(requests, [])

    def test_loader_exception_private_text_and_details_do_not_enter_public_exports(self):
        self.install_plugin("fixture_data_loader")
        module = self.packages / "llm4om_fixture_data_loader/__init__.py"
        source = module.read_text().replace("        view = PublicDataLoader().load(ref, schema, context)",
            '        from llm4om.contracts import RunError\n        raise RunError("private-failure", "validation", "PRIVATE-LOADER-SENTINEL", details={"secret": "PRIVATE-LOADER-SENTINEL"})')
        module.write_text(source)
        settings, requests = self.local_provider()
        settings["data_loader"] = {"plugin_id": "llm4om.examples.reversed_columns", "config": {"reverse_columns": True}}
        result, path = self.run_config(settings)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(requests, [])
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "invalid_data_view")
        for file in path.rglob("*"):
            if file.is_file():
                self.assertNotIn(b"PRIVATE-LOADER-SENTINEL", file.read_bytes())

    def test_parameterized_worker_reads_original_csv_while_llm_receives_only_the_view(self):
        self.install_plugin("fixture_data_loader")
        settings, requests = self.local_provider(factory=True)
        settings["method"]["config"]["output_mode"] = "python_factory"
        settings["executor"] = yaml.safe_load((self.inputs / "run.yaml").read_text())["executor"]
        settings["data_loader"] = {"plugin_id": "llm4om.examples.reversed_columns", "config": {"reverse_columns": True}}
        settings["data_view"] = {"max_rows": 1, "columns": ["product_id", "profit", "resource_id", "capacity"]}
        result, path = self.run_config(settings)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(requests[0]["messages"][-1]["content"])
        self.assertEqual(payload["data"]["products"], "profit,product_id\r\n3,A\r\n")
        bundle = json.loads((path / "bundle.json").read_text())
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(solve["evidence_origin"], "trusted_container_worker")
        variables = json.loads((path / solve["solution_ref"]["relative_path"]).read_text())["variables"]
        self.assertEqual(variables, {"qty_A": 3.0, "qty_B": 2.0})
        from llm4om.checkers import ProductionChecker
        raw = {"products": (self.inputs / "data/products.csv").read_bytes(),
               "capacities": (self.inputs / "data/capacities.csv").read_bytes()}
        checker = ProductionChecker().check(json.loads((self.inputs / "problem.json").read_text()), raw,
                                            {"A": variables["qty_A"], "B": variables["qty_B"]})
        self.assertEqual(checker["independent_feasibility"]["status"], "pass")
        self.assertEqual(checker["original_objective"], 13)

    def test_public_sdk_loader_rejects_a_different_declared_original_hash(self):
        from llm4om import resolve_data_loader
        from llm4om.contracts import RunError
        ref = json.loads((self.inputs / "problem.json").read_text())["data_refs"][0]
        raw = (self.inputs / ref["path"]).read_bytes()
        ref["sha256"] = "0" * 64
        with self.assertRaises(RunError) as error:
            resolve_data_loader({}).load(raw, ref)
        self.assertEqual(error.exception.code, "data_hash_mismatch")

    def test_public_sdk_loader_rejects_invalid_exposure_configuration(self):
        from llm4om import resolve_data_loader
        from llm4om.contracts import RunError
        with self.assertRaises(RunError) as error:
            resolve_data_loader({"data_view": {"max_rows": -1}})
        self.assertEqual(error.exception.code, "invalid_config")

    def test_byte_bounded_csv_keeps_whole_original_rows_and_rejects_excessive_header(self):
        from llm4om import resolve_data_loader
        from llm4om.contracts import RunError
        ref = json.loads((self.inputs / "problem.json").read_text())["data_refs"][0]
        raw = (self.inputs / ref["path"]).read_bytes()
        view = resolve_data_loader({"data_view": {"max_bytes": 50}}).load(raw, ref)
        self.assertEqual(view.content, b"product_id,profit,cutting,finishing\r\nA,3,2,1\r\n")
        self.assertEqual((view.total_rows, view.rows, view.complete), (2, 1, False))
        with self.assertRaises(RunError) as error:
            resolve_data_loader({"data_view": {"max_bytes": 1}}).load(raw, ref)
        self.assertEqual(error.exception.code, "data_view_limit")
        empty = resolve_data_loader({"data_view": {"columns": []}}).load(raw, ref)
        self.assertEqual(json.loads(empty.content), {"format": "csv", "total_rows": 2, "columns": []})
