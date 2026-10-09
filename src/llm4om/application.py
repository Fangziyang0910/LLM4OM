"""Replay a public Formulation and optionally compile and solve its grounded IR."""

import hashlib
import base64
import json
import platform
import time
import sys
from copy import deepcopy
from importlib.metadata import version
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from io import StringIO
from pathlib import Path
from types import MappingProxyType
from typing import Any

from llm4om.contracts import (
    RunError, parse_json, public_path, read_config, read_public_bytes, validate_config, validate_csv, validate_problem,
    validate_model_artifact, validate_formulation, validate_bindings, reject_additional_refs,
    validate_worker_response,
)
from llm4om.control import CancellationToken
from llm4om.providers import Gateway
from llm4om.methods import FactoryCodeProposal, MethodContext, ModelProposal
from llm4om.preflight import AdmissionPlan, prepare_run
from llm4om.linear import CompiledCode, compile_ir
from llm4om.storage import RunStore
from llm4om.executors import run_container, run_owned_process


@dataclass(frozen=True)
class RunResult:
    run_id: str
    bundle_path: Path
    status: str


def run_problem(problem: Path, config: Path, *, offline: bool = False,
                output_root: Path | None = None, cancellation: CancellationToken | None = None) -> RunResult:
    cancellation = cancellation or CancellationToken()
    try:
        settings = read_config(config)
        root = output_root or config.parent / settings["store"]["config"]["root"]
    except (OSError, ValueError, KeyError, TypeError):
        root = output_root or Path.cwd() / "runs"
    store = RunStore(root, cancellation=cancellation)
    try:
        return _run_problem(problem, config, store, offline=offline)
    finally:
        store.close()


