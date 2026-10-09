"""Replay a public Formulation and optionally compile and solve its grounded IR."""

import hashlib
import platform
from copy import deepcopy
from importlib.metadata import version
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from typing import Any

from llm4om.contracts import (
    RunError, parse_json, public_path, read_config, read_public_bytes, validate_config, validate_csv, validate_problem,
)
from llm4om.mock import load_mock_output
from llm4om.linear import CompiledCode, compile_ir
from llm4om.highs import runtime_versions, solve_highs
from llm4om.storage import RunStore


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
    error_record = None
    artifact_ref = None
    settings_valid = False
    solve_ref = None
    execution_ref = None
    stages: dict[str, Any] = {name: {"status": "not_available", "reason": "Stage has not run."}
              for name in ("formulation", "code", "solve")}
    try:
        if config_error:
            if isinstance(config_error, RunError):
                raise config_error
            raise RunError("invalid_config", "validation", "Cannot read a valid RunConfig.")
        validate_config(settings)
        settings_valid = True
        if not offline and settings["executor"]["plugin_id"] != "llm4om.executors.trusted_local":
            raise RunError("offline_required", "admission", "Select trusted_local to compile and solve, or use offline mode.")
        if not offline and settings["budget"]["max_solver_calls"] < 1:
            raise RunError("budget_exhausted", "admission", "Real solving requires one Solver call slot.")
        if not offline:
            runtime_versions()
            mode = "trusted_local"
        artifact_ref, stages = _prepare_candidate(store, problem, config, settings, ledger, offline)
        status = "artifact_ready"
        if not offline:
            artifact_ref, compiled = _compile_candidate(store, artifact_ref, settings)
            stages["code"] = {"status": "available", "reason": None}
            solve_ref, execution_ref, execution_error = _execute_candidate(store, compiled, artifact_ref, settings, ledger)
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
    if stages["code"]["status"] == "available":
        store.json("evaluation.json", {"schema_version": "0.2.0", "protocol_id": "llm4om.eval.public-v0.1",
                   "formulation_validation": {"status": "pass", "level": "structural"},
                   "code_validation": {"status": "pass", "level": "deterministic_compilation"},
                   "semantic_validation": {"status": "not_available"}}, "evaluation")
    store.json("budget-ledger.json", ledger, "budget")
    store.emit("run_finished", status=status, error=error_record)
    if settings_valid and any(reporter["plugin_id"] == "llm4om.reporters.markdown" for reporter in settings.get("reporters", [])):
        report = (f"# LLM4OM run {store.run_id}\n\nMode: {mode}. Status: {status}.\n\n"
                  "| Stage | Status |\n|---|---|\n" +
                  "".join(f"| {name} | {stage['status']} |\n" for name, stage in stages.items()) +
                  "\nFormulation source: hand-authored Mock fixture. External LLM requests: 0.\n"
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
               "final_candidate_id": "001" if status == "completed" else None,
               "execution_plan": {name: {"requested_plugin_id": settings.get(name, {}).get("plugin_id"),
                    "resolved_plugin_id": settings[name]["plugin_id"] if resource_status[name] != "not_available" else None,
                    "status": resource_status[name],
                    "reason": None if resource_status[name] == "available" else "Resource did not complete successfully."}
                    for name in ["compiler", "model_backend", "solver", "executor"]} if settings_valid else {},
               "artifacts": list(store.refs)}, "bundle")
    return RunResult(store.run_id, store.path, status)


