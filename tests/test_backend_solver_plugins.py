"""Backend/Solver extension behavior at public model construction/solve seams."""

import json
import hashlib
import subprocess
import sys
import tempfile
import shutil
import os
import yaml
from pathlib import Path
import unittest

from llm4om.linear import compile_ir
from llm4om.executors import DEFAULT_IMAGE

ROOT = Path(__file__).resolve().parents[1]


class BackendSolverContractTests(unittest.TestCase):
    def test_cli_inventory_declares_actual_backend_and_solver_handle_profiles(self):
        result = subprocess.run([sys.executable, "-m", "llm4om", "plugins", "list"],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plugins = [item["manifest"] for item in json.loads(result.stdout)["plugins"]]
        backends = {item["plugin_id"]: item for item in plugins if item["kind"] == "model_backend"}
        solvers = {item["plugin_id"]: item for item in plugins if item["kind"] == "solver_backend"}
        self.assertEqual(set(backends), {"llm4om.model_backends.pyomo_factory", "llm4om.model_backends.gurobipy"})
        self.assertEqual(set(solvers), {"llm4om.solvers.highs", "llm4om.solvers.gurobi", "llm4om.solvers.ortools"})
        self.assertEqual(backends["llm4om.model_backends.pyomo_factory"]["capabilities"]["handle_profile"], "pyomo_linear/0.1.0")
        self.assertEqual(solvers["llm4om.solvers.highs"]["capabilities"]["handle_profiles"], ["pyomo_linear/0.1.0"])
        self.assertEqual(solvers["llm4om.solvers.ortools"]["capabilities"]["handle_profiles"], ["pyomo_linear/0.1.0"])
        self.assertEqual(solvers["llm4om.solvers.ortools"]["capabilities"]["result_profile"], "ortools_api/0.1.0")

    def test_pyomo_backend_and_highs_solver_use_an_explicit_model_handle(self):
        from llm4om.backends import PyomoFactoryBackend
        from llm4om.solvers import HighsSolverBackend
        ir = json.loads((ROOT / "examples/specs/model-ir.json").read_text())
        handle = PyomoFactoryBackend().load(compile_ir(ir), {})
        self.assertEqual(set(handle.decision_map), {"qty_A", "qty_B"})
        result = HighsSolverBackend().solve(handle, {})
        self.assertEqual(result["termination"], "optimal")
        self.assertEqual(result["variables"], {"qty_A": 3.0, "qty_B": 2.0})
        self.assertEqual(result["objective_value"], 13)

    def test_solver_rejects_nonlinear_or_unmapped_handles_without_silently_solving_a_different_model(self):
        import pyomo.environ as pyo
        from llm4om.backends import ModelHandle
        from llm4om.solvers import HighsSolverBackend
        from llm4om.contracts import RunError
        model = pyo.ConcreteModel()
        model.x = pyo.Var(bounds=(0, 2))
        model.objective = pyo.Objective(expr=model.x ** 2, sense=pyo.maximize)
        with self.assertRaises(RunError) as error:
            HighsSolverBackend().solve(ModelHandle(model, {"x": model.x}), {})
        self.assertEqual(error.exception.code, "unsupported_factory_expression")
        model.objective.set_value(model.x)
        with self.assertRaises(RunError) as error:
            HighsSolverBackend().solve(ModelHandle(model, {}), {})
        self.assertEqual(error.exception.code, "invalid_decision_map")

    def test_constant_only_compilation_keeps_internal_anchor_out_of_decisions(self):
        from llm4om.backends import PyomoFactoryBackend
        from llm4om.solvers import HighsSolverBackend
        ir = json.loads((ROOT / "examples/specs/model-ir.json").read_text())
        ir.update(problem_type="lp", variables=[], constraints=[])
        ir["objective"]["expression"] = {"constant": 7, "terms": []}
        backend = PyomoFactoryBackend()
        handle = backend.load(compile_ir(ir), {})
        self.assertEqual(backend.export(handle)["variables"], [])
        result = HighsSolverBackend().solve(handle, {})
        self.assertEqual(result["variables"], {})
        self.assertEqual(result["objective_value"], 7)

    def test_gurobi_solver_consumes_the_same_pyomo_handle_with_real_sdk(self):
        from llm4om.backends import PyomoFactoryBackend
        from llm4om.solvers import GurobiSolverBackend
        ir = json.loads((ROOT / "examples/specs/model-ir.json").read_text())
        result = GurobiSolverBackend().solve(PyomoFactoryBackend().load(compile_ir(ir), {}), {})
        self.assertEqual(result["objective_value"], 13)
        self.assertEqual(result["variables"], {"qty_A": 3.0, "qty_B": 2.0})

    def test_resolved_pair_checks_compatibility_and_options_before_constructing_or_solving(self):
        from llm4om.execution_plugins import resolve_execution_resources
        from llm4om.contracts import RunError
        resources = resolve_execution_resources(
            {"plugin_id": "llm4om.model_backends.pyomo_factory"}, {"plugin_id": "llm4om.solvers.highs"}, ["lp", "milp"])
        ir = json.loads((ROOT / "examples/specs/model-ir.json").read_text())
        handle = resources.backend.load(compile_ir(ir), {})
        self.assertEqual(resources.solve(handle, {})["objective_value"], 13)
        with self.assertRaises(RunError) as error:
            resolve_execution_resources({"plugin_id": "llm4om.model_backends.gurobipy"},
                {"plugin_id": "llm4om.solvers.highs"}, ["lp"])
        self.assertEqual(error.exception.code, "capability_mismatch")
        with self.assertRaises(RunError) as error:
            resolve_execution_resources({"plugin_id": "llm4om.model_backends.pyomo_factory"},
                {"plugin_id": "llm4om.solvers.highs", "options": {"private_option": 1}}, ["lp"])
        self.assertEqual(error.exception.code, "invalid_solver_options")

    def test_actual_handle_problem_type_must_match_the_admitted_scope(self):
        from llm4om.execution_plugins import resolve_execution_resources
        from llm4om.contracts import RunError
        resources = resolve_execution_resources({"plugin_id": "llm4om.model_backends.pyomo_factory"},
            {"plugin_id": "llm4om.solvers.highs"}, ["lp"])
        ir = json.loads((ROOT / "examples/specs/model-ir.json").read_text())
        with self.assertRaises(RunError) as error:
            resources.solve(resources.backend.load(compile_ir(ir), {}), {})
        self.assertEqual(error.exception.code, "capability_mismatch")


class InstalledExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packages = self.root / "packages"
        self.inputs = self.root / "inputs"
        shutil.copytree(ROOT / "examples/specs", self.inputs)
        project = self.root / "plugin"
        shutil.copytree(ROOT / "examples/plugins/fixture_execution", project)
        subprocess.run(["uv", "build", "--offline", "--wheel", "--out-dir", str(self.root / "dist")],
            cwd=project, capture_output=True, text=True, check=True)
        subprocess.run(["uv", "pip", "install", "--no-deps", "--target", str(self.packages), str(next((self.root / "dist").glob("*.whl")))],
            capture_output=True, text=True, check=True)

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "llm4om", *args], cwd=self.root,
            env={**os.environ, "LLM4OM_EXECUTION_FIXTURE_KEY": "synthetic-execution-key",
                "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, timeout=90)

    def run_installed_pair(self):
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["model_backend"] = {"plugin_id": "llm4om.examples.renaming_pyomo", "config": {"component": "selected_decisions"}}
        settings["solver"] = {"plugin_id": "llm4om.examples.checking_highs", "config": {"component": "selected_decisions"}}
        if os.environ.get("LLM4OM_TEST_EXECUTION_IMAGE"):
            settings["executor"] = yaml.safe_load((self.inputs / "run.yaml").read_text())["executor"]
            settings["executor"]["config"]["image"] = os.environ["LLM4OM_TEST_EXECUTION_IMAGE"]
        config = self.inputs / "execution.yaml"
        config.write_text(yaml.safe_dump(settings))
        doctor = self.cli("doctor", "--config", str(config))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        return path

    def test_installed_pair_is_admitted_and_actually_constructs_and_solves(self):
        path = self.run_installed_pair()
        solve = json.loads((path / "candidates/001/solve-result.json").read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(solve["solver_id"], "llm4om.examples.checking_highs")
        self.assertEqual(solve["model_backend"], "llm4om.examples.renaming_pyomo")
        self.assertEqual(solve["effective_options"]["fixture_component"], "selected_decisions")

    def test_installed_pair_completed_resume_is_idempotent_and_package_changes_reject(self):
        path = self.run_installed_pair()
        ledger = (path / "budget-ledger.json").read_bytes()
        resumed = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertEqual((path / "budget-ledger.json").read_bytes(), ledger)
        events = (path / "events.jsonl").read_bytes()
        source = self.packages / "llm4om_fixture_execution/__init__.py"
        source.write_text(source.read_text() + "\n# changed execution adapter\n")
        resumed = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(json.loads(resumed.stdout)["error"]["code"], "checkpoint_incompatible")
        self.assertEqual((path / "events.jsonl").read_bytes(), events)
        self.assertEqual((path / "budget-ledger.json").read_bytes(), ledger)

    def test_installed_pair_preserves_continuous_lp_domain_and_optimum(self):
        problem = json.loads((self.inputs / "problem.json").read_text())
        problem.update(revision="continuous-1", problem_type_hint="lp")
        problem["requirements"][1]["text"] = "A and B are nonnegative real quantities."
        (self.inputs / "problem.json").write_text(json.dumps(problem))
        ir = json.loads((self.inputs / "model-ir.json").read_text())
        ir.update(problem_revision="continuous-1", problem_type="lp")
        for variable in ir["variables"]:
            variable["domain"] = "continuous"
        raw = json.dumps(ir).encode()
        (self.inputs / "model-ir.json").write_bytes(raw)
        formulation = json.loads((self.inputs / "formulation.json").read_text())
        formulation["problem_revision"] = "continuous-1"
        formulation["representation"]["variables"][0]["domain"] = "continuous"
        formulation["structured_ir_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        raw = json.dumps(formulation).encode()
        (self.inputs / "formulation.json").write_bytes(raw)
        artifact = json.loads((self.inputs / "model-artifact.json").read_text())
        artifact["formulation_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        raw = (self.inputs / "problem.json").read_bytes()
        artifact["problem_ref"].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        (self.inputs / "model-artifact.json").write_text(json.dumps(artifact))
        path = self.run_installed_pair()
        result = json.loads((path / "candidates/001/solve-result.json").read_text())
        solution = json.loads((path / "candidates/001/solution.json").read_text())["variables"]
        self.assertAlmostEqual(result["objective_value"], 40 / 3)
        self.assertAlmostEqual(solution["qty_A"], 8 / 3)
        self.assertAlmostEqual(solution["qty_B"], 8 / 3)

    def test_missing_pair_in_worker_rejects_before_generation_or_solver(self):
        settings = yaml.safe_load((self.inputs / "run.yaml").read_text())
        settings["model_backend"] = {"plugin_id": "llm4om.examples.renaming_pyomo", "config": {"component": "selected_decisions"}}
        settings["solver"] = {"plugin_id": "llm4om.examples.checking_highs", "config": {"component": "selected_decisions"}}
        config = self.inputs / "missing-worker.yaml"
        config.write_text(yaml.safe_dump(settings))
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        bundle = json.loads((path / "bundle.json").read_text())
        self.assertEqual(bundle["error"]["code"], "execution_plugin_unavailable")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["llm_attempts"], ledger["solver_calls"]), (0, 0))

    def test_solver_cannot_misreport_options_or_invalid_values_and_keeps_errors_safe(self):
        source = self.packages / "llm4om_fixture_execution/__init__.py"
        original = source.read_text()
        for mutation in ('result["options"] = {"time_limit_s": 999}',
                'result["objective_value"] = float("nan")',
                'raise RunError("solver_error", "solve", "PRIVATE-SOLVER-ERROR", details={"private": "PRIVATE-SOLVER-ERROR"})'):
            with self.subTest(mutation=mutation):
                source.write_text(original.replace("return result", mutation + "\n        return result"))
                shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
                settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
                settings["model_backend"] = {"plugin_id": "llm4om.examples.renaming_pyomo", "config": {"component": "selected_decisions"}}
                settings["solver"] = {"plugin_id": "llm4om.examples.checking_highs", "config": {"component": "selected_decisions"}}
                config = self.inputs / "bad-solver.yaml"
                config.write_text(yaml.safe_dump(settings))
                result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                path = Path(json.loads(result.stdout)["bundle_path"])
                self.assertIsNone(json.loads((path / "bundle.json").read_text())["solve_result_ref"])
                self.assertTrue(all(b"PRIVATE-SOLVER-ERROR" not in p.read_bytes() for p in path.rglob("*") if p.is_file()))

    def test_solver_runtime_version_mismatch_rejects_before_generation(self):
        source = self.packages / "llm4om_fixture_execution/__init__.py"
        source.write_text(source.read_text().replace("class CheckingHighsSolver(HighsSolverBackend):",
            'class CheckingHighsSolver(HighsSolverBackend):\n    def runtime(self):\n        return {"packages": {"highspy": "invalid-version"}}\n'))
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["model_backend"] = {"plugin_id": "llm4om.examples.renaming_pyomo", "config": {"component": "selected_decisions"}}
        settings["solver"] = {"plugin_id": "llm4om.examples.checking_highs", "config": {"component": "selected_decisions"}}
        config = self.inputs / "bad-runtime.yaml"
        config.write_text(yaml.safe_dump(settings))
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        self.assertEqual(json.loads((path / "bundle.json").read_text())["error"]["code"], "solver_unavailable")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["llm_attempts"], ledger["solver_calls"]), (0, 0))

    def test_backend_input_representation_is_checked_before_generation(self):
        source = self.packages / "llm4om_fixture_execution/__init__.py"
        source.write_text(source.read_text().replace("return manifest", 'manifest["capabilities"]["input_artifact_kinds"] = ["native_code"]\n        return manifest', 1))
        shutil.rmtree(source.parent / "__pycache__", ignore_errors=True)
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["model_backend"] = {"plugin_id": "llm4om.examples.renaming_pyomo", "config": {"component": "selected_decisions"}}
        config = self.inputs / "wrong-representation.yaml"
        config.write_text(yaml.safe_dump(settings))
        result = self.cli("doctor", "--config", str(config))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "capability_mismatch")

    def test_public_solver_dispatch_accepts_installed_pair_and_config(self):
        script = """import json,sys
from pathlib import Path
from llm4om.linear import compile_ir
from llm4om.executors import DEFAULT_IMAGE
from llm4om.solvers import solve,solver_runtime
config={'component':'selected_decisions'}
runtime=solver_runtime('llm4om.examples.checking_highs',config=config)
code=compile_ir(json.loads(Path(sys.argv[1]).read_text()))
result=solve(code,{},'llm4om.examples.checking_highs',config=config,
    backend_selection={'plugin_id':'llm4om.examples.renaming_pyomo','config':config})
print(json.dumps({'runtime':runtime,'result':result}))
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.inputs / "model-ir.json")],
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"]["objective_value"], 13)

    def serve_replies(self, replies):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        answers = iter(replies)
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": next(answers)}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 300, "completion_tokens": 600, "total_tokens": 900}}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": "synthetic-execution",
            "config": {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "credential_env": "LLM4OM_EXECUTION_FIXTURE_KEY", "max_output_tokens": 2048, "max_retries": 0}}

    def test_installed_pair_constructs_parameterized_factory_in_child_and_independently_solves(self):
        reply = {"representation": json.loads((self.inputs / "formulation.json").read_text())["representation"],
            "python_factory": (ROOT / "examples/factories/production.py").read_text()}
        settings = yaml.safe_load((self.inputs / "run.yaml").read_text())
        settings["budget"]["max_total_tokens"] = 30000
        settings["method"]["config"]["output_mode"] = "python_factory"
        settings["model_backend"] = {"plugin_id": "llm4om.examples.renaming_pyomo", "config": {"component": "selected_decisions"}}
        settings["solver"] = {"plugin_id": "llm4om.examples.checking_highs", "config": {"component": "selected_decisions"}}
        settings["executor"]["config"]["image"] = os.environ.get("LLM4OM_TEST_EXECUTION_IMAGE", DEFAULT_IMAGE + "-with-execution")
        settings["llm"] = self.serve_replies([json.dumps(reply)])
        config = self.inputs / "factory.yaml"
        config.write_text(yaml.safe_dump(settings))
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        solve = json.loads((path / "candidates/001/solve-result.json").read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(solve["effective_options"]["fixture_component"], "selected_decisions")
        decision_map = json.loads((path / "candidates/001/decision-map.json").read_text())["decisions"]
        self.assertTrue(all(name.startswith("selected_decisions[") for name in decision_map.values()))
        code = json.loads((path / "candidates/001/code-artifact.json").read_text())
        self.assertEqual(code["provenance"]["origin"], "method_generated")

    def test_installed_native_pair_constructs_and_reads_mps_before_actual_gurobi_solve(self):
        reply = {"representation": json.loads((self.inputs / "formulation.json").read_text())["representation"],
            "native_gurobipy": (ROOT / "examples/factories/production_gurobi.py").read_text()}
        settings = yaml.safe_load((self.inputs / "gurobi.yaml").read_text())
        settings["budget"]["max_total_tokens"] = 30000
        settings["method"]["config"]["output_mode"] = "native_gurobipy"
        settings["model_backend"] = {"plugin_id": "llm4om.examples.marking_gurobipy", "config": {"component": "selected_native"}}
        settings["solver"] = {"plugin_id": "llm4om.examples.checking_gurobi", "config": {"component": "selected_native"}}
        settings["executor"]["config"]["image"] = os.environ.get("LLM4OM_TEST_EXECUTION_IMAGE", DEFAULT_IMAGE + "-with-execution")
        settings["llm"] = self.serve_replies([json.dumps(reply)])
        config = self.inputs / "native.yaml"
        config.write_text(yaml.safe_dump(settings))
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        solve = json.loads((path / "candidates/001/solve-result.json").read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(solve["solver_id"], "llm4om.examples.checking_gurobi")
        self.assertEqual(solve["effective_options"]["fixture_component"], "selected_native")
        self.assertTrue((path / "candidates/001/native-model.mps").is_file())

    def test_installed_native_pair_is_used_by_original_coe_script_and_independent_collector(self):
        import hashlib
        contract = json.dumps({"code_example": "def prob_case(capacity): pass", "entry_point": "prob_case", "input": {"capacity": 4}}).encode()
        (self.inputs / "contract.json").write_bytes(contract)
        problem = json.loads((self.inputs / "problem.json").read_text())
        problem.update(schema_version="0.3.0", description="Maximize 3x, with nonnegative integer x at most capacity.", requirements=[],
            data_refs=[{"data_id": "contract", "path": "contract.json", "format": "json", "schema": {"type": "object"}, "sha256": hashlib.sha256(contract).hexdigest()}])
        (self.inputs / "problem.json").write_text(json.dumps(problem))
        source = """import gurobipy as gp