def _run_problem(problem: Path, config: Path, store: RunStore, *, offline: bool = False,
                 restored_plan: AdmissionPlan | None = None) -> RunResult:
    started = time.time()
    cancellation = store.cancellation
    settings: dict[str, Any] = {}
    config_error: Exception | None = None
    try:
        settings = read_config(config)
    except (OSError, ValueError, KeyError, TypeError) as error:
        config_error = error
    mode = "offline_mock" if offline else "not_resolved"
    store.emit("run_resumed" if "problem" in store.state else "run_started", mode=mode)
    ledger: dict[str, Any] = {"schema_version": "0.2.0", "llm_attempts": 0,
                             "solver_calls": 0, "external_llm_requests": 0, "candidates": 0, "total_tokens": None,
                             "cost": 0, "evidence_origin": "mock_fixture"}
    error_record: dict[str, Any] | None = None
    artifact_ref = store.state.get("artifact_ref")
    settings_valid = False
    solve_ref = store.state.get("solve_ref")
    execution_ref = store.state.get("execution_ref")
    admission_ref = None
    requested_config_ref = None
    code_level = "deterministic_compilation"
    stages: dict[str, Any] = {name: {"status": "not_available", "reason": "Stage has not run."}
              for name in ("formulation", "code", "solve")}
    ledger = store.state.get("ledger", ledger)
    stages = store.state.get("stages", stages)
    try:
        cancellation.check()
        if config_error:
            if isinstance(config_error, RunError):
                raise config_error
            raise RunError("invalid_config", "validation", "Cannot read a valid RunConfig.")
        requested_config_ref = store.json("requested-config.json", settings, "requested-config")
        validate_config(settings)
        settings_valid = True
        if "problem" not in store.state:
            sources = {str(problem.resolve()): hashlib.sha256(read_public_bytes(problem)).hexdigest(),
                       str(config.resolve()): hashlib.sha256(read_public_bytes(config)).hexdigest()}
            public_input = parse_json(read_public_bytes(problem))
            for data in public_input.get("data_refs", []):
                path = public_path(problem.parent, data["path"])
                sources[str(path)] = hashlib.sha256(read_public_bytes(path)).hexdigest()
            if "response_artifact" in settings["llm"]["config"]:
                path = public_path(config.parent, settings["llm"]["config"]["response_artifact"])
                sources[str(path)] = hashlib.sha256(read_public_bytes(path)).hexdigest()
            store.state.update(problem=str(problem.resolve()), config=str(config.resolve()), sources=sources,
                               offline=offline, phase="admitted", ledger=ledger, stages=stages,
                               artifact_ref=None, solve_ref=None, execution_ref=None,
                               deadline=started + settings["budget"]["wall_time_s"])
        else:
            ledger = store.state["ledger"]
            stages = store.state["stages"]
            artifact_ref = store.state["artifact_ref"]
            solve_ref = store.state["solve_ref"]
            execution_ref = store.state["execution_ref"]
        plan = restored_plan or prepare_run(settings, offline=offline, config_dir=config.parent,
                           deadline=store.state["deadline"], cancellation=cancellation, expected=store.state.get("admission"))
        if "admission" in store.state and plan.snapshot != store.state["admission"]:
            raise RunError("checkpoint_incompatible", "admission", "Method, package, runtime or resource identity changed.")
        admission_ref = store.json("admission-plan.json", plan.snapshot, "admission-plan")
        mode = plan.snapshot["mode"]
        if plan.snapshot["method_profile"] in ("factory_single_candidate/0.1.0", "native_single_candidate/0.1.0"):
            code_level = "factory_contract"
        store.state["admission"] = plan.snapshot
        store.state["sdk"] = version("llm4om")
        store.state["host"] = {"python": platform.python_version(), "sdk_sha256": _sdk_sha256(),
                               "packages": {name: version(name) for name in ("PyYAML", "jsonschema")}}
        store.checkpoint()
        if artifact_ref is None:
            artifact_ref, stages = _prepare_candidate(store, problem, config, settings, ledger, offline, plan)
            store.state.update(artifact_ref=artifact_ref, stages=stages, phase="method_done")
            store.checkpoint()
        status = "artifact_ready"
        if not offline:
            if store.state["phase"] == "method_done":
                artifact_ref, compiled = _compile_candidate(store, artifact_ref, settings)
                stages["code"] = {"status": "available", "reason": None}
                store.state.update(artifact_ref=artifact_ref, phase="code_done")
                store.checkpoint()
            else:
                compiled = _restored_compilation(store, artifact_ref)
            cancellation.check()
            stages["code"] = {"status": "available", "reason": None}
            if store.state["phase"] != "execute_done":
                solve_ref, execution_ref, execution_error = _execute_candidate(store, compiled, artifact_ref, settings, ledger, plan)
                artifact_ref = store.state.get("executed_artifact_ref", artifact_ref)
            else:
                execution_error = None
                store.emit("execution_reused", solve_result_ref=solve_ref)
            if solve_ref is not None:
                stages["solve"] = {"status": "available", "reason": None}
            if execution_error is not None:
                raise execution_error
            stages["solve"] = {"status": "available", "reason": None}
            cancellation.check()
            status = "completed"
    except (RunError, ValueError, KeyError, TypeError) as error:
        status = "cancelled" if isinstance(error, RunError) and error.code == "run_cancelled" else "failed"
        error_record = {"code": error.code if isinstance(error, RunError) else "invalid_input",
                        "stage": error.stage if isinstance(error, RunError) else "validation",
                        "message": str(error) if isinstance(error, RunError) else "Cannot process the public input or Mock artifact."}
        if isinstance(error, RunError) and error.details is not None:
            error_record["details_ref"] = store.json("diagnostics/plugin-error.json", error.details, "plugin-error")
    if stages["formulation"]["status"] == "available":
        store.json("evaluation.json", {"schema_version": "0.2.0", "protocol_id": "llm4om.eval.public-v0.1",
                   "formulation_validation": {"status": "pass", "level": "structural"},
                   "code_validation": {"status": "pass", "level": code_level}
                                      if stages["code"]["status"] == "available" else {"status": "not_available"},
                   "semantic_validation": {"status": "not_available"}}, "evaluation")
    store.state.update(ledger=ledger, stages=stages, artifact_ref=artifact_ref, solve_ref=solve_ref, execution_ref=execution_ref)
    store.json("budget-ledger.json", ledger, "budget")
    store.emit("run_finished", status=status, error=error_record)
    if settings_valid and any(reporter["plugin_id"] == "llm4om.reporters.markdown" for reporter in settings.get("reporters", [])):
        report = (f"# LLM4OM run {store.run_id}\n\nMode: {mode}. Status: {status}.\n\n"
                  "| Stage | Status |\n|---|---|\n" +
                  "".join(f"| {name} | {stage['status']} |\n" for name, stage in stages.items()) +
                  f"\nMethod: {settings['method']['plugin_id']}. Provider: {settings['llm']['provider_plugin_id']}. External LLM requests: {ledger['external_llm_requests']}.\n"
                  "Structural checks do not establish semantic correctness.\n")
        if solve_ref is not None:
            solve_summary = parse_json(read_public_bytes(store.path / solve_ref["relative_path"]))
            report += f"\n{solve_summary['solver_id']}: {solve_summary['termination']}. Objective: {solve_summary['objective_value']}.\n"
        if error_record:
            report += f"\nError: {error_record['code']} ({error_record['stage']}).\n"
        store.write("reports/report.md", report.encode(), "report")
    resource_status = {"compiler": "available" if code_level == "deterministic_compilation" and stages["code"]["status"] == "available" else "not_available",
                       **{name: "available" if solve_ref is not None else "failed" if execution_ref is not None else "not_available"
                          for name in ("model_backend", "solver", "executor")}}
    store.json("bundle.json", {"schema_version": "0.2.0", "run_id": store.run_id,
               "mode": mode, "status": status, "stages": stages,
               "error": error_record, "model_artifact_ref": artifact_ref, "solve_result_ref": solve_ref,
               "execution_result_ref": execution_ref,
               "admission_plan_ref": admission_ref,
               "requested_config_ref": requested_config_ref,
               "public_problem_ref": store.projections.get("public-problem.json"),
               "lineage_ref": store.state.get("lineage_ref"),
               "public_projections": {name: ref for name, ref in store.projections.items() if name != "bundle.json"},
               "final_candidate_id": "001" if status == "completed" else None,
               "execution_plan": {name: {"requested_plugin_id": settings.get(name, {}).get("plugin_id"),
                    "resolved_plugin_id": settings[name]["plugin_id"] if resource_status[name] != "not_available" else None,
                    "status": resource_status[name],
                    "reason": None if resource_status[name] == "available" else "Method supplied Code; compiler is not used."
                    if name == "compiler" and code_level == "factory_contract" else "Resource did not complete successfully."}
                    for name in ["compiler", "model_backend", "solver", "executor"]} if settings_valid else {},
               "artifacts": list(store.refs)}, "bundle")
    store.state["status"] = status
    store.checkpoint()
    return RunResult(store.run_id, store.path, status)


