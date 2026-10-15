"""Shared proposal persistence, compilation, execution and stage-recovery pipeline."""

import base64
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from time import monotonic
from io import StringIO
from typing import Any

from llm4om.compilers import resolve_compiler, compiler_identity
from llm4om.contracts import (RunError, parse_json, public_path, read_public_bytes,
    validate_model_artifact, validate_formulation, validate_bindings, reject_additional_refs,
    validate_worker_response)
from llm4om.linear import CompiledCode, compile_ir
from llm4om.methods import ModelProposal, FactoryCodeProposal, ScriptCodeProposal
from llm4om.preflight import AdmissionPlan
from llm4om.run_records import load_run_record
from llm4om.script_execution import ScriptExecutions
from llm4om.storage import RunStore


def persist_proposal(store: RunStore, output: ModelProposal, public: dict[str, Any],
                      problem_ref: dict[str, Any], problem_sha256: str, settings: dict[str, Any],
                      offline: bool, plan: AdmissionPlan, replay: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    check_id = store.state.get("check_id", "001")
    method = plan.method
    artifact = parse_json(json.dumps(output.artifact, allow_nan=False).encode())
    formulation = parse_json(json.dumps(output.formulation, allow_nan=False).encode()) if output.formulation is not None else None
    factory_profile = plan.snapshot["method_profile"] in ("factory_single/0.2.0", "factory_checked/0.2.0", "native_single/0.2.0", "native_checked/0.2.0", "native_script/0.1.0", "native_script/0.2.0")
    source_ref = None
    if factory_profile and isinstance(output.code, (FactoryCodeProposal, ScriptCodeProposal)) and isinstance(output.code.source, str):
        source_ref = store.write(f"checks/{check_id}/model.py", output.code.source.encode(), "method-source")
        if formulation is not None:
            store.json(f"checks/{check_id}/supplied-formulation.json", formulation, "supplied-formulation")
        store.json(f"checks/{check_id}/supplied-code.json", {
            "schema_version": output.code.schema_version, "source_ref": source_ref,
            "source_sha256": output.code.source_sha256, "data_bindings": output.code.data_bindings}, "supplied-code")
    validate_model_artifact(artifact)
    validate_bindings(artifact, public)
    if formulation is None:
        if plan.snapshot["method_profile"] != "native_script/0.2.0" or artifact["stage_status"]["formulation"]["status"] != "not_available":
            raise RunError("invalid_method_outcome", "formulation", "This admitted profile requires a supplied Formulation.")
    else:
        validate_formulation(formulation, public)
        if formulation["representation_kind"] not in plan.method.manifest["capabilities"]["formulation_representations"]:
            raise RunError("capability_mismatch", "formulation", "Supplied Formulation is outside the declared representations.")
        if artifact["stage_status"]["formulation"]["status"] != "available":
            raise RunError("invalid_method_outcome", "formulation", "Supplied Formulation must be recorded as available.")
    if artifact["problem_ref"].get("sha256") != problem_sha256:
        raise RunError("artifact_problem_mismatch", "formulation", "Method output belongs to another public input.")
    if factory_profile:
        if (output.structured_ir is not None or not isinstance(output.code, (FactoryCodeProposal, ScriptCodeProposal))
                or source_ref is None or output.code.schema_version != "0.1.0" or not output.code.source
                or output.code.representation_kind not in plan.method.manifest["capabilities"]["code_representations"]):
            raise RunError("invalid_method_outcome", "code", "Factory profile requires only a versioned Code proposal.")
        if source_ref["sha256"] != output.code.source_sha256:
            raise RunError("code_hash_mismatch", "code", "Factory proposal source hash differs from its bytes.")
        validate_bindings({"data_bindings": output.code.data_bindings}, public)
        if formulation is not None and formulation["structured_ir_ref"] is not None:
            raise RunError("invalid_method_outcome", "formulation", "Factory source Formulation must not claim an original grounded IR.")
    else:
        assert formulation is not None
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
        formulation["structured_ir_ref"] = store.json(f"checks/{check_id}/structured-ir.json", ir, ir["model_id"])
    formulation_ref = None
    if (plan.snapshot["method_profile"] in ("factory_checked/0.2.0", "native_checked/0.2.0")
            and artifact["provenance"].get("repair", {}).get("stage") == "code"):
        parents = store.state.get("check_parent_ids", [])
        if len(parents) != 1:
            raise RunError("invalid_code_repair", "formulation", "Code-only repair requires exactly one source check.")
        parent = store.state["checks"][parents[0]]
        checked = load_run_record(store, parent["result_ref"])
        parent_artifact = load_run_record(store, checked["artifact_ref"]) if checked["artifact_ref"] else None
        if parent_artifact is None or parent_artifact["formulation_ref"] is None:
            raise RunError("invalid_code_repair", "formulation", "Code-only repair requires an available source Formulation.")
        original = load_run_record(store, parent_artifact["formulation_ref"])
        if formulation is None or any(formulation[key] != original[key] for key in (
                "representation", "representation_kind", "problem_id", "problem_revision", "data_bindings")):
            raise RunError("invalid_code_repair", "formulation", "Code-only repair changed the source Formulation or data identity.")
        formulation_ref = parent_artifact["formulation_ref"]
    elif formulation is not None:
        formulation_ref = store.json(f"checks/{check_id}/formulation.json", formulation, formulation["formulation_id"])
    artifact["problem_ref"] = problem_ref
    artifact["formulation_ref"] = formulation_ref
    if factory_profile:
        assert isinstance(output.code, (FactoryCodeProposal, ScriptCodeProposal))
        code_ref = store.json(f"checks/{check_id}/code-artifact.json", {
            "schema_version": "0.2.0", "code_id": "method-code-001", "representation_kind": output.code.representation_kind,
            "factory_contract": "native_script/0.1.0" if isinstance(output.code, ScriptCodeProposal) else "native_gurobipy/0.1.0" if output.code.representation_kind == "native_code" else "python_factory/0.1.0",
            "entry_point": "code.py" if isinstance(output.code, ScriptCodeProposal) else "build_model",
            **({"data_json_ref": store.write(f"checks/{check_id}/data.json", output.code.data_json, "script-data"),
                "execution_id": output.execution_id} if isinstance(output.code, ScriptCodeProposal) else {}),
            "representation_ref": source_ref, "model_backend": settings["model_backend"]["plugin_id"],
            "source_formulation_ref": formulation_ref, "data_bindings": output.code.data_bindings,
            "provenance": {"origin": "method_generated", "method": method.manifest,
                           "generation": artifact["provenance"]}}, "method-code-001")
        artifact["code_ref"] = code_ref
        artifact["stage_status"]["code"] = {"status": "available", "reason": None}
    artifact["provenance"]["replay"] = replay
    artifact["provenance"]["method"] = {"manifest": method.manifest, "origin": method.origin}
    artifact_ref = store.json(f"checks/{check_id}/artifact.json" if offline else f"checks/{check_id}/formulation-snapshot.json", artifact, artifact["artifact_id"])
    return artifact_ref, save_formulation(store, artifact_ref, artifact)


def save_formulation(store: RunStore, artifact_ref: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    check_id = store.state.get("check_id", "001")
    method = artifact["provenance"]["method"]["manifest"]
    call_ids = artifact["provenance"]["replay"]["call_ids"]
    store.json(f"checks/{check_id}/record.json" if store.state["offline"] else f"checks/{check_id}/record-snapshot.json", {
        "schema_version": "0.2.0", "check_id": check_id, "run_id": store.run_id, "parent_ids": store.state.get("check_parent_ids", []),
        "change_reason": store.state.get("check_change_reason"),
        "sequence_no": max(1, store.state["ledger"]["checks"]), "artifact_ref": artifact_ref,
        "created_by": {"method_id": method["plugin_id"], "method_version": method["plugin_version"],
                       "variant_id": (method["source"] or {}).get("variant_id", "grounded_single"),
                       "call_ids": call_ids, "prompt_hash": None,
                       "role": artifact["provenance"].get("repair", {}).get("stage", "formulation" if artifact["formulation_ref"] is not None else "code")}, "status": "proposed"}, check_id)
    if not store.state.get("check_pending"):
        store.state["ledger"]["checks"] = max(1, store.state["ledger"]["checks"])
    stages = {**artifact["stage_status"], "solve": {"status": "not_available", "reason": "Solve has not run."}}
    store.state.update(artifact_ref=artifact_ref, stages=stages, phase="method_done")
    store.emit("formulation_saved" if artifact["formulation_ref"] is not None else "code_output_saved",
               artifact_ref=artifact_ref, call_ids=call_ids, evidence_origin="method_output")
    return stages


def compile_model(store: RunStore, artifact_ref: dict[str, Any], settings: dict[str, Any]) -> tuple[dict[str, Any], CompiledCode | None]:
    check_id = store.state.get("check_id", "001")
    artifact = parse_json(read_public_bytes(store.path / artifact_ref["relative_path"]))
    if artifact["code_ref"] is not None:
        return artifact_ref, None
    formulation = parse_json(read_public_bytes(store.path / artifact["formulation_ref"]["relative_path"]))
    ir_ref = formulation["structured_ir_ref"]
    ir = parse_json(read_public_bytes(store.path / ir_ref["relative_path"]))
    compiler = resolve_compiler(settings["compiler"], settings["model_backend"]["plugin_id"], expected=store.state["admission"]["compiler"])
    compiled = compiler.compile(ir)
    source_ref = store.write(f"checks/{check_id}/model.py", compiled.source.encode(), "compiled-source")
    symbols_ref = store.json(f"checks/{check_id}/symbol-map.json", compiled.symbol_map, "symbol-map")
    code_ref = store.json(f"checks/{check_id}/code-artifact.json", {
        "schema_version": "0.2.0", "code_id": "compiled-code", "representation_kind": "python_factory",
        "representation_ref": source_ref, "model_backend": settings["model_backend"]["plugin_id"],
        "source_formulation_ref": artifact["formulation_ref"], "data_bindings": artifact["data_bindings"],
        "provenance": {"origin": "deterministic_compilation", "compiler_id": settings["compiler"]["plugin_id"],
                       "compiler_version": compiler.binding["manifest"]["plugin_version"], "source_ir_ref": ir_ref, "symbol_map_ref": symbols_ref,
                       "compiler_identity": compiler_identity(compiler.binding)}}, "compiled-code")
    artifact["artifact_id"] += "-compiled"
    artifact["code_ref"] = code_ref
    artifact["stage_status"]["code"] = {"status": "available", "reason": None}
    artifact_ref = store.json(f"checks/{check_id}/artifact.json", artifact, artifact["artifact_id"])
    store.json(f"checks/{check_id}/build.json", {"schema_version": "0.2.0", "code_artifact_ref": code_ref,
        "compiler_id": settings["compiler"]["plugin_id"], "compiler_version": compiler.binding["manifest"]["plugin_version"],
        "source_ir_ref": ir_ref, "target_backend": settings["model_backend"]["plugin_id"],
        "symbol_map_ref": symbols_ref, "data_bindings": artifact["data_bindings"],
        "diagnostics": [], "compiler_config_sha256": hashlib.sha256(json.dumps(compiler.binding["config"], sort_keys=True).encode()).hexdigest()}, "build")
    return artifact_ref, compiled


def execute_model(store: RunStore, compiled: CompiledCode | None, artifact_ref: dict[str, Any],
                       settings: dict[str, Any], ledger: dict[str, Any], plan: AdmissionPlan) -> tuple[dict[str, Any] | None, dict[str, Any], RunError | None]:
    executor = plan.executor
    if executor is None:
        raise RunError("executor_unavailable", "execution", "An admitted Executor is required.")
    check_id = store.state.get("check_id", "001")
    if plan.snapshot["method_profile"] in ("native_script/0.1.0", "native_script/0.2.0"):
        artifact = load_run_record(store, artifact_ref)
        code = load_run_record(store, artifact["code_ref"])
        source = read_public_bytes(store.path / code["representation_ref"]["relative_path"])
        data = read_public_bytes(store.path / code["data_json_ref"]["relative_path"])
        public = load_run_record(store, store.projections["public-problem.json"])
        script_executions = ScriptExecutions(store, public, settings, plan)
        execution = script_executions.reuse(code["execution_id"], ScriptCodeProposal(source.decode(),
            code["representation_ref"]["sha256"], code["data_bindings"], data))
        execution_ref = store.state["method_executions"][code["execution_id"]]["result_ref"]
        solve_ref = execution["solve_result_ref"]
        error = None
        if execution["source"]["status"] != "completed" or execution["source"]["exit_code"] != 0:
            error = RunError("source_execution_failed", "execution", "The selected last executed source script failed.")
        elif execution["collector_error"] is not None or solve_ref is None:
            error = RunError("collector_failed", "execution", "Source exited successfully but independent Solver evidence is unavailable.")
        record = load_run_record(store, store.projections[f"checks/{check_id}/record-snapshot.json"])
        record.update(status="selected" if error is None else "executed")
        store.json(f"checks/{check_id}/record.json", record, check_id)
        store.state.update(executed_artifact_ref=artifact_ref, solve_ref=solve_ref, execution_ref=execution_ref,
                           phase="execute_done" if error is None else "code_done")
        store.checkpoint()
        return solve_ref, execution_ref, error
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
    store.state.update(ledger=ledger, phase="execute_pending", execution_id=f"execution-{check_id}")
    store.checkpoint()
    store.emit("solver_started", solver_id=settings["solver"]["plugin_id"])
    out, err = StringIO(), StringIO()
    error = None
    solve_ref = None
    container = None
    resources = {"cpu_time_s": None, "peak_memory_bytes": None}
    executor_details: dict[str, Any] = {}
    try:
        if executor.mode == "container":
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
                    "output_limit_bytes": min(limits.get("output_limit_bytes", 1024 * 1024), 8 * 1024 * 1024),
                    "execution": {"model_backend": settings["model_backend"], "solver": settings["solver"], "allowed_problem_types": plan.snapshot["allowed_problem_types"]},
                    "execution_identity": plan.execution.identity() if plan.execution else None}
            else:
                ir = parse_json(read_public_bytes(store.path / formulation["structured_ir_ref"]["relative_path"]))
                source = compiled.source.encode()
                request = {"ir": ir, "source_sha256": hashlib.sha256(source).hexdigest(), "symbol_map": compiled.symbol_map, "solver_options": solver_options,
                    "compiler": settings["compiler"], "compiler_identity": compiler_identity(plan.snapshot["compiler"]), "target_backend": settings["model_backend"]["plugin_id"],
                    "execution": {"model_backend": settings["model_backend"], "solver": settings["solver"], "allowed_problem_types": plan.snapshot["allowed_problem_types"]},
                    "execution_identity": plan.execution.identity() if plan.execution else None}
            inputs = {"request.json": json.dumps(request, ensure_ascii=False, allow_nan=False).encode(), "model.py": source}
            for data in parse_json(read_public_bytes(store.path / "public-problem.json"))["data_refs"]:
                inputs[data["path"]] = read_public_bytes(store.path / data["path"])
            container = executor.run(["python", "-I", "-m", "llm4om.worker", "--solve", "/input/request.json", "--solver", settings["solver"]["plugin_id"]],
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
                solver_id=settings["solver"]["plugin_id"], model_backend=settings["model_backend"]["plugin_id"],
                result_profile=plan.execution.result_profile if plan.execution else None)
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
                view_ref = store.json(f"checks/{check_id}/factory-instance.json", instance, instance["model_id"])
                map_ref = store.json(f"checks/{check_id}/decision-map.json", {
                    "schema_version": "0.1.0", "decisions": exported["decision_map"],
                    "source_sha256": exported["source_sha256"], "data_bindings": artifact["data_bindings"],
                    "problem_revision": public["revision"], "origin": view_origin}, "decision-map")
                artifact["optional_views"].append({"origin": view_origin, "artifact_ref": view_ref,
                    "decision_map_ref": map_ref, "source_code_ref": artifact["code_ref"]})
                if view_origin == "native_exported_instance":
                    native_ref = store.write(f"checks/{check_id}/native-model.mps", base64.b64decode(exported["model_mps"], validate=True), "native-model")
                    artifact["optional_views"][-1]["native_model_ref"] = native_ref
                artifact_ref = store.json(f"checks/{check_id}/artifact.json", artifact, artifact["artifact_id"])
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
            stdout, stderr, exit_code = executor.run(
                [sys.executable, "-m", "llm4om.worker", "--solve-stdin", "--solver", settings["solver"]["plugin_id"]],
                json.dumps({"ir": ir, "source_sha256": hashlib.sha256(compiled.source.encode()).hexdigest(),
                            "symbol_map": compiled.symbol_map, "solver_options": solver_options, "compiler": settings["compiler"],
                            "compiler_identity": compiler_identity(plan.snapshot["compiler"]), "target_backend": settings["model_backend"]["plugin_id"],
                            "execution": {"model_backend": settings["model_backend"], "solver": settings["solver"], "allowed_problem_types": plan.snapshot["allowed_problem_types"]},
                            "execution_identity": plan.execution.identity() if plan.execution else None}, allow_nan=False).encode(),
                deadline=plan.deadline, cancellation=store.cancellation)
            out.write(stdout.decode(errors="replace"))
            err.write(stderr.decode(errors="replace"))
            payload = parse_json(stdout)
            if "error" in payload:
                raise RunError(payload["error"]["code"], payload["error"]["stage"], payload["error"]["message"])
            if exit_code != 0:
                raise RunError("solver_error", "solve", "The owned Solver child failed.")
            validate_worker_response(payload, payload["runtime"], solver_id=settings["solver"]["plugin_id"],
                                     model_backend=settings["model_backend"]["plugin_id"], result_profile=plan.execution.result_profile if plan.execution else None)
            solve = payload["result"]
            resources = payload["resources"]
            executor_details.update(exit_code=exit_code)
        variables = solve.pop("variables")
        solve["schema_version"] = "0.2.0"
        solve["solution_ref"] = store.json(f"checks/{check_id}/solution.json", {
            "schema_version": "0.2.0", "variables": variables, "evidence_origin": solve["evidence_origin"]}, "solution") if variables is not None else None
        solve_ref = store.json(f"checks/{check_id}/solve-result.json", solve, "solve-result")
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
    output_ref = store.write(f"checks/{check_id}/stdout.txt", out.getvalue().encode(), "stdout")
    stderr_ref = store.write(f"checks/{check_id}/stderr.txt", err.getvalue().encode(), "stderr")
    execution_ref = store.json(f"checks/{check_id}/execution.json", {"schema_version": "0.2.0",
        "run_id": store.run_id, "input_artifact_ref": input_artifact_ref, "artifact_ref": artifact_ref,
        "solver_call": ledger["solver_calls"],
        "execution_id": f"execution-{check_id}", "mode": executor.mode, "status": "cancelled" if error and error.code == "run_cancelled" else "failed" if error else "completed",
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
        "stderr_ref": stderr_ref, "diagnostics": [{"code": error.code, "stage": error.stage}] if error else []}, f"execution-{check_id}")
    record = parse_json(read_public_bytes(store.path / f"checks/{check_id}/record-snapshot.json"))
    record.update(artifact_ref=artifact_ref, status="executed" if error else "selected")
    store.json(f"checks/{check_id}/record.json", record, check_id)
    store.state.update(executed_artifact_ref=artifact_ref, artifact_ref=artifact_ref,
                       solve_ref=solve_ref, execution_ref=execution_ref,
                       phase="execute_done" if solve_ref is not None and error is None else "code_done")
    store.checkpoint()
    if solve_ref is not None:
        store.emit("solver_finished", solve_result_ref=solve_ref, termination=solve["termination"])
    return solve_ref, execution_ref, error


def restored_compilation(store: RunStore, artifact_ref: dict[str, Any]) -> CompiledCode | None:
    artifact = parse_json(read_public_bytes(store.path / artifact_ref["relative_path"]))
    code = parse_json(read_public_bytes(store.path / artifact["code_ref"]["relative_path"]))
    if code["provenance"]["origin"] != "deterministic_compilation":
        return None
    ir = parse_json(read_public_bytes(store.path / code["provenance"]["source_ir_ref"]["relative_path"]))
    binding = store.state["admission"]["compiler"]
    return resolve_compiler({"plugin_id": binding["manifest"]["plugin_id"], "config": binding["config"]},
        store.state["admission"]["model_backend_id"], expected=binding).compile(ir)


def reconcile_formulation(store: RunStore) -> None:
    check_id = store.state.get("check_id", "001")
    name = f"checks/{check_id}/artifact.json" if store.state["offline"] else f"checks/{check_id}/formulation-snapshot.json"
    records = store.interrupted_publications.get(name, [])
    if store.state.get("artifact_ref") is not None or not records:
        return
    try:
        artifact_ref = records[-1]
        artifact = load_run_record(store, artifact_ref)
        public_ref = store.projections["public-problem.json"]
        public = load_run_record(store, public_ref)
        formulation = load_run_record(store, artifact["formulation_ref"]) if artifact["formulation_ref"] is not None else None
        validate_bindings(artifact, public)
        if formulation is not None:
            validate_formulation(formulation, public)
        elif (store.state["admission"]["method_profile"] != "native_script/0.2.0"
                or artifact["stage_status"]["formulation"]["status"] != "not_available"
                or not isinstance(artifact["stage_status"]["formulation"]["reason"], str)
                or not artifact["stage_status"]["formulation"]["reason"]):
            raise ValueError("Missing Formulation is not admitted or explicitly explained.")
        if (artifact["problem_ref"] != public_ref
                or artifact["provenance"]["method"] != store.state["admission"]["method"]
                or formulation is not None and artifact["stage_status"]["formulation"] != {"status": "available", "reason": None}):
            raise ValueError("Completed Formulation differs from the admitted input or method.")
        if artifact["code_ref"] is None:
            if formulation is None:
                raise ValueError("A missing Formulation requires real Code output.")
            validate_model_artifact(artifact)
            ir = load_run_record(store, formulation["structured_ir_ref"])
            validate_bindings(ir, public)
            if (ir["problem_id"] != public["problem_id"] or ir["problem_revision"] != public["revision"]
                    or ir["problem_type"] not in store.state["admission"]["allowed_problem_types"]):
                raise ValueError("Completed Formulation IR belongs to another input or profile.")
        else:
            code = load_run_record(store, artifact["code_ref"])
            validate_bindings(code, public)
            if (code["source_formulation_ref"] != artifact["formulation_ref"]
                    or code["provenance"]["method"] != store.state["admission"]["method"]["manifest"]
                    or code["provenance"]["origin"] != "method_generated"
                    or code["model_backend"] != store.state["admission"]["model_backend_id"]):
                raise ValueError("Completed Code differs from the admitted Formulation or method.")
        store.accept_publications()
        save_formulation(store, artifact_ref, artifact)
    except (RunError, ValueError, KeyError, TypeError) as error:
        raise RunError("checkpoint_incompatible", "admission", "Cannot reconcile the completed Formulation.") from error


def reconcile_execution(store: RunStore, settings: dict[str, Any]) -> None:
    check_id = store.state.get("check_id", "001")
    records = store.interrupted_publications.get(f"checks/{check_id}/execution.json", [])
    if store.state["phase"] != "execute_pending" or not records:
        return
    try:
        def load(ref: dict[str, Any]) -> dict[str, Any]:
            return parse_json(read_public_bytes(public_path(store.path, ref["relative_path"])))
        execution_ref = records[-1]
        execution = load_run_record(store, execution_ref)
        if execution["status"] != "completed":
            return
        artifact_ref = execution["artifact_ref"]
        artifact = load(artifact_ref)
        original = load(store.state["artifact_ref"])
        mode = store.state["admission"]["executor"]["manifest"]["capabilities"]["execution_modes"][0]
        if (execution["run_id"] != store.run_id or execution["execution_id"] != store.state["execution_id"]
                or execution["solver_call"] != store.state["ledger"]["solver_calls"]
                or execution["input_artifact_ref"] != store.state["artifact_ref"]
                or {key: value for key, value in artifact.items() if key != "optional_views"}
                   != {key: value for key, value in original.items() if key != "optional_views"}
                or execution["mode"] != mode or execution["exit_code"] != 0
                or execution["diagnostics"]):
            raise ValueError("Completed execution identity differs from the admitted proposal.")
        solve_ref = execution["solve_result_ref"]
        solve = load(solve_ref)
        result_profile = store.state["admission"]["execution"]["solver"]["manifest"]["capabilities"]["result_profile"]
        sdk_origin = "trusted_" + result_profile.split("/", 1)[0]
        expected_origin = ("trusted_container_worker" if mode == "container" else
                           sdk_origin)
        if solve["termination"] == "error" or solve["evidence_origin"] != expected_origin:
            raise ValueError("Execution has no completed trusted Solver result.")
        runtime = {"packages": store.state["admission"]["packages"]}
        if mode == "container" and execution["image_id"] != store.state["admission"]["worker"]["image_id"]:
            raise ValueError("Completed execution used another Worker.")
        result = {key: value for key, value in solve.items() if key not in ("schema_version", "solution_ref")}
        result["variables"] = load(solve["solution_ref"])["variables"] if solve["solution_ref"] is not None else None
        result["evidence_origin"] = sdk_origin
        validate_worker_response({"schema_version": "0.2.0", "runtime": runtime, "result": result,
                                  "resources": execution["resources"]}, runtime,
                                 solver_id=settings["solver"]["plugin_id"], model_backend=settings["model_backend"]["plugin_id"], result_profile=result_profile)
        store.accept_publications()
        record = load(store.projections[f"checks/{check_id}/record-snapshot.json"])
        record.update(artifact_ref=artifact_ref, status="selected")
        store.json(f"checks/{check_id}/record.json", record, check_id)
        store.state.update(artifact_ref=artifact_ref, executed_artifact_ref=artifact_ref,
                           solve_ref=solve_ref, execution_ref=execution_ref, phase="execute_done")
        store.checkpoint()
    except (RunError, ValueError, KeyError, TypeError) as error:
        raise RunError("checkpoint_incompatible", "admission", "Cannot reconcile the completed proposal execution.") from error
