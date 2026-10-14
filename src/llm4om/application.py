"""Single-problem run, report, resume and derived-run application use cases."""

import hashlib
import json
import platform
import time
from copy import deepcopy
from importlib.metadata import version
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from llm4om.contracts import RunError, parse_json, public_path, read_config, read_public_bytes, validate_config, validate_data, validate_problem
from llm4om.control import CancellationToken
from llm4om.gateway import Gateway
from llm4om.runtime_identity import sdk_sha256
from llm4om.run_records import load_run_record
from llm4om.candidates import (persist_proposal, compile_candidate, execute_candidate,
    restored_compilation, reconcile_formulation, reconcile_execution)
from llm4om.methods import MethodContext, ModelProposal
from llm4om.method_resources import RunMethodResources
from llm4om.preflight import AdmissionPlan, prepare_run
from llm4om.storage import RunStore
from llm4om.store_registry import DEFAULT_SELECTION, open_run_store, resolve_store, saved_store_selection
from llm4om.clarification import prepare_clarification, validate_clarification_response
from llm4om.reporters import render_reports, resolve_reporters


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
    selection = dict(DEFAULT_SELECTION)
    try:
        settings = read_config(config)
        selection = settings["store"]
        root = output_root or config.parent / settings["store"]["config"].get("root", "runs")
    except (OSError, ValueError, KeyError, TypeError):
        root = output_root or Path.cwd() / "runs"
    try:
        resolved = resolve_store(selection)
    except RunError:
        # A store selection that cannot be resolved (including a broken installed plugin) still
        # gets a filesystem run directory so admission can save its failure bundle.
        store = RunStore(root, cancellation=cancellation)
    else:
        store = resolved.open(root, cancellation=cancellation)
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
    plan = restored_plan
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
                sources[str(path)] = hashlib.sha256(read_public_bytes(path, max_bytes=8 * 1024 * 1024)).hexdigest()
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
        if plan.method.manifest["capabilities"].get("human_assisted"):
            store.state["assisted"] = True
        if plan.snapshot["method_profile"] in ("factory_single_candidate/0.1.0", "factory_candidates/0.1.0", "native_single_candidate/0.1.0", "native_candidates/0.1.0", "native_script/0.1.0", "native_script/0.2.0"):
            code_level = "native_script_contract" if plan.snapshot["method_profile"] in ("native_script/0.1.0", "native_script/0.2.0") else "factory_contract"
        if plan.snapshot["method_profile"] in ("native_script/0.1.0", "native_script/0.2.0") and "admission" not in store.state:
            ledger["admission_solver_probe_calls"] = ledger.get("admission_solver_probe_calls", 0) + 2
        store.state["admission"] = plan.snapshot
        store.state["sdk"] = version("llm4om")
        store.state["host"] = {"python": platform.python_version(), "sdk_sha256": sdk_sha256(),
                               "packages": {name: version(name) for name in ("PyYAML", "jsonschema")}}
        store.checkpoint()
        if artifact_ref is None or store.state.get("candidate_assessment_pending"):
            artifact_ref, stages = _prepare_candidate(store, problem, config, settings, ledger, offline, plan)
            solve_ref = store.state.get("solve_ref")
            execution_ref = store.state.get("execution_ref")
        status = "artifact_ready"
        if not offline:
            if store.state["phase"] == "method_done":
                artifact_ref, compiled = compile_candidate(store, artifact_ref, settings)
                stages["code"] = {"status": "available", "reason": None}
                store.state.update(artifact_ref=artifact_ref, phase="code_done")
                store.emit("code_saved", artifact_ref=artifact_ref,
                           **({"evidence_origin": "method_generated"} if compiled is None else {}))
            else:
                compiled = restored_compilation(store, artifact_ref)
            cancellation.check()
            stages["code"] = {"status": "available", "reason": None}
            if store.state["phase"] != "execute_done":
                solve_ref, execution_ref, execution_error = execute_candidate(store, compiled, artifact_ref, settings, ledger, plan)
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
    if store.state.get("assisted"):
        ledger["evidence_origin"] = "assisted"
    store.json("budget-ledger.json", ledger, "budget")
    store.emit("run_finished", status=status, error=error_record)
    report_refs: list[dict[str, Any]] = []
    report_errors: list[dict[str, Any]] = []
    if plan is not None:
        row = {"run_id": store.run_id, "status": status, "mode": mode, "stages": stages, "error": error_record,
            "method_id": settings["method"]["plugin_id"], "provider_id": settings["llm"]["provider_plugin_id"],
            "model": settings["llm"]["model"], **ledger,
            "solve": load_run_record(store, solve_ref) if solve_ref else None}
        view = {"id": store.run_id, "rows": [row],
                "summary": {"policy": "Structural checks do not establish semantic correctness. Unknown resources stay null."}}
        report_refs, report_errors = render_reports(list(plan.reporters), view, 'run',
            lambda name, raw, ref: store.write(name, raw, ref["artifact_id"]))
        if report_errors:
            store.json("diagnostics/report-errors.json", {"schema_version": "0.1.0", "errors": report_errors}, "report-errors")
    resource_status = {"compiler": "available" if code_level == "deterministic_compilation" and stages["code"]["status"] == "available" else "not_available",
                       **{name: "available" if solve_ref is not None else "failed" if execution_ref is not None else "not_available"
                          for name in ("model_backend", "solver", "executor")}}
    store.json("bundle.json", {"schema_version": "0.2.0", "run_id": store.run_id,
               "assisted": store.state.get("assisted", False), "report_refs": report_refs, "report_errors": report_errors,
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


def report_run(run: Path) -> dict[str, Any]:
    """Render saved public results without a Provider, Solver or source replay."""
    store = open_run_store(saved_store_selection(run), run.parent, resume=run)
    try:
        if store.state.get("status") not in {"completed", "artifact_ready", "failed", "cancelled", "unresolved", "needs_input"}:
            raise RunError("run_active", "reporting", "Report a saved inactive run.")
        if store.state.get("sdk") != version("llm4om") or store.state.get("host", {}).get("sdk_sha256") != sdk_sha256():
            raise RunError("checkpoint_incompatible", "reporting", "Saved SDK identity differs from this renderer.")
        bundle = load_run_record(store, store.projections["bundle.json"])
        settings = load_run_record(store, bundle["requested_config_ref"])
        ledger = load_run_record(store, store.projections["budget-ledger.json"])
        reporters = resolve_reporters(settings.get("reporters", []), "run", expected=store.state["admission"]["reporters"])
        row = {"run_id": store.run_id, "status": bundle["status"], "mode": bundle["mode"],
            "stages": bundle["stages"], "error": bundle["error"], "method_id": settings["method"]["plugin_id"],
            "provider_id": settings["llm"]["provider_plugin_id"], "model": settings["llm"]["model"], **ledger,
            "solve": load_run_record(store, bundle["solve_result_ref"]) if bundle["solve_result_ref"] else None}
        refs, errors = render_reports(reporters, {"id": store.run_id, "rows": [row],
            "summary": {"policy": "Structural checks do not establish semantic correctness. Unknown resources stay null."}},
            "run", lambda name, raw, ref: store.write(name, raw, ref["artifact_id"]))
        bundle.update(report_refs=refs, report_errors=errors)
        if errors:
            store.json("diagnostics/report-errors.json", {"schema_version": "0.1.0", "errors": errors}, "report-errors")
        store.emit("reports_rendered", report_errors=errors)
        bundle.update(artifacts=list(store.refs),
            public_projections={name: ref for name, ref in store.projections.items() if name != "bundle.json"})
        store.json("bundle.json", bundle, "bundle")
        store.checkpoint()
        return {"run_id": store.run_id, "status": bundle["status"], "report_refs": refs, "report_errors": errors}
    finally:
        store.close()


def _prepare_candidate(store: RunStore, problem: Path, config: Path, settings: dict[str, Any],
                 ledger: dict[str, Any], offline: bool, plan: AdmissionPlan) -> tuple[dict[str, Any], dict[str, Any]]:
    method = plan.method
    source_problem = read_public_bytes(problem)
    public = parse_json(source_problem)
    validate_problem(public)
    data_refs = []
    data_content = {}
    data_views = {}
    view_records = {}
    if plan.data_loader is None:
        raise RunError("unknown_plugin", "admission", "No admitted public DataLoader is available.")
    for index, data in enumerate(public["data_refs"]):
        raw = read_public_bytes(public_path(problem.parent, data["path"]), max_bytes=8 * 1024 * 1024)
        view = plan.data_loader.load(raw, data)
        data_views[data["data_id"]] = view
        view_ref = store.write(f"data-views/{index}.{view.format}", view.content, f"view-{data['data_id']}")
        view_records[data["data_id"]] = {**view.metadata(), "content_ref": view_ref}
        ref = store.write(f"data/{index}.{data['format']}", raw, data["data_id"])
        data_refs.append(ref)
        data_content[data["data_id"]] = raw
        data["path"] = ref["relative_path"]
        data["sha256"] = ref["sha256"]
    problem_ref = store.json("public-problem.json", public, public["problem_id"])
    store.json("dataset-manifest.json", {"schema_version": "0.2.0", "data": data_refs}, "dataset")
    data_views_ref = store.json("data-views.json", {"schema_version": "0.1.0", "loader": plan.data_loader.binding,
        "limits": plan.data_loader.limits, "views": view_records}, "data-views")
    if method.manifest["capabilities"].get("data_access", "full") == "full" and any(not view.complete for view in data_views.values()):
        raise RunError("capability_mismatch", "admission", "Method requires full data; the admitted modeling view is incomplete.")
    public_config = deepcopy(settings)
    if "root" in public_config["store"]["config"]:
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
                            tuple(deepcopy(store.state.get("clarification_responses", []))), MappingProxyType(data_views),
                            MappingProxyType({**plan.execution.backend_binding["manifest"]["capabilities"]["code_generation"],
                                "model_backend": settings["model_backend"]["plugin_id"],
                                "solver": settings["solver"]["plugin_id"],
                                "solver_name": plan.execution.solver_binding["manifest"]["display_name"]})
                            if plan.execution and "code_generation" in plan.execution.backend_binding["manifest"]["capabilities"] else None)
    store.state["method_started"] = True
    store.checkpoint()
    try:
        outcome = method.run(deepcopy(settings["method"]["config"]), deepcopy(public), context,
                             checkpoint=store.state.get("method_checkpoint"))
    finally:
        if isinstance(gateway, Gateway):
            ledger.update(gateway.ledger)
            store.json("llm-trace.json", {"schema_version": "0.2.0", "attempts": gateway.trace,
                "data_views_ref": data_views_ref}, "llm-trace")
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
    return persist_proposal(store, outcome.proposal, public, problem_ref, context.problem_sha256,
                             settings, offline, plan, replay)


def resume_run(run: Path, *, cancellation: CancellationToken | None = None,
               strategy: str = "continue", answers: Path | None = None,
               revised_problem: Path | None = None) -> RunResult:
    """Continue fixed work, or explicitly start a derived semantic rerun with carried usage."""
    if strategy not in {"continue", "rerun"}:
        raise RunError("invalid_resume_strategy", "admission", "Resume strategy must be continue or rerun.")
    if revised_problem is not None and answers is None:
        raise RunError("invalid_clarification_response", "admission", "A problem revision needs a bound clarification response.")
    store = open_run_store(saved_store_selection(run), run.parent, resume=run,
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
        host = {"python": platform.python_version(), "sdk_sha256": sdk_sha256(), "packages": {name: version(name) for name in ("PyYAML", "jsonschema")}}
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
            request = load_run_record(store, store.state["clarification_request_ref"])
            receipts = store.interrupted_publications.get("clarifications/" + request["request_id"] + "/response.json", [])
            if receipts:
                response = validate_clarification_response(load_run_record(store, receipts[-1]), request)
                if response["action"] != "confirm":
                    raise RunError("checkpoint_incompatible", "admission", "A same-run response receipt must confirm existing declarations.")
                store.accept_publications()
                _accept_clarification_response(store, request, response, receipts[-1])
        if answers is not None:
            if strategy != "continue" or store.state.get("clarification_request_ref") is None:
                raise RunError("invalid_clarification_response", "admission", "Answers need an existing clarification and the continue strategy.")
            request = load_run_record(store, store.state["clarification_request_ref"])
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
            public = load_run_record(store, store.projections["public-problem.json"])
            RunMethodResources(store, public, settings, plan).reconcile()
        reconcile_formulation(store)
        if (store.state.get("artifact_ref") is None and store.state.get("method_checkpoint") is None
                and store.state.get("method_started")):
            raise RunError("checkpoint_unsupported", "admission", "No completed stage or supported internal method checkpoint exists.")
        reconcile_execution(store, settings)
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
            data = read_public_bytes(public_path(problem.parent, ref["path"]), max_bytes=8 * 1024 * 1024)
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
            try:
                # Fast path only; unreadable checkpoints fall through to the verified resume below.
                with_state = parse_json(read_public_bytes(child_path / "checkpoint.json"))["payload"]["state"]
            except (ValueError, OSError, KeyError, TypeError):
                with_state = None
            if with_state is None or "sources" not in with_state:
                child = open_run_store(saved_store_selection(store.path), store.path.parent, resume=child_path,
                                       cancellation=cancellation)
                try:
                    if child.state.get("derivation_identity") != identity:
                        raise RunError("checkpoint_incompatible", "admission", "Derived initialization identity changed.")
                    child.accept_publications()
                    return _initialize_derived_run(child, store, resource_records, problem=problem, response=response)
                finally:
                    child.close()
            return resume_run(child_path, cancellation=cancellation)
    child = open_run_store(saved_store_selection(store.path), store.path.parent, cancellation=cancellation)
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
                            problem: Path | None = None, response: dict[str, Any] | None = None,
                            config: Path | None = None, edit: dict[str, Any] | None = None) -> RunResult:
    parent_refs = [child.write("parent/" + store.run_id + "/" + ref["relative_path"],
        read_public_bytes(public_path(store.path, ref["relative_path"])), ref["artifact_id"],
        ref.get("schema_version")) for ref in store.refs]
    parent_checkpoint_ref = child.write("parent/" + store.run_id + "/checkpoint.json",
        read_public_bytes(store.path / "checkpoint.json"), "parent-checkpoint", "0.1.0")
    ledger = deepcopy(store.state["ledger"])
    response_ref = child.json("clarification-response.json", response, "revision-response") if response is not None else None
    lineage_ref = child.json("lineage.json", {"schema_version": "0.1.0",
        "operation": "assisted_revision" if edit is not None else "clarification_revision" if problem is not None else "derived_rerun", "parent_run_id": store.run_id,
        **({"edit": edit} if edit is not None else {}),
        "clarification_response_ref": response_ref,
        "parent_budget_ledger": ledger, "input_hashes": store.state["sources"],
        "parent_checkpoint_ref": parent_checkpoint_ref,
        "parent_artifacts": parent_refs, "parent_resource_records": resource_records, "reused_records": [],
        "policy": "Fresh method execution; previous paid/unknown usage and reservations count against the configured caps."}, "lineage")
    child.state.update(lineage_ref=lineage_ref, inherited_ledger=ledger, ledger=deepcopy(ledger), interactive=store.state.get("interactive", False))
    if edit is not None:
        child.state["assisted"] = True
        child.state["ledger"]["candidates"] += 1
    return _run_problem(problem or Path(store.state["problem"]), config or Path(store.state["config"]), child,
                        offline=False if edit is not None else store.state["offline"])