def _prepare_candidate(store: RunStore, problem: Path, config: Path, settings: dict[str, Any],
                 ledger: dict[str, Any], offline: bool, plan: AdmissionPlan) -> tuple[dict[str, Any], dict[str, Any]]:
    method = plan.method
    source_problem = read_public_bytes(problem)
    public = parse_json(source_problem)
    validate_problem(public)
    data_refs = []
    data_content = {}
    for index, data in enumerate(public["data_refs"]):
        raw = read_public_bytes(public_path(problem.parent, data["path"]))
        if data["sha256"] and hashlib.sha256(raw).hexdigest() != data["sha256"]:
            raise RunError("data_hash_mismatch", "validation", "A data file does not match its declared SHA-256.")
        validate_csv(raw, data["schema"])
        ref = store.write(f"data/{index}.csv", raw, data["data_id"])
        data_refs.append(ref)
        data_content[data["data_id"]] = raw
        data["path"] = ref["relative_path"]
        data["sha256"] = ref["sha256"]
    problem_ref = store.json("public-problem.json", public, public["problem_id"])
    store.json("dataset-manifest.json", {"schema_version": "0.2.0", "data": data_refs}, "dataset")
    public_config = deepcopy(settings)
    public_config["store"]["config"]["root"] = "."
    if "response_artifact" in public_config["llm"]["config"]:
        public_config["llm"]["config"]["response_artifact"] = "candidates/001/artifact.json"
    public_config.setdefault("evaluation", {"protocol_id": "llm4om.eval.public-v0.1",
                                            "evaluator_plugin_id": "llm4om.evaluators.structural"})
    store.json("public-config.json", public_config, "config")
    store.json("environment-lock.json", {"schema_version": "0.2.0", "python": platform.python_version(),
               "llm4om": version("llm4om"),
               "packages": {**{name: version(name) for name in ["PyYAML", "jsonschema"]},
                            **plan.snapshot["packages"]},
               "mode": plan.snapshot["mode"],
               "method": {"manifest": method.manifest, "origin": method.origin},
               "method_variant": (method.manifest["source"] or {}).get("variant_id", "grounded_single_candidate")}, "environment")
    if plan.provider is None:
        raise RunError("checkpoint_incompatible", "admission", "Identity-only admission cannot run a method.")
    gateway = plan.provider.gateway(public, hashlib.sha256(source_problem).hexdigest(), store, ledger,
                                    settings["budget"], config.parent, deadline=plan.deadline)
    def save_method_checkpoint(value: dict[str, Any]) -> None:
        if not method.manifest["capabilities"].get("supports_checkpoint"):
            raise RunError("checkpoint_unsupported", "formulation", "Method has no internal checkpoint contract.")
        value = parse_json(json.dumps(value, allow_nan=False).encode())
        if not isinstance(value.get("schema_version"), str):
            raise RunError("checkpoint_incompatible", "formulation", "Method checkpoint must be versioned JSON.")
        store.state["method_checkpoint"] = value
        store.checkpoint()
    context = MethodContext(gateway, MappingProxyType(data_content), MappingProxyType(deepcopy(settings["budget"])),
                            hashlib.sha256(source_problem).hexdigest(), store.cancellation, save_method_checkpoint)
    store.state["method_started"] = True
    store.checkpoint()
    try:
        outcome = method.run(deepcopy(settings["method"]["config"]), deepcopy(public), context,
                             checkpoint=store.state.get("method_checkpoint"))
    finally:
        if isinstance(gateway, Gateway):
            ledger.update(gateway.ledger)
            store.json("llm-trace.json", {"schema_version": "0.2.0", "attempts": gateway.trace}, "llm-trace")
        store.state["ledger"] = ledger
        store.checkpoint()
    if (outcome.status != "candidate_selected" or outcome.final_candidate_id != "001"
            or not isinstance(outcome.proposal, ModelProposal)):
        raise RunError("invalid_method_outcome", "formulation", "This profile requires one selected candidate with ID 001.")
    output = outcome.proposal
    artifact = parse_json(json.dumps(output.artifact, allow_nan=False).encode())
    formulation = parse_json(json.dumps(output.formulation, allow_nan=False).encode())
    factory_profile = plan.snapshot["method_profile"] in ("factory_single_candidate/0.1.0", "native_single_candidate/0.1.0")
    source_ref = None
    if factory_profile and isinstance(output.code, FactoryCodeProposal) and isinstance(output.code.source, str):
        source_ref = store.write("candidates/001/model.py", output.code.source.encode(), "method-source")
        store.json("candidates/001/supplied-formulation.json", formulation, "supplied-formulation")
        store.json("candidates/001/supplied-code.json", {
            "schema_version": output.code.schema_version, "source_ref": source_ref,
            "source_sha256": output.code.source_sha256, "data_bindings": output.code.data_bindings}, "supplied-code")
    validate_model_artifact(artifact)
    validate_bindings(artifact, public)
    validate_formulation(formulation, public)
    if artifact["problem_ref"].get("sha256") != hashlib.sha256(source_problem).hexdigest():
        raise RunError("artifact_problem_mismatch", "formulation", "Method output belongs to another public input.")
    if factory_profile:
        if (output.structured_ir is not None or not isinstance(output.code, FactoryCodeProposal)
                or source_ref is None or output.code.schema_version != "0.1.0" or not output.code.source
                or output.code.representation_kind not in plan.method.manifest["capabilities"]["code_representations"]):
            raise RunError("invalid_method_outcome", "code", "Factory profile requires only a versioned Code proposal.")
        if source_ref["sha256"] != output.code.source_sha256:
            raise RunError("code_hash_mismatch", "code", "Factory proposal source hash differs from its bytes.")
        validate_bindings({"data_bindings": output.code.data_bindings}, public)
        if formulation["structured_ir_ref"] is not None:
            raise RunError("invalid_method_outcome", "formulation", "Factory source Formulation must not claim an original grounded IR.")
    else:
        if output.code is not None or output.structured_ir is None:
            raise RunError("invalid_method_outcome", "formulation", "Grounded profile requires LPIR, not provided Code.")
        ir = parse_json(json.dumps(output.structured_ir, allow_nan=False).encode())
        reject_additional_refs(ir)
        validate_bindings(ir, public)
        if ir.get("problem_id") != public["problem_id"] or ir.get("problem_revision") != public["revision"]:
            raise RunError("artifact_problem_mismatch", "formulation", "Method output belongs to another public input.")
        if (ir.get("schema_version") != "0.1.0" or ir.get("ir_kind") != "grounded_lp"
                or not isinstance(ir.get("model_id"), str) or not ir["model_id"]):
            raise RunError("invalid_method_outcome", "formulation", "Method must supply an identified grounded LPIR 0.1.0.")
        if ir.get("problem_type") not in plan.snapshot["allowed_problem_types"]:
            raise RunError("capability_mismatch", "formulation", "Actual IR type is outside the admitted problem types.")
        formulation["structured_ir_ref"] = store.json("candidates/001/structured-ir.json", ir, ir["model_id"])
    formulation_ref = store.json("candidates/001/formulation.json", formulation, formulation["formulation_id"])
    artifact["problem_ref"] = problem_ref
    artifact["formulation_ref"] = formulation_ref
    if factory_profile:
        assert isinstance(output.code, FactoryCodeProposal)
        code_ref = store.json("candidates/001/code-artifact.json", {
            "schema_version": "0.2.0", "code_id": "method-code-001", "representation_kind": output.code.representation_kind,
            "factory_contract": "native_gurobipy/0.1.0" if output.code.representation_kind == "native_code" else "python_factory/0.1.0", "entry_point": "build_model",
            "representation_ref": source_ref, "model_backend": settings["model_backend"]["plugin_id"],
            "source_formulation_ref": formulation_ref, "data_bindings": output.code.data_bindings,
            "provenance": {"origin": "method_generated", "method": method.manifest,
                           "generation": formulation["provenance"]}}, "method-code-001")
        artifact["code_ref"] = code_ref
        artifact["stage_status"]["code"] = {"status": "available", "reason": None}
    call_ids = [call.call_id for call in gateway.calls]
    artifact["provenance"]["replay"] = {"mode": gateway.calls[-1].evidence_origin if gateway.calls else "no_calls", "call_ids": call_ids,
                                        "response_sha256": gateway.calls[-1].source_sha256 if gateway.calls else None}
    artifact["provenance"]["method"] = {"manifest": method.manifest, "origin": method.origin}
    artifact_ref = store.json("candidates/001/artifact.json" if offline else "candidates/001/formulation-snapshot.json", artifact, artifact["artifact_id"])
    store.json("candidates/001/candidate.json" if offline else "candidates/001/candidate-snapshot.json", {"schema_version": "0.2.0", "candidate_id": "001",
               "run_id": store.run_id, "parent_ids": [], "sequence_no": 1, "artifact_ref": artifact_ref,
               "created_by": {"method_id": settings["method"]["plugin_id"], "method_version": method.manifest["plugin_version"],
                              "variant_id": (method.manifest["source"] or {}).get("variant_id", "grounded_single_candidate"), "call_ids": call_ids,
                              "prompt_hash": None, "role": "formulation"}, "status": "proposed"}, "001")
    ledger["candidates"] = 1
    store.emit("formulation_saved", artifact_ref=artifact_ref, call_ids=call_ids, evidence_origin="method_output")
    stages = {**artifact["stage_status"], "solve": {
        "status": "not_available", "reason": "Solve has not run."}}
    return artifact_ref, stages