def _prepare_candidate(store: RunStore, problem: Path, config: Path, settings: dict[str, Any],
                 ledger: dict[str, Any], offline: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    source_problem = read_public_bytes(problem)
    public = parse_json(source_problem)
    validate_problem(public)
    data_refs = []
    for index, data in enumerate(public["data_refs"]):
        raw = read_public_bytes(public_path(problem.parent, data["path"]))
        if data["sha256"] and hashlib.sha256(raw).hexdigest() != data["sha256"]:
            raise RunError("data_hash_mismatch", "validation", "A data file does not match its declared SHA-256.")
        validate_csv(raw, data["schema"])
        ref = store.write(f"data/{index}.csv", raw, data["data_id"])
        data_refs.append(ref)
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
                            **(runtime_versions() if not offline else {})},
               "mode": "offline_mock" if offline else "trusted_local",
               "method_variant": "hand_authored_fixture_replay"}, "environment")
    ledger["llm_attempts"] += 1
    store.emit("mock_call_started", call_id="mock-1")
    response = public_path(config.parent, settings["llm"]["config"]["response_artifact"])
    output = load_mock_output(response, public, hashlib.sha256(source_problem).hexdigest())
    artifact, formulation = output.artifact, output.formulation
    ir_ref = formulation["structured_ir_ref"]
    formulation["structured_ir_ref"] = store.json(
        "candidates/001/structured-ir.json", output.structured_ir, ir_ref["artifact_id"])
    formulation_ref = store.json("candidates/001/formulation.json", formulation, formulation["formulation_id"])
    artifact["problem_ref"] = problem_ref
    artifact["formulation_ref"] = formulation_ref
    artifact["provenance"]["replay"] = {"mode": "offline_mock", "call_id": "mock-1",
                                        "response_sha256": output.source_sha256}
    artifact_ref = store.json("candidates/001/artifact.json" if offline else "candidates/001/formulation-snapshot.json", artifact, artifact["artifact_id"])
    store.json("candidates/001/candidate.json" if offline else "candidates/001/candidate-snapshot.json", {"schema_version": "0.2.0", "candidate_id": "001",
               "run_id": store.run_id, "parent_ids": [], "sequence_no": 1, "artifact_ref": artifact_ref,
               "created_by": {"method_id": settings["method"]["plugin_id"], "method_version": "0.1.0",
                              "variant_id": "hand_authored_fixture_replay", "call_ids": ["mock-1"],
                              "prompt_hash": None, "role": "formulation"}, "status": "proposed"}, "001")
    ledger["candidates"] = 1
    store.emit("formulation_saved", artifact_ref=artifact_ref, call_id="mock-1", evidence_origin="mock_fixture")
    stages = {**artifact["stage_status"], "solve": {
        "status": "not_available", "reason": "Solve has not run."}}
    store.json("evaluation.json", {"schema_version": "0.2.0", "protocol_id": "llm4om.eval.public-v0.1",
               "formulation_validation": {"status": "pass", "level": "structural"},
               "code_validation": {"status": "not_available"},
               "semantic_validation": {"status": "not_available"}}, "evaluation")
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
                       settings: dict[str, Any], ledger: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any], RunError | None]:
    started = datetime.now(timezone.utc).isoformat()
    timer = monotonic()
    ledger["solver_calls"] += 1
    store.emit("solver_started", solver_id=settings["solver"]["plugin_id"])
    out, err = StringIO(), StringIO()
    error = None
    solve_ref = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            solve = solve_highs(compiled, settings["solver"].get("options", {}))
        variables = solve.pop("variables")
        solve["schema_version"] = "0.2.0"
        solve["solution_ref"] = store.json("candidates/001/solution.json", {
            "schema_version": "0.2.0", "variables": variables, "evidence_origin": "trusted_highs_api"}, "solution") if variables is not None else None
        solve_ref = store.json("candidates/001/solve-result.json", solve, "solve-result")
        store.emit("solver_finished", solve_result_ref=solve_ref, termination=solve["termination"])
        if solve["termination"] == "error":
            error = RunError("solver_error", "solve", "HiGHS reports an execution error.")
    except RunError as failure:
        error = failure
    except (RuntimeError, ArithmeticError) as failure:
        error = RunError("solver_error", "solve", "Cannot build or solve the compiled model.")
    output_ref = store.write("candidates/001/stdout.txt", out.getvalue().encode(), "stdout")
    stderr_ref = store.write("candidates/001/stderr.txt", err.getvalue().encode(), "stderr")
    execution_ref = store.json("candidates/001/execution.json", {"schema_version": "0.2.0",
        "execution_id": "execution-001", "mode": "trusted_local", "status": "failed" if error else "completed",
        "start": started, "end": datetime.now(timezone.utc).isoformat(), "exit_code": None,
        "wall_time_s": monotonic() - timer, "resources": {"cpu_time_s": None, "peak_memory_bytes": None},
        "output_truncated": False, "solve_result_ref": solve_ref, "stdout_ref": output_ref,
        "stderr_ref": stderr_ref, "diagnostics": [{"code": error.code, "stage": error.stage}] if error else []}, "execution-001")
    candidate = parse_json(read_public_bytes(store.path / "candidates/001/candidate-snapshot.json"))
    candidate.update(artifact_ref=artifact_ref, status="executed" if error else "selected")
    store.json("candidates/001/candidate.json", candidate, "001")
    return solve_ref, execution_ref, error
