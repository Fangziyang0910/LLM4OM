"""Replay a public Formulation and optionally compile and solve its grounded IR."""

import hashlib
import json
import platform
from copy import deepcopy
from importlib.metadata import version
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from types import MappingProxyType
from typing import Any

from llm4om.contracts import (
    RunError, parse_json, public_path, read_config, read_public_bytes, validate_config, validate_csv, validate_problem,
    validate_model_artifact, validate_formulation, validate_bindings, reject_additional_refs,
    validate_worker_response,
)
from llm4om.mock import MockGateway
from llm4om.methods import MethodContext, ModelProposal
from llm4om.preflight import AdmissionPlan, prepare_run
from llm4om.linear import CompiledCode, compile_ir
from llm4om.highs import solve_highs
from llm4om.storage import RunStore
from llm4om.executors import run_container


@dataclass(frozen=True)
class RunResult:
    run_id: str
    bundle_path: Path
    status: str


def run_problem(problem: Path, config: Path, *, offline: bool = False,
                output_root: Path | None = None) -> RunResult:
    settings: dict[str, Any] = {}
    config_error: Exception | None = None
    try:
        settings = read_config(config)
        configured_root = config.parent / settings["store"]["config"]["root"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        config_error = error
        configured_root = Path.cwd() / "runs"
    mode = "offline_mock" if offline else "not_resolved"
    store = RunStore(output_root or configured_root)
    store.emit("run_started", mode=mode)
    ledger: dict[str, Any] = {"schema_version": "0.2.0", "llm_attempts": 0,
                             "solver_calls": 0, "external_llm_requests": 0, "candidates": 0, "total_tokens": None,
                             "cost": 0, "evidence_origin": "mock_fixture"}
    error_record: dict[str, Any] | None = None
    artifact_ref = None
    settings_valid = False
    solve_ref = None
    execution_ref = None
    admission_ref = None
    requested_config_ref = None
    stages: dict[str, Any] = {name: {"status": "not_available", "reason": "Stage has not run."}
              for name in ("formulation", "code", "solve")}
    try:
        if config_error:
            if isinstance(config_error, RunError):
                raise config_error
            raise RunError("invalid_config", "validation", "Cannot read a valid RunConfig.")
        requested_config_ref = store.json("requested-config.json", settings, "requested-config")
        validate_config(settings)
        settings_valid = True
        plan = prepare_run(settings, offline=offline)
        admission_ref = store.json("admission-plan.json", plan.snapshot, "admission-plan")
        mode = plan.snapshot["mode"]
        artifact_ref, stages = _prepare_candidate(store, problem, config, settings, ledger, offline, plan)
        status = "artifact_ready"
        if not offline:
            artifact_ref, compiled = _compile_candidate(store, artifact_ref, settings)
            stages["code"] = {"status": "available", "reason": None}
            solve_ref, execution_ref, execution_error = _execute_candidate(store, compiled, artifact_ref, settings, ledger, plan)
            if solve_ref is not None:
                stages["solve"] = {"status": "available", "reason": None}
            if execution_error is not None:
                raise execution_error
            stages["solve"] = {"status": "available", "reason": None}
            status = "completed"
    except (RunError, ValueError, KeyError, TypeError) as error:
        status = "failed"
        error_record = {"code": error.code if isinstance(error, RunError) else "invalid_input",
                        "stage": error.stage if isinstance(error, RunError) else "validation",
                        "message": str(error) if isinstance(error, RunError) else "Cannot process the public input or Mock artifact."}
        if isinstance(error, RunError) and error.details is not None:
            error_record["details_ref"] = store.json("diagnostics/plugin-error.json", error.details, "plugin-error")
    if stages["formulation"]["status"] == "available":
        store.json("evaluation.json", {"schema_version": "0.2.0", "protocol_id": "llm4om.eval.public-v0.1",
                   "formulation_validation": {"status": "pass", "level": "structural"},
                   "code_validation": {"status": "pass", "level": "deterministic_compilation"}
                                      if stages["code"]["status"] == "available" else {"status": "not_available"},
                   "semantic_validation": {"status": "not_available"}}, "evaluation")
    store.json("budget-ledger.json", ledger, "budget")
    store.emit("run_finished", status=status, error=error_record)
    if settings_valid and any(reporter["plugin_id"] == "llm4om.reporters.markdown" for reporter in settings.get("reporters", [])):
        report = (f"# LLM4OM run {store.run_id}\n\nMode: {mode}. Status: {status}.\n\n"
                  "| Stage | Status |\n|---|---|\n" +
                  "".join(f"| {name} | {stage['status']} |\n" for name, stage in stages.items()) +
                  f"\nMethod: {settings['method']['plugin_id']}. Provider: Mock. External LLM requests: 0.\n"
                  "Structural checks do not establish semantic correctness.\n")
        if solve_ref is not None:
            solve_summary = parse_json(read_public_bytes(store.path / solve_ref["relative_path"]))
            report += f"\nHiGHS: {solve_summary['termination']}. Objective: {solve_summary['objective_value']}.\n"
        if error_record:
            report += f"\nError: {error_record['code']} ({error_record['stage']}).\n"
        store.write("reports/report.md", report.encode(), "report")
    resource_status = {"compiler": "available" if stages["code"]["status"] == "available" else "not_available",
                       **{name: "available" if solve_ref is not None else "failed" if execution_ref is not None else "not_available"
                          for name in ("model_backend", "solver", "executor")}}
    store.json("bundle.json", {"schema_version": "0.2.0", "run_id": store.run_id,
               "mode": mode, "status": status, "stages": stages,
               "error": error_record, "model_artifact_ref": artifact_ref, "solve_result_ref": solve_ref,
               "execution_result_ref": execution_ref,
               "admission_plan_ref": admission_ref,
               "requested_config_ref": requested_config_ref,
               "final_candidate_id": "001" if status == "completed" else None,
               "execution_plan": {name: {"requested_plugin_id": settings.get(name, {}).get("plugin_id"),
                    "resolved_plugin_id": settings[name]["plugin_id"] if resource_status[name] != "not_available" else None,
                    "status": resource_status[name],
                    "reason": None if resource_status[name] == "available" else "Resource did not complete successfully."}
                    for name in ["compiler", "model_backend", "solver", "executor"]} if settings_valid else {},
               "artifacts": list(store.refs)}, "bundle")
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
    response = public_path(config.parent, settings["llm"]["config"]["response_artifact"])
    gateway = MockGateway(response, public, hashlib.sha256(source_problem).hexdigest(), store, ledger,
                          settings["budget"]["max_llm_attempts"])
    context = MethodContext(gateway, MappingProxyType(data_content), MappingProxyType(deepcopy(settings["budget"])),
                            hashlib.sha256(source_problem).hexdigest())
    outcome = method.run(deepcopy(settings["method"]["config"]), deepcopy(public), context)
    if (outcome.status != "candidate_selected" or outcome.final_candidate_id != "001"
            or not isinstance(outcome.proposal, ModelProposal)):
        raise RunError("invalid_method_outcome", "formulation", "This profile requires one selected candidate with ID 001.")
    output = outcome.proposal
    artifact = parse_json(json.dumps(output.artifact, allow_nan=False).encode())
    formulation = parse_json(json.dumps(output.formulation, allow_nan=False).encode())
    ir = parse_json(json.dumps(output.structured_ir, allow_nan=False).encode())
    validate_model_artifact(artifact)
    validate_bindings(artifact, public)
    validate_formulation(formulation, public)
    reject_additional_refs(ir)
    validate_bindings(ir, public)
    if (artifact["problem_ref"].get("sha256") != hashlib.sha256(source_problem).hexdigest()
            or ir.get("problem_id") != public["problem_id"] or ir.get("problem_revision") != public["revision"]):
        raise RunError("artifact_problem_mismatch", "formulation", "Method output belongs to another public input.")
    if (ir.get("schema_version") != "0.1.0" or ir.get("ir_kind") != "grounded_lp"
            or not isinstance(ir.get("model_id"), str) or not ir["model_id"]):
        raise RunError("invalid_method_outcome", "formulation", "Method must supply an identified grounded LPIR 0.1.0.")
    if ir.get("problem_type") not in plan.snapshot["allowed_problem_types"]:
        raise RunError("capability_mismatch", "formulation", "Actual IR type is outside the admitted problem types.")
    ir_ref = formulation["structured_ir_ref"]
    formulation["structured_ir_ref"] = store.json(
        "candidates/001/structured-ir.json", ir, ir["model_id"])
    formulation_ref = store.json("candidates/001/formulation.json", formulation, formulation["formulation_id"])
    artifact["problem_ref"] = problem_ref
    artifact["formulation_ref"] = formulation_ref
    call_ids = [call.call_id for call in gateway.calls]
    artifact["provenance"]["replay"] = {"mode": "offline_mock", "call_ids": call_ids,
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


def _compile_candidate(store: RunStore, artifact_ref: dict[str, Any], settings: dict[str, Any]) -> tuple[dict[str, Any], CompiledCode]:
    artifact = parse_json(read_public_bytes(store.path / artifact_ref["relative_path"]))
    formulation = parse_json(read_public_bytes(store.path / artifact["formulation_ref"]["relative_path"]))
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


def _execute_candidate(store: RunStore, compiled: CompiledCode, artifact_ref: dict[str, Any],
                       settings: dict[str, Any], ledger: dict[str, Any], plan: AdmissionPlan) -> tuple[dict[str, Any] | None, dict[str, Any], RunError | None]:
    started = datetime.now(timezone.utc).isoformat()
    timer = monotonic()
    ledger["solver_calls"] += 1
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
            ir = parse_json(read_public_bytes(store.path / formulation["structured_ir_ref"]["relative_path"]))
            request = {"ir": ir, "source_sha256": hashlib.sha256(compiled.source.encode()).hexdigest(),
                       "solver_options": settings["solver"].get("options", {})}
            limits = settings["executor"]["config"]
            inputs = {"request.json": json.dumps(request, ensure_ascii=False, allow_nan=False).encode(),
                      "model.py": compiled.source.encode()}
            for data in parse_json(read_public_bytes(store.path / "public-problem.json"))["data_refs"]:
                inputs[data["path"]] = read_public_bytes(store.path / data["path"])
            container = run_container(["python", "-I", "-m", "llm4om.worker", "--solve", "/input/request.json"],
                                      inputs, limits, image=plan.snapshot["worker"]["image_id"])
            out.write(container.stdout.decode(errors="replace"))
            err.write(container.stderr.decode(errors="replace"))
            if container.status in ("timeout", "oom", "output_limit"):
                raise RunError(f"execution_{container.status}", "execution", "The isolated Worker exceeded an enforced resource limit.")
            payload = parse_json(container.stdout)
            validate_worker_response(payload, {name: plan.snapshot["worker"][name] for name in ("python", "llm4om", "packages")})
            if "error" in payload:
                raise RunError(payload["error"]["code"], payload["error"]["stage"], payload["error"]["message"])
            if container.status != "completed" or container.exit_code != 0:
                raise RunError("executor_error", "execution", "The isolated Worker failed.")
            solve = payload["result"]
            solve["evidence_origin"] = "trusted_container_worker"
            resources = payload["resources"]
        else:
            with redirect_stdout(out), redirect_stderr(err):
                solve = solve_highs(compiled, settings["solver"].get("options", {}))
        variables = solve.pop("variables")
        solve["schema_version"] = "0.2.0"
        solve["solution_ref"] = store.json("candidates/001/solution.json", {
            "schema_version": "0.2.0", "variables": variables, "evidence_origin": solve["evidence_origin"]}, "solution") if variables is not None else None
        solve_ref = store.json("candidates/001/solve-result.json", solve, "solve-result")
        store.emit("solver_finished", solve_result_ref=solve_ref, termination=solve["termination"])
        if solve["termination"] == "error":
            error = RunError("solver_error", "solve", "HiGHS reports an execution error.")
    except RunError as failure:
        error = failure
        if failure.code == "executor_error":
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
        "execution_id": "execution-001", "mode": settings["executor"]["plugin_id"].removeprefix("llm4om.executors."), "status": "failed" if error else "completed",
        "start": started, "end": datetime.now(timezone.utc).isoformat(),
        "worker_status": container.status if container else executor_details.get("status"),
        "exit_code": container.exit_code if container else executor_details.get("exit_code"),
        "wall_time_s": monotonic() - timer, "resources": resources,
        "output_truncated": container.output_truncated if container else executor_details.get("output_truncated", False),
        "image_id": container.image_id if container else executor_details.get("image_id"),
        "container_id": container.container_id if container else executor_details.get("container_id"),
        "container_name": executor_details.get("container_name"),
        "oom_killed": container.oom_killed if container else executor_details.get("oom_killed"),
        "restrictions": container.restrictions if container else executor_details.get("restrictions"),
        "executor_diagnostics": list(container.diagnostics) if container else executor_details.get("diagnostics", []),
        "solve_result_ref": solve_ref, "stdout_ref": output_ref,
        "stderr_ref": stderr_ref, "diagnostics": [{"code": error.code, "stage": error.stage}] if error else []}, "execution-001")
    candidate = parse_json(read_public_bytes(store.path / "candidates/001/candidate-snapshot.json"))
    candidate.update(artifact_ref=artifact_ref, status="executed" if error else "selected")
    store.json("candidates/001/candidate.json", candidate, "001")
    return solve_ref, execution_ref, error