def _compile_candidate(store: RunStore, artifact_ref: dict[str, Any], settings: dict[str, Any]) -> tuple[dict[str, Any], CompiledCode | None]:
    artifact = parse_json(read_public_bytes(store.path / artifact_ref["relative_path"]))
    formulation = parse_json(read_public_bytes(store.path / artifact["formulation_ref"]["relative_path"]))
    if artifact["code_ref"] is not None:
        store.emit("code_saved", artifact_ref=artifact_ref, evidence_origin="method_generated")
        return artifact_ref, None
    ir_ref = formulation["structured_ir_ref"]
    ir = parse_json(read_public_bytes(store.path / ir_ref["relative_path"]))
    compiled = compile_ir(ir)
    source_ref = store.write("candidates/001/model.py", compiled.source.encode(), "compiled-source")
    symbols_ref = store.json("candidates/001/symbol-map.json", compiled.symbol_map, "symbol-map")
    code_ref = store.json("candidates/001/code-artifact.json", {
        "schema_version": "0.2.0", "code_id": "compiled-code", "representation_kind": "python_factory",
        "representation_ref": source_ref, "model_backend": settings["model_backend"]["plugin_id"],
        "source_formulation_ref": artifact["formulation_ref"], "data_bindings": artifact["data_bindings"],
        "provenance": {"origin": "deterministic_compilation", "compiler_id": settings["compiler"]["plugin_id"],
                       "compiler_version": "0.1.0", "source_ir_ref": ir_ref, "symbol_map_ref": symbols_ref}}, "compiled-code")
    artifact["artifact_id"] += "-compiled"
    artifact["code_ref"] = code_ref
    artifact["stage_status"]["code"] = {"status": "available", "reason": None}
    artifact_ref = store.json("candidates/001/artifact.json", artifact, artifact["artifact_id"])
    store.emit("code_saved", artifact_ref=artifact_ref)
    store.json("candidates/001/build.json", {"schema_version": "0.2.0", "code_artifact_ref": code_ref,
        "compiler_id": settings["compiler"]["plugin_id"], "compiler_version": "0.1.0",
        "source_ir_ref": ir_ref, "target_backend": settings["model_backend"]["plugin_id"],
        "symbol_map_ref": symbols_ref, "data_bindings": artifact["data_bindings"],
        "diagnostics": [], "compiler_config_sha256": hashlib.sha256(b"{}").hexdigest()}, "build")
    return artifact_ref, compiled


