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
    RunError, parse_json, public_path, read_config, read_public_bytes, validate_config, validate_data, validate_problem,
    validate_model_artifact, validate_formulation, validate_bindings, reject_additional_refs,
    validate_worker_response,
)
from llm4om.control import CancellationToken
from llm4om.providers import Gateway
from llm4om.methods import FactoryCodeProposal, ScriptCodeProposal, MethodContext, ModelProposal
from llm4om.method_resources import RunMethodResources
from llm4om.preflight import AdmissionPlan, prepare_run
from llm4om.linear import CompiledCode, compile_ir
from llm4om.storage import RunStore
from llm4om.executors import run_container, run_owned_process
from llm4om.clarification import prepare_clarification, validate_clarification_response


@dataclass(frozen=True)
class RunResult:
    run_id: str
    bundle_path: Path
    status: str


def run_problem(problem: Path, config: Path, *, offline: bool = False,
                output_root: Path | None = None, cancellation: CancellationToken | None = None,
                interactive: bool = False) -> RunResult:
    if type(interactive) is not bool:
        raise RunError("invalid_config", "admission", "Interactive mode must be an explicit boolean.")
    cancellation = cancellation or CancellationToken()
    try:
        settings = read_config(config)
        root = output_root or config.parent / settings["store"]["config"]["root"]
    except (OSError, ValueError, KeyError, TypeError):
        root = output_root or Path.cwd() / "runs"
    store = RunStore(root, cancellation=cancellation)
    store.state["interactive"] = interactive
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
        if plan.snapshot["method_profile"] in ("factory_single_candidate/0.1.0", "factory_candidates/0.1.0", "native_single_candidate/0.1.0", "native_candidates/0.1.0", "native_script/0.1.0", "native_script/0.2.0"):
            code_level = "native_script_contract" if plan.snapshot["method_profile"] in ("native_script/0.1.0", "native_script/0.2.0") else "factory_contract"
        if plan.snapshot["method_profile"] in ("native_script/0.1.0", "native_script/0.2.0") and "admission" not in store.state:
            ledger["admission_solver_probe_calls"] = ledger.get("admission_solver_probe_calls", 0) + 2
        store.state["admission"] = plan.snapshot
        store.state["sdk"] = version("llm4om")
        store.state["host"] = {"python": platform.python_version(), "sdk_sha256": _sdk_sha256(),
                               "packages": {name: version(name) for name in ("PyYAML", "jsonschema")}}
        store.checkpoint()
        if artifact_ref is None or store.state.get("candidate_assessment_pending"):
            artifact_ref, stages = _prepare_candidate(store, problem, config, settings, ledger, offline, plan)
            solve_ref = store.state.get("solve_ref")
            execution_ref = store.state.get("execution_ref")
        status = "artifact_ready"
        if not offline:
            if store.state["phase"] == "method_done":
                artifact_ref, compiled = _compile_candidate(store, artifact_ref, settings)
                stages["code"] = {"status": "available", "reason": None}
                store.state.update(artifact_ref=artifact_ref, phase="code_done")
                store.emit("code_saved", artifact_ref=artifact_ref,
                           **({"evidence_origin": "method_generated"} if compiled is None else {}))
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
        if isinstance(error, RunError) and error.code == "clarification_required":
            status = "needs_input" if store.state.get("interactive", False) else "unresolved"
            error_record = None
    if stages["formulation"]["status"] == "available" or stages["code"]["status"] == "available":
        store.json("evaluation.json", {"schema_version": "0.2.0", "protocol_id": "llm4om.eval.public-v0.1",
                   "formulation_validation": {"status": "pass", "level": "structural"}
                        if stages["formulation"]["status"] == "available" else dict(stages["formulation"]),
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
               "clarification_request_ref": store.state.get("clarification_request_ref"),
               "clarification_response_refs": store.state.get("clarification_response_refs", []),
               "public_projections": {name: ref for name, ref in store.projections.items() if name != "bundle.json"},
               "final_candidate_id": store.state.get("candidate_id", "001") if status == "completed" else None,
               "execution_plan": {name: {"requested_plugin_id": settings.get(name, {}).get("plugin_id"),
                    "resolved_plugin_id": settings[name]["plugin_id"] if resource_status[name] != "not_available" else None,
                    "status": resource_status[name],
                    "reason": None if resource_status[name] == "available" else "Method supplied Code; compiler is not used."
                    if name == "compiler" and code_level in ("factory_contract", "native_script_contract") else "Resource did not complete successfully."}
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
        validate_data(raw, data)
        ref = store.write(f"data/{index}.{data['format']}", raw, data["data_id"])
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
                                    settings["budget"], config.parent, deadline=plan.deadline, role_providers=plan.role_providers)
    def save_method_checkpoint(value: dict[str, Any]) -> None:
        if not method.manifest["capabilities"].get("supports_checkpoint"):
            raise RunError("checkpoint_unsupported", "formulation", "Method has no internal checkpoint contract.")
        value = parse_json(json.dumps(value, allow_nan=False).encode())
        if not isinstance(value.get("schema_version"), str):
            raise RunError("checkpoint_incompatible", "formulation", "Method checkpoint must be versioned JSON.")
        store.state["method_checkpoint"] = value
        store.checkpoint()
    context = MethodContext(gateway, MappingProxyType(data_content), MappingProxyType(deepcopy(settings["budget"])),
                            hashlib.sha256(source_problem).hexdigest(), store.cancellation, save_method_checkpoint,
                            RunMethodResources(store, public, settings, plan, responses=gateway.calls), plan.deadline,
                            tuple(deepcopy(store.state.get("clarification_responses", []))))
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
    if outcome.status == "needs_input":
        if (not method.manifest["capabilities"].get("supports_clarification") or outcome.proposal is not None
                or outcome.final_candidate_id is not None or outcome.clarification is None
                or store.state.get("method_checkpoint") is None):
            raise RunError("invalid_method_outcome", "formulation", "Clarification requires a declared capability, request and versioned method checkpoint.")
        request = prepare_clarification(outcome.clarification, public, store.run_id, context.problem_sha256,
                                        sequence_no=len(store.state.get("clarification_responses", [])) + 1)
        ref = store.json("clarifications/" + request["request_id"] + "/request.json", request, request["request_id"])
        store.state.update(clarification_request_ref=ref, clarification_answered=False, phase="needs_input")
        store.emit("clarification_requested", request_ref=ref)
        raise RunError("clarification_required", "formulation", "Public clarification is required.")
    if outcome.status in ("failed", "exhausted") and outcome.final_candidate_id is None and outcome.proposal is None:
        store.json("method/outcome.json", {"schema_version": "0.1.0", "status": outcome.status,
            "final_candidate_id": None}, "method-outcome")
        raise RunError("method_" + outcome.status, "formulation", "The method ended without a selectable candidate; existing attempts are retained.")
    if outcome.status == "candidate_selected" and outcome.proposal is None:
        return RunMethodResources(store, public, settings, plan).selected(outcome.final_candidate_id)
    if plan.snapshot["method_profile"] in ("grounded_candidates/0.1.0", "factory_candidates/0.1.0", "native_candidates/0.1.0"):
        raise RunError("invalid_method_outcome", "formulation", "The candidate profile requires a saved assessment and selection.")
    if outcome.status != "candidate_selected" or outcome.final_candidate_id != "001" or not isinstance(outcome.proposal, ModelProposal):
        raise RunError("invalid_method_outcome", "formulation", "This profile requires one selected candidate with ID 001.")
    store.state["candidate_id"] = "001"
    replay = {"mode": gateway.calls[-1].evidence_origin if gateway.calls else "no_calls",
              "call_ids": [call.call_id for call in gateway.calls],
              "response_sha256": gateway.calls[-1].source_sha256 if gateway.calls else None}
    return _persist_proposal(store, outcome.proposal, public, problem_ref, context.problem_sha256,
                             settings, offline, plan, replay)


def _persist_proposal(store: RunStore, output: ModelProposal, public: dict[str, Any],
                      problem_ref: dict[str, Any], problem_sha256: str, settings: dict[str, Any],
                      offline: bool, plan: AdmissionPlan, replay: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_id = store.state.get("candidate_id", "001")
    method = plan.method
    artifact = parse_json(json.dumps(output.artifact, allow_nan=False).encode())
    formulation = parse_json(json.dumps(output.formulation, allow_nan=False).encode()) if output.formulation is not None else None
    factory_profile = plan.snapshot["method_profile"] in ("factory_single_candidate/0.1.0", "factory_candidates/0.1.0", "native_single_candidate/0.1.0", "native_candidates/0.1.0", "native_script/0.1.0", "native_script/0.2.0")
    source_ref = None
    if factory_profile and isinstance(output.code, (FactoryCodeProposal, ScriptCodeProposal)) and isinstance(output.code.source, str):
        source_ref = store.write(f"candidates/{candidate_id}/model.py", output.code.source.encode(), "method-source")
        if formulation is not None:
            store.json(f"candidates/{candidate_id}/supplied-formulation.json", formulation, "supplied-formulation")
        store.json(f"candidates/{candidate_id}/supplied-code.json", {
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
        formulation["structured_ir_ref"] = store.json(f"candidates/{candidate_id}/structured-ir.json", ir, ir["model_id"])
    formulation_ref = None
    if (plan.snapshot["method_profile"] in ("factory_candidates/0.1.0", "native_candidates/0.1.0")
            and artifact["provenance"].get("repair", {}).get("stage") == "code"):
        parents = store.state.get("candidate_parent_ids", [])
        if len(parents) != 1:
            raise RunError("invalid_code_repair", "formulation", "Code-only repair requires exactly one source candidate.")
        parent = store.state["candidate_assessments"][parents[0]]
        assessment = _load_verified_record(store, parent["result_ref"])
        parent_artifact = _load_verified_record(store, assessment["artifact_ref"]) if assessment["artifact_ref"] else None
        if parent_artifact is None or parent_artifact["formulation_ref"] is None:
            raise RunError("invalid_code_repair", "formulation", "Code-only repair requires an available source Formulation.")
        original = _load_verified_record(store, parent_artifact["formulation_ref"])
        if formulation is None or any(formulation[key] != original[key] for key in (
                "representation", "representation_kind", "problem_id", "problem_revision", "data_bindings")):
            raise RunError("invalid_code_repair", "formulation", "Code-only repair changed the source Formulation or data identity.")
        formulation_ref = parent_artifact["formulation_ref"]
    elif formulation is not None:
        formulation_ref = store.json(f"candidates/{candidate_id}/formulation.json", formulation, formulation["formulation_id"])
    artifact["problem_ref"] = problem_ref
    artifact["formulation_ref"] = formulation_ref
    if factory_profile:
        assert isinstance(output.code, (FactoryCodeProposal, ScriptCodeProposal))
        code_ref = store.json(f"candidates/{candidate_id}/code-artifact.json", {
            "schema_version": "0.2.0", "code_id": "method-code-001", "representation_kind": output.code.representation_kind,
            "factory_contract": "native_script/0.1.0" if isinstance(output.code, ScriptCodeProposal) else "native_gurobipy/0.1.0" if output.code.representation_kind == "native_code" else "python_factory/0.1.0",
            "entry_point": "code.py" if isinstance(output.code, ScriptCodeProposal) else "build_model",
            **({"data_json_ref": store.write(f"candidates/{candidate_id}/data.json", output.code.data_json, "script-data"),
                "execution_id": output.execution_id} if isinstance(output.code, ScriptCodeProposal) else {}),
            "representation_ref": source_ref, "model_backend": settings["model_backend"]["plugin_id"],
            "source_formulation_ref": formulation_ref, "data_bindings": output.code.data_bindings,
            "provenance": {"origin": "method_generated", "method": method.manifest,
                           "generation": artifact["provenance"]}}, "method-code-001")
        artifact["code_ref"] = code_ref
        artifact["stage_status"]["code"] = {"status": "available", "reason": None}
    artifact["provenance"]["replay"] = replay
    artifact["provenance"]["method"] = {"manifest": method.manifest, "origin": method.origin}
    artifact_ref = store.json(f"candidates/{candidate_id}/artifact.json" if offline else f"candidates/{candidate_id}/formulation-snapshot.json", artifact, artifact["artifact_id"])
    return artifact_ref, _save_formulation(store, artifact_ref, artifact)


def _save_formulation(store: RunStore, artifact_ref: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    candidate_id = store.state.get("candidate_id", "001")
    method = artifact["provenance"]["method"]["manifest"]
    call_ids = artifact["provenance"]["replay"]["call_ids"]
    store.json(f"candidates/{candidate_id}/candidate.json" if store.state["offline"] else f"candidates/{candidate_id}/candidate-snapshot.json", {
        "schema_version": "0.2.0", "candidate_id": candidate_id, "run_id": store.run_id, "parent_ids": store.state.get("candidate_parent_ids", []),
        "change_reason": store.state.get("candidate_change_reason"),
        "sequence_no": max(1, store.state["ledger"]["candidates"]), "artifact_ref": artifact_ref,
        "created_by": {"method_id": method["plugin_id"], "method_version": method["plugin_version"],
                       "variant_id": (method["source"] or {}).get("variant_id", "grounded_single_candidate"),
                       "call_ids": call_ids, "prompt_hash": None,
                       "role": artifact["provenance"].get("repair", {}).get("stage", "formulation" if artifact["formulation_ref"] is not None else "code")}, "status": "proposed"}, candidate_id)
    if not store.state.get("candidate_assessment_pending"):
        store.state["ledger"]["candidates"] = max(1, store.state["ledger"]["candidates"])
    stages = {**artifact["stage_status"], "solve": {"status": "not_available", "reason": "Solve has not run."}}
    store.state.update(artifact_ref=artifact_ref, stages=stages, phase="method_done")
    store.emit("formulation_saved" if artifact["formulation_ref"] is not None else "code_output_saved",
               artifact_ref=artifact_ref, call_ids=call_ids, evidence_origin="method_output")
    return stages


def _compile_candidate(store: RunStore, artifact_ref: dict[str, Any], settings: dict[str, Any]) -> tuple[dict[str, Any], CompiledCode | None]:
    candidate_id = store.state.get("candidate_id", "001")
    artifact = parse_json(read_public_bytes(store.path / artifact_ref["relative_path"]))
    if artifact["code_ref"] is not None:
        return artifact_ref, None
    formulation = parse_json(read_public_bytes(store.path / artifact["formulation_ref"]["relative_path"]))
    ir_ref = formulation["structured_ir_ref"]
    ir = parse_json(read_public_bytes(store.path / ir_ref["relative_path"]))
    compiled = compile_ir(ir)
    source_ref = store.write(f"candidates/{candidate_id}/model.py", compiled.source.encode(), "compiled-source")
    symbols_ref = store.json(f"candidates/{candidate_id}/symbol-map.json", compiled.symbol_map, "symbol-map")
    code_ref = store.json(f"candidates/{candidate_id}/code-artifact.json", {
        "schema_version": "0.2.0", "code_id": "compiled-code", "representation_kind": "python_factory",
        "representation_ref": source_ref, "model_backend": settings["model_backend"]["plugin_id"],
        "source_formulation_ref": artifact["formulation_ref"], "data_bindings": artifact["data_bindings"],
        "provenance": {"origin": "deterministic_compilation", "compiler_id": settings["compiler"]["plugin_id"],
                       "compiler_version": "0.1.0", "source_ir_ref": ir_ref, "symbol_map_ref": symbols_ref}}, "compiled-code")
    artifact["artifact_id"] += "-compiled"
    artifact["code_ref"] = code_ref
    artifact["stage_status"]["code"] = {"status": "available", "reason": None}
    artifact_ref = store.json(f"candidates/{candidate_id}/artifact.json", artifact, artifact["artifact_id"])
    store.json(f"candidates/{candidate_id}/build.json", {"schema_version": "0.2.0", "code_artifact_ref": code_ref,
        "compiler_id": settings["compiler"]["plugin_id"], "compiler_version": "0.1.0",
        "source_ir_ref": ir_ref, "target_backend": settings["model_backend"]["plugin_id"],
        "symbol_map_ref": symbols_ref, "data_bindings": artifact["data_bindings"],
        "diagnostics": [], "compiler_config_sha256": hashlib.sha256(b"{}").hexdigest()}, "build")
    return artifact_ref, compiled


def _execute_candidate(store: RunStore, compiled: CompiledCode | None, artifact_ref: dict[str, Any],
                       settings: dict[str, Any], ledger: dict[str, Any], plan: AdmissionPlan) -> tuple[dict[str, Any] | None, dict[str, Any], RunError | None]:
    candidate_id = store.state.get("candidate_id", "001")
    if plan.snapshot["method_profile"] in ("native_script/0.1.0", "native_script/0.2.0"):
        artifact = _load_verified_record(store, artifact_ref)
        code = _load_verified_record(store, artifact["code_ref"])
        source = read_public_bytes(store.path / code["representation_ref"]["relative_path"])
        data = read_public_bytes(store.path / code["data_json_ref"]["relative_path"])
        public = _load_verified_record(store, store.projections["public-problem.json"])
        method_resources = RunMethodResources(store, public, settings, plan)
        execution = method_resources.reuse(code["execution_id"], ScriptCodeProposal(source.decode(),
            code["representation_ref"]["sha256"], code["data_bindings"], data))
        execution_ref = store.state["method_executions"][code["execution_id"]]["result_ref"]
        solve_ref = execution["solve_result_ref"]
        error = None
        if execution["source"]["status"] != "completed" or execution["source"]["exit_code"] != 0:
            error = RunError("source_execution_failed", "execution", "The selected last executed source script failed.")
        elif execution["collector_error"] is not None or solve_ref is None:
            error = RunError("collector_failed", "execution", "Source exited successfully but independent Solver evidence is unavailable.")
        candidate = _load_verified_record(store, store.projections[f"candidates/{candidate_id}/candidate-snapshot.json"])
        candidate.update(status="selected" if error is None else "executed")
        store.json(f"candidates/{candidate_id}/candidate.json", candidate, candidate_id)
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
    store.state.update(ledger=ledger, phase="execute_pending", execution_id=f"execution-{candidate_id}")
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
                view_ref = store.json(f"candidates/{candidate_id}/factory-instance.json", instance, instance["model_id"])
                map_ref = store.json(f"candidates/{candidate_id}/decision-map.json", {
                    "schema_version": "0.1.0", "decisions": exported["decision_map"],
                    "source_sha256": exported["source_sha256"], "data_bindings": artifact["data_bindings"],
                    "problem_revision": public["revision"], "origin": view_origin}, "decision-map")
                artifact["optional_views"].append({"origin": view_origin, "artifact_ref": view_ref,
                    "decision_map_ref": map_ref, "source_code_ref": artifact["code_ref"]})
                if view_origin == "native_exported_instance":
                    native_ref = store.write(f"candidates/{candidate_id}/native-model.mps", base64.b64decode(exported["model_mps"], validate=True), "native-model")
                    artifact["optional_views"][-1]["native_model_ref"] = native_ref
                artifact_ref = store.json(f"candidates/{candidate_id}/artifact.json", artifact, artifact["artifact_id"])
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
        solve["solution_ref"] = store.json(f"candidates/{candidate_id}/solution.json", {
            "schema_version": "0.2.0", "variables": variables, "evidence_origin": solve["evidence_origin"]}, "solution") if variables is not None else None
        solve_ref = store.json(f"candidates/{candidate_id}/solve-result.json", solve, "solve-result")
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
    output_ref = store.write(f"candidates/{candidate_id}/stdout.txt", out.getvalue().encode(), "stdout")
    stderr_ref = store.write(f"candidates/{candidate_id}/stderr.txt", err.getvalue().encode(), "stderr")
    execution_ref = store.json(f"candidates/{candidate_id}/execution.json", {"schema_version": "0.2.0",
        "run_id": store.run_id, "input_artifact_ref": input_artifact_ref, "artifact_ref": artifact_ref,
        "solver_call": ledger["solver_calls"],
        "execution_id": f"execution-{candidate_id}", "mode": settings["executor"]["plugin_id"].removeprefix("llm4om.executors."), "status": "cancelled" if error and error.code == "run_cancelled" else "failed" if error else "completed",
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
        "stderr_ref": stderr_ref, "diagnostics": [{"code": error.code, "stage": error.stage}] if error else []}, f"execution-{candidate_id}")
    candidate = parse_json(read_public_bytes(store.path / f"candidates/{candidate_id}/candidate-snapshot.json"))
    candidate.update(artifact_ref=artifact_ref, status="executed" if error else "selected")
    store.json(f"candidates/{candidate_id}/candidate.json", candidate, candidate_id)
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


def _load_verified_record(store: RunStore, ref: dict[str, Any]) -> dict[str, Any]:
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
    verify(ref)
    return load(ref)


def _reconcile_formulation(store: RunStore) -> None:
    candidate_id = store.state.get("candidate_id", "001")
    name = f"candidates/{candidate_id}/artifact.json" if store.state["offline"] else f"candidates/{candidate_id}/formulation-snapshot.json"
    records = store.interrupted_publications.get(name, [])
    if store.state.get("artifact_ref") is not None or not records:
        return
    try:
        artifact_ref = records[-1]
        artifact = _load_verified_record(store, artifact_ref)
        public_ref = store.projections["public-problem.json"]
        public = _load_verified_record(store, public_ref)
        formulation = _load_verified_record(store, artifact["formulation_ref"]) if artifact["formulation_ref"] is not None else None
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
            ir = _load_verified_record(store, formulation["structured_ir_ref"])
            validate_bindings(ir, public)
            if (ir["problem_id"] != public["problem_id"] or ir["problem_revision"] != public["revision"]
                    or ir["problem_type"] not in store.state["admission"]["allowed_problem_types"]):
                raise ValueError("Completed Formulation IR belongs to another input or profile.")
        else:
            code = _load_verified_record(store, artifact["code_ref"])
            validate_bindings(code, public)
            if (code["source_formulation_ref"] != artifact["formulation_ref"]
                    or code["provenance"]["method"] != store.state["admission"]["method"]["manifest"]
                    or code["provenance"]["origin"] != "method_generated"
                    or code["model_backend"] != store.state["admission"]["model_backend_id"]):
                raise ValueError("Completed Code differs from the admitted Formulation or method.")
        store.accept_publications()
        _save_formulation(store, artifact_ref, artifact)
    except (RunError, ValueError, KeyError, TypeError) as error:
        raise RunError("checkpoint_incompatible", "admission", "Cannot reconcile the completed Formulation.") from error


def _reconcile_execution(store: RunStore, settings: dict[str, Any]) -> None:
    candidate_id = store.state.get("candidate_id", "001")
    records = store.interrupted_publications.get(f"candidates/{candidate_id}/execution.json", [])
    if store.state["phase"] != "execute_pending" or not records:
        return
    try:
        def load(ref: dict[str, Any]) -> dict[str, Any]:
            return parse_json(read_public_bytes(public_path(store.path, ref["relative_path"])))
        execution_ref = records[-1]
        execution = _load_verified_record(store, execution_ref)
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
        candidate = load(store.projections[f"candidates/{candidate_id}/candidate-snapshot.json"])
        candidate.update(artifact_ref=artifact_ref, status="selected")
        store.json(f"candidates/{candidate_id}/candidate.json", candidate, candidate_id)
        store.state.update(artifact_ref=artifact_ref, executed_artifact_ref=artifact_ref,
                           solve_ref=solve_ref, execution_ref=execution_ref, phase="execute_done")
        store.checkpoint()
    except (RunError, ValueError, KeyError, TypeError) as error:
        raise RunError("checkpoint_incompatible", "admission", "Cannot reconcile the completed candidate execution.") from error


def _sdk_sha256() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(path for path in root.rglob("*") if path.suffix in (".py", ".txt", ".json")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def resume_run(run: Path, *, cancellation: CancellationToken | None = None,
               strategy: str = "continue", answers: Path | None = None,
               revised_problem: Path | None = None) -> RunResult:
    """Continue fixed work, or explicitly start a derived semantic rerun with carried usage."""
    if strategy not in {"continue", "rerun"}:
        raise RunError("invalid_resume_strategy", "admission", "Resume strategy must be continue or rerun.")
    if revised_problem is not None and answers is None:
        raise RunError("invalid_clarification_response", "admission", "A problem revision needs a bound clarification response.")
    store = RunStore(run.parent, resume=run,
                     cancellation=cancellation if strategy == "continue" and revised_problem is None else None)
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
                           deadline=max(saved_deadline, time.time() + 5) if strategy == "rerun" or revised_problem is not None or store.state.get("status") in ("completed", "artifact_ready") else saved_deadline,
                           cancellation=store.cancellation, expected=store.state["admission"],
                           identity_only=strategy == "rerun" or revised_problem is not None or store.state.get("status") in ("completed", "artifact_ready"))
        if plan.snapshot != store.state["admission"]:
            raise RunError("checkpoint_incompatible", "admission", "Saved resource identity differs from admission.")
        if store.state.get("clarification_request_ref") is not None:
            request = _load_verified_record(store, store.state["clarification_request_ref"])
            receipts = store.interrupted_publications.get("clarifications/" + request["request_id"] + "/response.json", [])
            if receipts:
                response = validate_clarification_response(_load_verified_record(store, receipts[-1]), request)
                if response["action"] != "confirm":
                    raise RunError("checkpoint_incompatible", "admission", "A same-run response receipt must confirm existing declarations.")
                store.accept_publications()
                _accept_clarification_response(store, request, response, receipts[-1])
        if answers is not None:
            if strategy != "continue" or store.state.get("clarification_request_ref") is None:
                raise RunError("invalid_clarification_response", "admission", "Answers need an existing clarification and the continue strategy.")
            request = _load_verified_record(store, store.state["clarification_request_ref"])
            response = validate_clarification_response(parse_json(read_public_bytes(answers)), request)
            if response["action"] == "revise":
                if revised_problem is None:
                    raise RunError("problem_revision_required", "admission", "Revised information requires a new public problem revision.")
                revised = parse_json(read_public_bytes(revised_problem))
                validate_problem(revised)
                if revised["problem_id"] != request["problem_id"] or revised["revision"] == request["problem_revision"]:
                    raise RunError("invalid_problem_revision", "admission", "Revision must retain problem identity and change revision explicitly.")
                return _derive_run(store, resource_records, cancellation=cancellation, problem=revised_problem, response=response)
            if revised_problem is not None:
                raise RunError("invalid_problem_revision", "admission", "Confirmation cannot carry a changed problem.")
            _accept_clarification_response(store, request, response)
        if strategy == "continue" and store.state.get("status") in ("needs_input", "unresolved") and not store.state.get("clarification_answered"):
            return RunResult(store.run_id, store.path, store.state["status"])
        if strategy == "rerun":
            return _derive_run(store, resource_records, cancellation=cancellation)
        if store.state.get("status") in ("completed", "artifact_ready"):
            return RunResult(store.run_id, store.path, store.state["status"])
        if time.time() >= store.state["deadline"]:
            raise RunError("deadline_exhausted", "admission", "The original absolute run deadline expired.")
        if "public-problem.json" in store.projections:
            public = _load_verified_record(store, store.projections["public-problem.json"])
            RunMethodResources(store, public, settings, plan).reconcile()
        _reconcile_formulation(store)
        if (store.state.get("artifact_ref") is None and store.state.get("method_checkpoint") is None
                and store.state.get("method_started")):
            raise RunError("checkpoint_unsupported", "admission", "No completed stage or supported internal method checkpoint exists.")
        _reconcile_execution(store, settings)
        store.interrupted_publications = {}
        return _run_problem(Path(store.state["problem"]), Path(store.state["config"]), store,
                            offline=store.state["offline"], restored_plan=plan)
    finally:
        store.close()


def _accept_clarification_response(store: RunStore, request: dict[str, Any], response: dict[str, Any],
                                   receipt: dict[str, Any] | None = None) -> None:
    records = store.state.setdefault("clarification_responses", [])
    prior = next((r for r in records if r["request_id"] == response["request_id"]), None)
    if prior is not None and prior != response:
        raise RunError("clarification_response_conflict", "admission", "An accepted answer is immutable.")
    if prior is None:
        ref = receipt or store.json("clarifications/" + request["request_id"] + "/response.json", response, request["request_id"] + "-response")
        records.append(response)
        store.state.setdefault("clarification_response_refs", []).append(ref)
        store.state.update(clarification_answered=True, phase="method_pending")
        store.checkpoint()


def _derive_run(store: RunStore, resource_records: list[dict[str, Any]], *,
                cancellation: CancellationToken | None = None, problem: Path | None = None,
                response: dict[str, Any] | None = None) -> RunResult:
    operation_key = identity = None
    if problem is not None and response is not None:
        raw = read_public_bytes(problem)
        revised = parse_json(raw)
        sources = {}
        for ref in revised["data_refs"]:
            data = read_public_bytes(public_path(problem.parent, ref["path"]))
            validate_data(data, ref)
            digest = hashlib.sha256(data).hexdigest()
            if ref["sha256"] and ref["sha256"] != digest:
                raise RunError("data_hash_mismatch", "admission", "Revised data differs from its declared identity.")
            sources[ref["data_id"]] = digest
        operation_key = hashlib.sha256(json.dumps({"request_id": response["request_id"],
            "problem_id": revised["problem_id"], "revision": revised["revision"]}, sort_keys=True).encode()).hexdigest()
        identity = hashlib.sha256(json.dumps({"problem_sha256": hashlib.sha256(raw).hexdigest(),
            "response": response, "data_sha256": sources}, sort_keys=True).encode()).hexdigest()
        existing = store.state.get("clarification_derivations", {}).get(operation_key)
        if existing is not None:
            if existing["identity"] != identity:
                raise RunError("problem_revision_conflict", "admission", "A recorded problem revision cannot be rebound to different input or answers.")
            child_path = store.path.parent / existing["run_id"]
            with_state = parse_json(read_public_bytes(child_path / "checkpoint.json"))["payload"]["state"]
            if "sources" not in with_state:
                child = RunStore(store.path.parent, resume=child_path, cancellation=cancellation)
                try:
                    if child.state.get("derivation_identity") != identity:
                        raise RunError("checkpoint_incompatible", "admission", "Derived initialization identity changed.")
                    child.accept_publications()
                    return _initialize_derived_run(child, store, resource_records, problem=problem, response=response)
                finally:
                    child.close()
            return resume_run(child_path, cancellation=cancellation)
    child = RunStore(store.path.parent, cancellation=cancellation)
    try:
        if operation_key is not None:
            child.state["derivation_identity"] = identity
            child.checkpoint()
            store.state.setdefault("clarification_derivations", {})[operation_key] = {"identity": identity, "run_id": child.run_id}
            store.checkpoint()
        return _initialize_derived_run(child, store, resource_records, problem=problem, response=response)
    finally:
        child.close()


def _initialize_derived_run(child: RunStore, store: RunStore, resource_records: list[dict[str, Any]], *,
                            problem: Path | None = None, response: dict[str, Any] | None = None) -> RunResult:
    parent_refs = [child.write("parent/" + store.run_id + "/" + ref["relative_path"],
        read_public_bytes(public_path(store.path, ref["relative_path"])), ref["artifact_id"],
        ref.get("schema_version")) for ref in store.refs]
    parent_checkpoint_ref = child.write("parent/" + store.run_id + "/checkpoint.json",
        read_public_bytes(store.path / "checkpoint.json"), "parent-checkpoint", "0.1.0")
    ledger = deepcopy(store.state["ledger"])
    response_ref = child.json("clarification-response.json", response, "revision-response") if response is not None else None
    lineage_ref = child.json("lineage.json", {"schema_version": "0.1.0",
        "operation": "clarification_revision" if problem is not None else "derived_rerun", "parent_run_id": store.run_id,
        "clarification_response_ref": response_ref,
        "parent_budget_ledger": ledger, "input_hashes": store.state["sources"],
        "parent_checkpoint_ref": parent_checkpoint_ref,
        "parent_artifacts": parent_refs, "parent_resource_records": resource_records, "reused_records": [],
        "policy": "Fresh method execution; previous paid/unknown usage and reservations count against the configured caps."}, "lineage")
    child.state.update(lineage_ref=lineage_ref, inherited_ledger=ledger, ledger=deepcopy(ledger), interactive=store.state.get("interactive", False))
    return _run_problem(problem or Path(store.state["problem"]), Path(store.state["config"]), child,
                        offline=store.state["offline"])
