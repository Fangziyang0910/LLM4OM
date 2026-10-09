"""Parameterized factories through the public CLI/SDK and real Worker."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

from llm4om import run_problem

ROOT = Path(__file__).resolve().parents[1]


class FactoryRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs"
        shutil.copytree(ROOT / "examples/specs", self.inputs)
        self.config = yaml.safe_load((self.inputs / "run.yaml").read_text())
        self.config["method"]["config"]["output_mode"] = "python_factory"

    def save_config(self):
        path = self.inputs / "factory.yaml"
        path.write_text(yaml.safe_dump(self.config))
        return path

    def test_factory_rejects_local_and_offline_before_generation(self):
        self.config["executor"] = {"plugin_id": "llm4om.executors.trusted_local", "config": {}}
        for offline in (False, True):
            with self.subTest(offline=offline):
                result = run_problem(self.inputs / "problem.json", self.save_config(), offline=offline,
                                     output_root=self.root / "runs")
                bundle = json.loads((result.bundle_path / "bundle.json").read_text())
                self.assertEqual(bundle["error"]["code"], "capability_mismatch")
                ledger = json.loads((result.bundle_path / "budget-ledger.json").read_text())
                self.assertEqual(ledger["llm_attempts"], 0)

    def start_provider(self, source=None):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        self.source = source or (ROOT / "examples/factories/production.py").read_text()
        representation = json.loads((ROOT / "examples/specs/formulation.json").read_text())["representation"]
        representation["sets"] = [
            {"id": "products", "source": {"data_id": "products", "column": "product_id"}},
            {"id": "resources", "source": {"data_id": "capacities", "column": "resource_id"}}]
        self.reply = {"representation": representation, "python_factory": self.source}
        self.requests = []
        test = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                test.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": json.dumps(test.reply)},
                    "finish_reason": "stop"}], "usage": {"prompt_tokens": 300, "completion_tokens": 600,
                    "total_tokens": 900}}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.config["budget"]["max_total_tokens"] = 30000
        self.config["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "local-fixture",
            "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "S02B_FIXTURE_KEY",
                       "max_output_tokens": 4096, "max_retries": 0}}

    def run_cli(self):
        import os
        config = self.save_config()
        completed = subprocess.run([sys.executable, "-m", "llm4om", "run", "--problem",
            str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs")],
            cwd=self.root, env={**os.environ, "S02B_FIXTURE_KEY": "synthetic-factory-key",
                               "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, timeout=90)
        self.assertTrue(completed.stdout, completed.stderr)
        path = Path(json.loads(completed.stdout)["bundle_path"])
        return path, json.loads((path / "bundle.json").read_text())

    def test_direct_factory_rebinds_public_csv_and_preserves_source_formulation(self):
        self.start_provider()
        self.config.pop("compiler")
        hashes, bindings = [], []
        for revision, expected in [("1", {"qty_A": 3, "qty_B": 2}), ("2", {"qty_A": 2, "qty_B": 3})]:
            if revision == "2":
                data = self.inputs / "data/products.csv"
                data.write_bytes(b"product_id,profit,cutting,finishing\nA,2,2,1\nB,3,1,2\n")
                problem = json.loads((self.inputs / "problem.json").read_text())
                problem["revision"] = revision
                problem["data_refs"][0]["sha256"] = hashlib.sha256(data.read_bytes()).hexdigest()
                (self.inputs / "problem.json").write_text(json.dumps(problem))
            path, bundle = self.run_cli()
            self.assertEqual(bundle["status"], "completed", bundle["error"])
            for ref in bundle["artifacts"]:
                raw = (path / ref["relative_path"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), ref["sha256"])
            solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
            self.assertEqual(solve["termination"], "optimal")
            self.assertEqual(solve["objective_value"], 13)
            solution = json.loads((path / solve["solution_ref"]["relative_path"]).read_text())
            self.assertEqual(solution["variables"], expected)
            artifact = json.loads((path / bundle["model_artifact_ref"]["relative_path"]).read_text())
            code = json.loads((path / artifact["code_ref"]["relative_path"]).read_text())
            self.assertEqual(code["provenance"]["origin"], "method_generated")
            self.assertEqual(code["source_formulation_ref"], artifact["formulation_ref"])
            self.assertEqual((path / code["representation_ref"]["relative_path"]).read_text(), self.source)
            hashes.append(code["representation_ref"]["sha256"])
            bindings.append(code["data_bindings"])
            formulation = json.loads((path / artifact["formulation_ref"]["relative_path"]).read_text())
            self.assertEqual(formulation["problem_revision"], revision)
            self.assertEqual(formulation["representation"], self.reply["representation"])
            self.assertIsNone(formulation["structured_ir_ref"])
            view = json.loads((path / artifact["optional_views"][0]["artifact_ref"]["relative_path"]).read_text())
            self.assertEqual(view["provenance"]["origin"], "factory_exported_instance")
            self.assertEqual(view["problem_revision"], revision)
            evaluation = json.loads((path / "evaluation.json").read_text())
            self.assertEqual(evaluation["code_validation"]["level"], "factory_contract")
            self.assertEqual(evaluation["semantic_validation"]["status"], "not_available")
            all_public = b"\n".join(file.read_bytes() for file in path.rglob("*") if file.is_file())
            self.assertNotIn(b"synthetic-factory-key", all_public)
        self.assertEqual(hashes[0], hashes[1])
        self.assertNotEqual(bindings[0], bindings[1])
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn("synthetic-factory-key", json.dumps(self.requests))

    def test_factory_cannot_forge_solver_evidence_by_printing_or_monkeypatching(self):
        source = (ROOT / "examples/factories/production.py").read_text()
        source += '\nimport llm4om.highs as solver\nsolver.solve_highs = lambda *args: {"termination": "optimal", "objective_value": 999999}\nprint("FORGED-SOLVE-RESULT objective=999999")\n'
        self.start_provider(source)
        path, bundle = self.run_cli()
        self.assertEqual(bundle["status"], "completed", bundle["error"])
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(solve["termination"], "optimal")
        execution = json.loads((path / bundle["execution_result_ref"]["relative_path"]).read_text())
        self.assertIn("FORGED-SOLVE-RESULT", (path / execution["stderr_ref"]["relative_path"]).read_text())

    def test_factory_modifying_installed_solver_code_is_rejected_with_diagnostics(self):
        source = (ROOT / "examples/factories/production.py").read_text()
        source += '\nimport llm4om.highs as solver\nfrom pathlib import Path\nPath(solver.__file__).write_text("print(999999)")\n'
        self.start_provider(source)
        path, bundle = self.run_cli()
        self.assertEqual(bundle["error"]["code"], "factory_exception")
        self.assertIn("OSError", bundle["error"]["message"])
        self.assertIsNone(bundle["solve_result_ref"])
        self.assertEqual((path / "candidates/001/model.py").read_text(), source)
        self.assertIsNotNone(bundle["model_artifact_ref"])
        self.assertEqual(bundle["stages"]["formulation"]["status"], "available")
        self.assertEqual(bundle["stages"]["code"]["status"], "available")

    def install_factory_method(self):
        project = self.root / "method"
        shutil.copytree(ROOT / "examples/plugins/fixture_method", project)
        package = project / "src/llm4om_fixture_method"
        manifest = json.loads((package / "manifest.json").read_text())
        manifest["plugin_id"] = "test.methods.parameterized"
        manifest["capabilities"]["method_profile"] = "factory_single_candidate/0.1.0"
        manifest["capabilities"]["execution_modes"] = ["container"]
        manifest["config_schema"] = {"type": "object", "properties": {"binding": {"enum": ["current", "stale", "bad_hash", "future"]}},
                                     "required": ["binding"], "additionalProperties": False}
        (package / "manifest.json").write_text(json.dumps(manifest))
        (package / "production.txt").write_text((ROOT / "examples/factories/production.py").read_text())
        (package / "formulation.json").write_bytes((ROOT / "examples/specs/formulation.json").read_bytes())
        (project / "pyproject.toml").write_text((project / "pyproject.toml").read_text().replace('["manifest.json"]', '["manifest.json", "production.txt", "formulation.json"]'))
        (package / "__init__.py").write_text('''import hashlib
import json
from importlib.resources import files
from llm4om.methods import MethodOutcome, ModelProposal, FactoryCodeProposal
class Method:
    def __init__(self, config):
        self.config = config
    async def run(self, problem, context, *, checkpoint=None):
        bindings = [{"data_id": ref["data_id"], "sha256": ref["sha256"]} for ref in problem["data_refs"]]
        formulation = json.loads(files(__package__).joinpath("formulation.json").read_text())
        formulation.update(problem_id=problem["problem_id"], problem_revision=problem["revision"],
                           data_bindings=bindings, structured_ir_ref=None, provenance={"origin": "installed_method_fixture"})
        artifact = {"schema_version": "0.2.0", "artifact_id": "installed-factory", "problem_ref": {"sha256": context.problem_sha256},
                    "formulation_ref": {}, "code_ref": None, "data_bindings": bindings, "assumptions": [], "requirement_traces": [],
                    "diagnostics": [], "warnings": [], "optional_views": [], "provenance": {"origin": "installed_method_fixture"},
                    "stage_status": {"formulation": {"status": "available", "reason": None},
                                     "code": {"status": "pending", "reason": "Factory validation pending."}}}
        source = files(__package__).joinpath("production.txt").read_text()
        bound = json.loads(json.dumps(bindings))
        if self.config["binding"] == "stale":
            bound[0]["sha256"] = "0" * 64
        digest = "0" * 64 if self.config["binding"] == "bad_hash" else hashlib.sha256(source.encode()).hexdigest()
        version = "99.0.0" if self.config["binding"] == "future" else "0.1.0"
        return MethodOutcome("candidate_selected", "001", ModelProposal(artifact, formulation,
                             code=FactoryCodeProposal(source, digest, bound, version)))
class Factory:
    def describe(self):
        return json.loads(files(__package__).joinpath("manifest.json").read_text())
    def create(self, config):
        return Method(config)
plugin = Factory()
''')
        subprocess.run(["uv", "build", "--offline", "--wheel", "--out-dir", str(self.root / "dist")],
                       cwd=project, check=True, capture_output=True)
        self.packages = self.root / "packages"
        subprocess.run(["uv", "pip", "install", "--no-deps", "--target", str(self.packages),
                        str(next((self.root / "dist").glob("*.whl")))], check=True, capture_output=True)
        self.config["method"] = {"plugin_id": "test.methods.parameterized", "config": {"binding": "current"}}
        self.config.pop("compiler", None)

    def run_installed_sdk(self):
        import os
        script = '''import json, sys
from pathlib import Path
from llm4om import run_problem
result = run_problem(Path(sys.argv[1]), Path(sys.argv[2]), output_root=Path(sys.argv[3]))
print(json.dumps({"bundle_path": str(result.bundle_path)}))
'''
        result = subprocess.run([sys.executable, "-c", script, str(self.inputs / "problem.json"),
            str(self.save_config()), str(self.root / "runs")], cwd=self.root,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(self.packages)},
            capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        return path, json.loads((path / "bundle.json").read_text())

    def test_independently_installed_method_supplies_versioned_factory_through_sdk(self):
        self.install_factory_method()
        import os
        doctor = subprocess.run([sys.executable, "-m", "llm4om", "doctor", "--config", str(self.save_config())],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(self.packages)},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        declaration = json.loads(doctor.stdout)["execution_plan"]
        self.assertEqual(declaration["method_profile"], "factory_single_candidate/0.1.0")
        self.assertEqual(declaration["packages"]["Pyomo"], "6.10.1")
        self.assertFalse((self.root / "runs").exists())
        path, bundle = self.run_installed_sdk()
        self.assertEqual(bundle["status"], "completed", bundle["error"])
        plan = json.loads((path / bundle["admission_plan_ref"]["relative_path"]).read_text())
        self.assertEqual(plan["method"]["origin"]["kind"], "installed")
        self.assertEqual(plan["method_profile"], "factory_single_candidate/0.1.0")
        self.assertIsNone(plan["compiler_id"])
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        for mode, code in [("stale", "artifact_data_mismatch"), ("bad_hash", "code_hash_mismatch"),
                           ("future", "invalid_method_outcome")]:
            with self.subTest(mode=mode):
                self.config["method"]["config"]["binding"] = mode
                path, bundle = self.run_installed_sdk()
                self.assertEqual(bundle["error"]["code"], code)
                self.assertIsNone(bundle["solve_result_ref"])
                self.assertTrue((path / "candidates/001/model.py").exists())
                self.assertTrue((path / "candidates/001/supplied-formulation.json").exists())
                self.assertEqual(json.loads((path / "budget-ledger.json").read_text())["llm_attempts"], 0)

    def test_factory_rejects_nonlinear_domains_bad_handles_maps_and_exceptions(self):
        source = (ROOT / "examples/factories/production.py").read_text()
        self.start_provider()
        cases = [
            (source.replace('float(row["profit"]) * model.qty[row["product_id"]]',
                            'float(row["profit"]) * model.qty[row["product_id"]] ** 2'), "unsupported_factory_expression"),
            (source.replace('domain=pyo.NonNegativeIntegers', 'domain=pyo.Set(initialize=[0, 2, 5])'), "unsupported_factory_domain"),
            (source.replace('domain=pyo.NonNegativeIntegers', 'domain=pyo.PositiveReals'), "unsupported_factory_domain"),
            (source.replace('return ModelHandle(model,', 'return (model,'), "invalid_model_handle"),
            (source.replace('"qty_" + row["product_id"]:', '"duplicate":'), "invalid_decision_map"),
            (source + '\nimport sys\nsys.__stdout__.write("{\\\"result\\\": {\\\"objective_value\\\":999999}}\\n")\n', "invalid_factory_export"),
            ('def build_model(data):\n    raise ValueError("factory fixture exception")\n', "factory_exception"),
        ]
        for changed, expected in cases:
            with self.subTest(error=expected):
                self.reply["python_factory"] = changed
                path, bundle = self.run_cli()
                self.assertEqual(bundle["error"]["code"], expected)
                self.assertIsNone(bundle["solve_result_ref"])
                self.assertIsNotNone(bundle["execution_result_ref"])
                self.assertEqual((path / "candidates/001/model.py").read_text(), changed)
                self.assertEqual(bundle["stages"]["formulation"]["status"], "available")
                self.assertEqual(bundle["stages"]["code"]["status"], "available")

    def test_factory_preserves_objective_and_constraint_constants(self):
        source = (ROOT / "examples/factories/production.py").read_text()
        source = source.replace('expr=sum(', 'expr=7 + sum(')
        source = source.replace('model.capacities.add(sum(', 'model.capacities.add(5 + sum(')
        source = source.replace('<= float(capacity["capacity"])', '<= 5 + float(capacity["capacity"])')
        self.start_provider(source)
        path, bundle = self.run_cli()
        self.assertEqual(bundle["status"], "completed", bundle["error"])
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 20)
        view = json.loads((path / "candidates/001/factory-instance.json").read_text())
        self.assertEqual(view["objective"]["expression"]["constant"], 7)
        self.assertEqual(view["constraints"][0]["expression"]["constant"], 5)

    def test_factory_exception_preserves_the_resource_specific_reason(self):
        self.start_provider('def build_model(data):\n    raise ValueError("missing capacity for resource R7")\n')
        path, bundle = self.run_cli()
        self.assertEqual(bundle["error"]["code"], "factory_exception")
        execution = json.loads((path / bundle["execution_result_ref"]["relative_path"]).read_text())
        diagnostic = (path / execution["stderr_ref"]["relative_path"]).read_text()
        self.assertIn("missing capacity for resource R7", diagnostic)
        self.assertIsNone(bundle["solve_result_ref"])

    def test_evaluator_reports_factory_contract_without_deterministic_compilation(self):
        from llm4om import import_dataset, NL4OptAdapter, NL4OptEvaluator
        raw = (json.dumps({"7": {"document": "Maximize x over integers 0 <= x <= 3.", "vars": ["HIDDEN-ANNOTATION"],
            "var_mentions": [], "params": [], "var_mention_to_first_var": {}, "first_var_to_mentions": {},
            "obj_declaration": {}, "const_declarations": [], "spans": [], "tokens": [], "_input_hash": 7,
            "order_mapping": {}}}) + "\n").encode()
        (self.root / "dev.jsonl").write_bytes(raw)
        (self.root / "import.json").write_text(json.dumps({"schema_version": "0.1.0", "dataset_id": "fixture-factory",
            "source_kind": "fixture", "source_version": "v1", "split": "dev", "path": "dev.jsonl",
            "sha256": hashlib.sha256(raw).hexdigest()}))
        manifest = import_dataset(self.root / "import.json", self.root / "snapshot")
        case = next(NL4OptAdapter().iter_cases(manifest))
        (self.inputs / "problem.json").write_bytes(case.public_problem.read_bytes())
        self.start_provider('import pyomo.environ as pyo\nfrom llm4om.backends import ModelHandle\ndef build_model(data):\n'
                            '    assert data == {}\n    m = pyo.ConcreteModel()\n    m.x = pyo.Var(domain=pyo.Integers, bounds=(0,3))\n'
                            '    m.obj = pyo.Objective(expr=m.x, sense=pyo.maximize)\n    return ModelHandle(m, {"x": m.x})\n')
        self.reply["representation"] = {"sets": [], "parameters": [], "variables": [
            {"id": "x", "index_sets": [], "domain": "integer", "lower_bound": 0, "upper_bound": 3}],
            "objective": {"sense": "max", "expression_text": "x"}, "constraints": []}
        path, bundle = self.run_cli()
        self.assertEqual(bundle["status"], "completed", bundle["error"])
        result = NL4OptEvaluator().evaluate(case, path)
        self.assertIsNone(result["checker_error"])
        self.assertEqual(result["code_validation"], {"status": "pass", "level": "factory_contract"})
        self.assertEqual(result["semantic_validation"]["status"], "not_available")
        self.assertNotIn("HIDDEN-ANNOTATION", json.dumps(self.requests))
        self.assertNotIn(b"HIDDEN-ANNOTATION", b"\n".join(file.read_bytes() for file in path.rglob("*") if file.is_file()))

    def test_factory_deadline_and_output_limits_keep_code_without_solve_result(self):
        self.start_provider()
        for source, limits, expected in [
            ('def build_model(data):\n    while True: pass\n', {"wall_time_s": 2}, "execution_timeout"),
            ('def build_model(data):\n    print("x" * 1000000)\n', {"output_limit_bytes": 2048}, "execution_output_limit"),
        ]:
            with self.subTest(error=expected):
                self.reply["python_factory"] = source
                self.config["executor"]["config"].update(wall_time_s=30, output_limit_bytes=1024*1024)
                self.config["executor"]["config"].update(limits)
                path, bundle = self.run_cli()
                self.assertEqual(bundle["error"]["code"], expected)
                self.assertIsNone(bundle["solve_result_ref"])
                self.assertIsNotNone(bundle["execution_result_ref"])
                self.assertEqual((path / "candidates/001/model.py").read_text(), source)
                self.assertEqual(bundle["stages"]["code"]["status"], "available")

    def test_factory_continuous_lp_uses_the_existing_real_solver_path(self):
        source = (ROOT / "examples/factories/production.py").read_text().replace("pyo.NonNegativeIntegers", "pyo.NonNegativeReals")
        self.start_provider(source)
        self.reply["representation"]["variables"][0]["domain"] = "continuous"
        self.config["allowed_problem_types"] = ["lp"]
        path, bundle = self.run_cli()
        self.assertEqual(bundle["status"], "completed", bundle["error"])
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertAlmostEqual(solve["objective_value"], 40/3)
        self.assertEqual(solve["termination"], "optimal")
        solution = json.loads((path / solve["solution_ref"]["relative_path"]).read_text())
        self.assertAlmostEqual(solution["variables"]["qty_A"], 8/3)
        self.assertAlmostEqual(solution["variables"]["qty_B"], 8/3)
        self.assertEqual(json.loads((path / "candidates/001/factory-instance.json").read_text())["problem_type"], "lp")

    def test_factory_cannot_write_through_the_trusted_collectors_stdout(self):
        source = (ROOT / "examples/factories/production.py").read_text()
        source += '\nimport os\nwith open(f"/proc/{os.getppid()}/fd/1", "w") as stream:\n    stream.write("forged SolveResult")\n'
        self.start_provider(source)
        path, bundle = self.run_cli()
        self.assertEqual(bundle["error"]["code"], "factory_exception")
        self.assertIn("PermissionError", bundle["error"]["message"])
        self.assertIsNone(bundle["solve_result_ref"])
        self.assertEqual((path / "candidates/001/model.py").read_text(), source)