def _execute_candidate(store: RunStore, compiled: CompiledCode | None, artifact_ref: dict[str, Any],
                       settings: dict[str, Any], ledger: dict[str, Any], plan: AdmissionPlan) -> tuple[dict[str, Any] | None, dict[str, Any], RunError | None]:
    started = datetime.now(timezone.utc).isoformat()
    timer = monotonic()
    remaining = plan.deadline - time.time()
    if remaining <= 0:
        raise RunError("deadline_exhausted", "execution", "No shared run deadline remains for Worker execution.")
    if ledger["solver_calls"] >= settings["budget"]["max_solver_calls"]:
        raise RunError("budget_exhausted", "execution", "No shared Solver call slot remains.")
    solver_options = {**settings["solver"].get("options", {})}
    solver_options["time_limit_s"] = min(solver_options.get("time_limit_s", remaining), remaining)
    ledger["solver_calls"] += 1
    input_artifact_ref = artifact_ref
    store.state.update(ledger=ledger, phase="execute_pending", execution_id="execution-001")
    store.checkpoint()
    store.emit("solver_started", solver_id=settings["solver"]["plugin_id"])
    out, err = StringIO(), StringIO()
    error = None
    solve_ref = None
    container = None
    resources = {"cpu_time_s": None, "peak_memory_bytes": None}
    executor_details: dict[str, Any] = {}
    try:
        if settings["executor"]["plugin_id"] == "llm4om.executors.container":
            artifact = parse_json(read_public_bytes(store.path / artifact_ref["relative_path"]))
            formulation = parse_json(read_public_bytes(store.path / artifact["formulation_ref"]["relative_path"]))
            limits = {**settings["executor"]["config"]}
            limits["wall_time_s"] = min(limits["wall_time_s"], remaining)
            if compiled is None:
                code = parse_json(read_public_bytes(store.path / artifact["code_ref"]["relative_path"]))
                source = read_public_bytes(store.path / code["representation_ref"]["relative_path"])
                public = parse_json(read_public_bytes(store.path / "public-problem.json"))
                request = {"kind": code["factory_contract"], "source_sha256": code["representation_ref"]["sha256"],
                    "problem": public, "formulation": formulation, "data_bindings": code["data_bindings"],
                    "data_refs": public["data_refs"], "allowed_problem_types": plan.snapshot["allowed_problem_types"],
                    "solver_options": solver_options, "wall_time_s": limits["wall_time_s"],
                    "output_limit_bytes": min(limits.get("output_limit_bytes", 1024 * 1024), 8 * 1024 * 1024)}
            else:
                ir = parse_json(read_public_bytes(store.path / formulation["structured_ir_ref"]["relative_path"]))
                source = compiled.source.encode()
                request = {"ir": ir, "source_sha256": hashlib.sha256(source).hexdigest(), "solver_options": solver_options}
            inputs = {"request.json": json.dumps(request, ensure_ascii=False, allow_nan=False).encode(), "model.py": source}
            for data in parse_json(read_public_bytes(store.path / "public-problem.json"))["data_refs"]:
                inputs[data["path"]] = read_public_bytes(store.path / data["path"])
            container = run_container(["python", "-I", "-m", "llm4om.worker", "--solve", "/input/request.json", "--solver", settings["solver"]["plugin_id"]],
                inputs, limits, image=plan.snapshot["worker"]["image_id"], deadline=plan.deadline, cancellation=store.cancellation)
            out.write(container.stdout.decode(errors="replace"))
            err.write(container.stderr.decode(errors="replace"))
            if container.status == "cancelled":
                raise RunError("run_cancelled", "execution", "The isolated Worker was cancelled.")
            if container.status in ("timeout", "oom", "output_limit"):
                raise RunError(f"execution_{container.status}", "execution", "The isolated Worker exceeded an enforced resource limit.")
            payload = parse_json(container.stdout)
            validate_worker_response(payload, {name: value for name, value in plan.snapshot["worker"].items()
                if name in ("python", "llm4om", "packages", "solver_environment")},
                solver_id=settings["solver"]["plugin_id"], model_backend=settings["model_backend"]["plugin_id"])
            if "error" in payload:
                raise RunError(payload["error"]["code"], payload["error"]["stage"], payload["error"]["message"])
            if container.status != "completed" or container.exit_code != 0:
                raise RunError("executor_error", "execution", "The isolated Worker failed.")
            if compiled is None:
                exported = payload["factory"]
                view_origin = "native_exported_instance" if code["representation_kind"] == "native_code" else "factory_exported_instance"
                instance = exported["instance"]
                compile_ir(instance)
                validate_bindings(instance, public)
                if (exported["source_sha256"] != request["source_sha256"]
                        or instance["problem_id"] != public["problem_id"] or instance["problem_revision"] != public["revision"]
                        or instance["provenance"]["origin"] != view_origin
                        or set(exported["decision_map"]) != {v["id"] for v in instance["variables"]}):
                    raise RunError("worker_protocol_error", "execution", "Factory instance evidence differs from the admitted binding.")
                view_ref = store.json("candidates/001/factory-instance.json", instance, instance["model_id"])
                map_ref = store.json("candidates/001/decision-map.json", {
                    "schema_version": "0.1.0", "decisions": exported["decision_map"],
                    "source_sha256": exported["source_sha256"], "data_bindings": artifact["data_bindings"],
                    "problem_revision": public["revision"], "origin": view_origin}, "decision-map")
                artifact["optional_views"].append({"origin": view_origin, "artifact_ref": view_ref,
                    "decision_map_ref": map_ref, "source_code_ref": artifact["code_ref"]})
                if view_origin == "native_exported_instance":
                    native_ref = store.write("candidates/001/native-model.mps", base64.b64decode(exported["model_mps"], validate=True), "native-model")
                    artifact["optional_views"][-1]["native_model_ref"] = native_ref
                artifact_ref = store.json("candidates/001/artifact.json", artifact, artifact["artifact_id"])
            elif "factory" in payload:
                raise RunError("worker_protocol_error", "execution", "Grounded solving must not claim a factory export.")
            solve = payload["result"]
            solve["evidence_origin"] = "trusted_container_worker"
            resources = payload["resources"]
        else:
            if compiled is None:
                raise RunError("capability_mismatch", "execution", "Factory code cannot execute on the host.")
            artifact = parse_json(read_public_bytes(store.path / artifact_ref["relative_path"]))
            formulation = parse_json(read_public_bytes(store.path / artifact["formulation_ref"]["relative_path"]))
            ir = parse_json(read_public_bytes(store.path / formulation["structured_ir_ref"]["relative_path"]))
            stdout, stderr, exit_code = run_owned_process(
                [sys.executable, "-m", "llm4om.worker", "--solve-stdin", "--solver", settings["solver"]["plugin_id"]],
                json.dumps({"ir": ir, "source_sha256": hashlib.sha256(compiled.source.encode()).hexdigest(),
                            "solver_options": solver_options}, allow_nan=False).encode(),
                deadline=plan.deadline, cancellation=store.cancellation)
            out.write(stdout.decode(errors="replace"))
            err.write(stderr.decode(errors="replace"))
            payload = parse_json(stdout)
            if "error" in payload:
                raise RunError(payload["error"]["code"], payload["error"]["stage"], payload["error"]["message"])
            if exit_code != 0:
                raise RunError("solver_error", "solve", "The owned Solver child failed.")
            validate_worker_response(payload, payload["runtime"], solver_id=settings["solver"]["plugin_id"],
                                     model_backend=settings["model_backend"]["plugin_id"])
            solve = payload["result"]
            resources = payload["resources"]
            executor_details.update(exit_code=exit_code)
        variables = solve.pop("variables")
        solve["schema_version"] = "0.2.0"
        solve["solution_ref"] = store.json("candidates/001/solution.json", {
            "schema_version": "0.2.0", "variables": variables, "evidence_origin": solve["evidence_origin"]}, "solution") if variables is not None else None
        solve_ref = store.json("candidates/001/solve-result.json", solve, "solve-result")
        if solve["termination"] == "error":
            error = RunError("solver_error", "solve", "Solver reports an execution error.")
    except RunError as failure:
        error = failure
        if failure.details is not None:
            executor_details = failure.details or {}
            out.write(executor_details.get("stdout", ""))
            err.write(executor_details.get("stderr", ""))
    except (RuntimeError, ArithmeticError) as failure:
        error = RunError("solver_error", "solve", "Cannot build or solve the compiled model.")
    except (ValueError, KeyError, TypeError):
        error = RunError("worker_protocol_error", "execution", "Worker result does not match the declared protocol.")
    output_ref = store.write("candidates/001/stdout.txt", out.getvalue().encode(), "stdout")
    stderr_ref = store.write("candidates/001/stderr.txt", err.getvalue().encode(), "stderr")
    execution_ref = store.json("candidates/001/execution.json", {"schema_version": "0.2.0",
        "run_id": store.run_id, "input_artifact_ref": input_artifact_ref, "artifact_ref": artifact_ref,
        "solver_call": ledger["solver_calls"],
        "execution_id": "execution-001", "mode": settings["executor"]["plugin_id"].removeprefix("llm4om.executors."), "status": "cancelled" if error and error.code == "run_cancelled" else "failed" if error else "completed",
        "start": started, "end": datetime.now(timezone.utc).isoformat(),
        "worker_status": container.status if container else executor_details.get("status"),
        "exit_code": container.exit_code if container else executor_details.get("exit_code"),
        "wall_time_s": monotonic() - timer, "resources": resources,
        "output_truncated": container.output_truncated if container else executor_details.get("output_truncated", False),
        "image_id": container.image_id if container else executor_details.get("image_id"),
        "container_id": container.container_id if container else executor_details.get("container_id"),
        "container_name": executor_details.get("container_name"),
        "oom_killed": container.oom_killed if container else executor_details.get("oom_killed"),
        "oom_evidence": container.oom_evidence if container else executor_details.get("oom_evidence"),
        "restrictions": container.restrictions if container else executor_details.get("restrictions"),
        "executor_diagnostics": list(container.diagnostics) if container else executor_details.get("diagnostics", []),
        "solve_result_ref": solve_ref, "stdout_ref": output_ref,
        "stderr_ref": stderr_ref, "diagnostics": [{"code": error.code, "stage": error.stage}] if error else []}, "execution-001")
    candidate = parse_json(read_public_bytes(store.path / "candidates/001/candidate-snapshot.json"))
    candidate.update(artifact_ref=artifact_ref, status="executed" if error else "selected")
    store.json("candidates/001/candidate.json", candidate, "001")
    store.state.update(executed_artifact_ref=artifact_ref, artifact_ref=artifact_ref,
                       solve_ref=solve_ref, execution_ref=execution_ref,
                       phase="execute_done" if solve_ref is not None and error is None else "code_done")
    store.checkpoint()
    if solve_ref is not None:
        store.emit("solver_finished", solve_result_ref=solve_ref, termination=solve["termination"])
    return solve_ref, execution_ref, error