def prob_case(capacity):
    model = gp.Model()
    x = model.addVar(lb=0, vtype=gp.GRB.INTEGER, name="x")
    model.addConstr(x <= capacity)
    model.setObjective(3*x, gp.GRB.MAXIMIZE)
    model.optimize()
    return model.ObjVal
"""
        settings = yaml.safe_load((self.inputs / "gurobi.yaml").read_text())
        settings.pop("compiler")
        settings["method"] = {"plugin_id": "llm4om.methods.coe", "config": {"public_contract_data_id": "contract", "max_collaborate_nums": 1,
            "enable_reflection": False, "max_trials": 1, "seed": 7}}
        settings["budget"].update(max_total_tokens=150000, max_llm_attempts=10, max_solver_calls=2, max_repairs=0, wall_time_s=90)
        settings["model_backend"] = {"plugin_id": "llm4om.examples.marking_gurobipy", "config": {"component": "selected_native"}}
        settings["solver"] = {"plugin_id": "llm4om.examples.checking_gurobi", "config": {"component": "selected_native"}}
        settings["executor"]["config"]["image"] = os.environ.get("LLM4OM_TEST_EXECUTION_IMAGE", DEFAULT_IMAGE + "-with-execution")
        settings["llm"] = self.serve_replies(["Programming Expert", "Use integer x bounded by capacity.", source])
        config = self.inputs / "script.yaml"
        config.write_text(yaml.safe_dump(settings))
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(config), "--output", str(self.root / "runs"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = Path(json.loads(result.stdout)["bundle_path"])
        bundle = json.loads((path / "bundle.json").read_text())
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 12)
        self.assertEqual(solve["effective_options"]["fixture_component"], "selected_native")
        self.assertEqual(solve["solver_id"], "llm4om.examples.checking_gurobi")


if __name__ == "__main__":
    unittest.main()