def _restored_compilation(store: RunStore, artifact_ref: dict[str, Any]) -> CompiledCode | None:
    artifact = parse_json(read_public_bytes(store.path / artifact_ref["relative_path"]))
    code = parse_json(read_public_bytes(store.path / artifact["code_ref"]["relative_path"]))
    if code["provenance"]["origin"] != "deterministic_compilation":
        return None
    ir = parse_json(read_public_bytes(store.path / code["provenance"]["source_ir_ref"]["relative_path"]))
    return compile_ir(ir)


def _reconcile_execution(store: RunStore, settings: dict[str, Any]) -> None:
    records = store.interrupted_publications.get("candidates/001/execution.json", [])
    if store.state["phase"] != "execute_pending" or not records:
        return
    try:
        visited: set[str] = set()
        def verify(value: Any) -> None:
            if isinstance(value, dict):
                if {"relative_path", "namespace", "sha256"} <= value.keys():
                    if value not in store.refs or value.get("namespace") != "run_public":
                        raise ValueError("Result refers to an unverified artifact.")
                    if value["relative_path"] not in visited:
                        visited.add(value["relative_path"])
                        if value["media_type"] == "application/json":
                            verify(load(value))
                else:
                    for item in value.values():
                        verify(item)
            elif isinstance(value, list):
                for item in value:
                    verify(item)
        def load(ref: dict[str, Any]) -> dict[str, Any]:
            return parse_json(read_public_bytes(public_path(store.path, ref["relative_path"])))
        execution_ref = records[-1]
        verify(execution_ref)
        execution = load(execution_ref)
        if execution["status"] != "completed":
            return
        artifact_ref = execution["artifact_ref"]
        artifact = load(artifact_ref)
        original = load(store.state["artifact_ref"])
        mode = settings["executor"]["plugin_id"].removeprefix("llm4om.executors.")
        if (execution["run_id"] != store.run_id or execution["execution_id"] != store.state["execution_id"]
                or execution["solver_call"] != store.state["ledger"]["solver_calls"]
                or execution["input_artifact_ref"] != store.state["artifact_ref"]
                or {key: value for key, value in artifact.items() if key != "optional_views"}
                   != {key: value for key, value in original.items() if key != "optional_views"}
                or execution["mode"] != mode or execution["exit_code"] != 0
                or execution["diagnostics"]):
            raise ValueError("Completed execution identity differs from the admitted candidate.")
        solve_ref = execution["solve_result_ref"]
        solve = load(solve_ref)
        expected_origin = ("trusted_container_worker" if mode == "container" else
                           "trusted_gurobi_api" if settings["solver"]["plugin_id"] == "llm4om.solvers.gurobi" else "trusted_highs_api")
        if solve["termination"] == "error" or solve["evidence_origin"] != expected_origin:
            raise ValueError("Execution has no completed trusted Solver result.")
        runtime = {"packages": store.state["admission"]["packages"]}
        if mode == "container" and execution["image_id"] != store.state["admission"]["worker"]["image_id"]:
            raise ValueError("Completed execution used another Worker.")
        result = {key: value for key, value in solve.items() if key not in ("schema_version", "solution_ref")}
        result["variables"] = load(solve["solution_ref"])["variables"] if solve["solution_ref"] is not None else None
        result["evidence_origin"] = "trusted_gurobi_api" if settings["solver"]["plugin_id"] == "llm4om.solvers.gurobi" else "trusted_highs_api"
        validate_worker_response({"schema_version": "0.2.0", "runtime": runtime, "result": result,
                                  "resources": execution["resources"]}, runtime,
                                 solver_id=settings["solver"]["plugin_id"], model_backend=settings["model_backend"]["plugin_id"])
        store.accept_publications()
        candidate = load(store.projections["candidates/001/candidate-snapshot.json"])
        candidate.update(artifact_ref=artifact_ref, status="selected")
        store.json("candidates/001/candidate.json", candidate, "001")
        store.state.update(artifact_ref=artifact_ref, executed_artifact_ref=artifact_ref,
                           solve_ref=solve_ref, execution_ref=execution_ref, phase="execute_done")
        store.checkpoint()
    except (RunError, ValueError, KeyError, TypeError) as error:
        raise RunError("checkpoint_incompatible", "admission", "Cannot reconcile the completed candidate execution.") from error


def _sdk_sha256() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def resume_run(run: Path, *, cancellation: CancellationToken | None = None,
               strategy: str = "continue") -> RunResult:
    """Continue fixed work, or explicitly start a derived semantic rerun with carried usage."""
    if strategy not in {"continue", "rerun"}:
        raise RunError("invalid_resume_strategy", "admission", "Resume strategy must be continue or rerun.")
    store = RunStore(run.parent, resume=run, cancellation=cancellation if strategy == "continue" else None)
    try:
        if store.state.get("sdk") != version("llm4om"):
            raise RunError("checkpoint_incompatible", "admission", "SDK version differs from the saved run.")
        if "sources" not in store.state or "admission" not in store.state:
            raise RunError("checkpoint_unsupported", "admission", "Run did not reach a resumable admitted checkpoint.")
        for path, digest in store.state["sources"].items():
            if hashlib.sha256(read_public_bytes(Path(path))).hexdigest() != digest:
                raise RunError("checkpoint_incompatible", "admission", "Original public input or configuration changed.")
        resource_records: list[dict[str, Any]] = []
        settings = read_config(Path(store.state["config"]))
        if "gateway_sha256" in store.state:
            archive = store.path.parent / ".private" / store.run_id
            resources = Gateway.recover(archive, expected_sha256=store.state["gateway_sha256"],
                budget=settings["budget"], deadline=store.state["deadline"],
                inherited_ledger=store.state.get("inherited_ledger", {}))
            store.state["ledger"].update(resources.ledger)
            resource_records = resources.trace
        host = {"python": platform.python_version(), "sdk_sha256": _sdk_sha256(), "packages": {name: version(name) for name in ("PyYAML", "jsonschema")}}
        if host != store.state.get("host"):
            raise RunError("checkpoint_incompatible", "admission", "Host Python or package identity changed.")
        # Completed runs validate identity without consuming a new runtime probe or deadline.
        saved_deadline = store.state["deadline"]
        plan = prepare_run(settings, offline=store.state["offline"], config_dir=Path(store.state["config"]).parent,
                           deadline=max(saved_deadline, time.time() + 5) if strategy == "rerun" or store.state.get("status") in ("completed", "artifact_ready") else saved_deadline,
                           cancellation=store.cancellation, expected=store.state["admission"],
                           identity_only=strategy == "rerun" or store.state.get("status") in ("completed", "artifact_ready"))
        if plan.snapshot != store.state["admission"]:
            raise RunError("checkpoint_incompatible", "admission", "Saved resource identity differs from admission.")
        if strategy == "rerun":
            child = RunStore(run.parent, cancellation=cancellation)
            try:
                parent_refs = [child.write("parent/" + store.run_id + "/" + ref["relative_path"],
                    read_public_bytes(public_path(store.path, ref["relative_path"])), ref["artifact_id"],
                    ref.get("schema_version")) for ref in store.refs]
                parent_checkpoint_ref = child.write("parent/" + store.run_id + "/checkpoint.json",
                    read_public_bytes(store.path / "checkpoint.json"), "parent-checkpoint", "0.1.0")
                ledger = deepcopy(store.state["ledger"])
                lineage_ref = child.json("lineage.json", {"schema_version": "0.1.0",
                    "operation": "derived_rerun", "parent_run_id": store.run_id,
                    "parent_budget_ledger": ledger, "input_hashes": store.state["sources"],
                    "parent_checkpoint_ref": parent_checkpoint_ref,
                    "parent_artifacts": parent_refs, "parent_resource_records": resource_records, "reused_records": [],
                    "policy": "Fresh method execution; previous paid/unknown usage and reservations count against the configured caps."}, "lineage")
                child.state.update(lineage_ref=lineage_ref, inherited_ledger=ledger, ledger=deepcopy(ledger))
                return _run_problem(Path(store.state["problem"]), Path(store.state["config"]), child,
                                    offline=store.state["offline"])
            finally:
                child.close()
        if store.state.get("status") in ("completed", "artifact_ready"):
            return RunResult(store.run_id, store.path, store.state["status"])
        if time.time() >= store.state["deadline"]:
            raise RunError("deadline_exhausted", "admission", "The original absolute run deadline expired.")
        if (store.state.get("artifact_ref") is None and store.state.get("method_checkpoint") is None
                and store.state.get("method_started")):
            raise RunError("checkpoint_unsupported", "admission", "No completed stage or supported internal method checkpoint exists.")
        _reconcile_execution(store, settings)
        store.interrupted_publications = {}
        return _run_problem(Path(store.state["problem"]), Path(store.state["config"]), store,
                            offline=store.state["offline"], restored_plan=plan)
    finally:
        store.close()
