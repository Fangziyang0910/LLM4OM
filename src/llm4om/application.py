"""Run one public problem through the explicitly offline S01 flow."""

import hashlib
import platform
from copy import deepcopy
from importlib.metadata import version
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm4om.contracts import (
    RunError, parse_json, public_path, read_config, read_public_bytes, validate_config, validate_csv, validate_problem,
)
from llm4om.mock import load_mock_output
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
    store = RunStore(output_root or configured_root)
    store.emit("run_started", mode="offline_mock")
    ledger: dict[str, Any] = {"schema_version": "0.2.0", "llm_attempts": 0,
                             "solver_calls": 0, "external_llm_requests": 0, "candidates": 0, "total_tokens": None,
                             "cost": 0, "evidence_origin": "mock_fixture"}
    error_record = None
    artifact_ref = None
    settings_valid = False
    stages = {name: {"status": "not_available", "reason": "Stage has not run."}
              for name in ("formulation", "code", "solve")}
    try:
        if config_error:
            if isinstance(config_error, RunError):
                raise config_error
            raise RunError("invalid_config", "validation", "Cannot read a valid RunConfig.")
        if not offline:
            raise RunError("offline_required", "admission", "S01 requires explicit offline mode.")
        validate_config(settings)
        settings_valid = True
        artifact_ref, stages = _run_offline(store, problem, config, settings, ledger)
        status = "artifact_ready"
    except (RunError, ValueError, KeyError, TypeError) as error:
        status = "failed"
        error_record = {"code": error.code if isinstance(error, RunError) else "invalid_input",
                        "stage": error.stage if isinstance(error, RunError) else "validation",
                        "message": str(error) if isinstance(error, RunError) else "Cannot process the public input or Mock artifact."}
    store.json("budget-ledger.json", ledger, "budget")
    store.emit("run_finished", status=status, error=error_record)
    if settings_valid and any(reporter["plugin_id"] == "llm4om.reporters.markdown" for reporter in settings.get("reporters", [])):
        report = (f"# LLM4OM run {store.run_id}\n\nMode: offline_mock. Status: {status}.\n\n"
                  "| Stage | Status |\n|---|---|\n" +
                  "".join(f"| {name} | {stage['status']} |\n" for name, stage in stages.items()) +
                  "\nMock replays a hand-authored artifact. No external LLM or solver was called.\n"
                  "Structural checks do not establish semantic correctness.\n")
        if error_record:
            report += f"\nError: {error_record['code']} ({error_record['stage']}).\n"
        store.write("reports/report.md", report.encode(), "report")
    store.json("bundle.json", {"schema_version": "0.2.0", "run_id": store.run_id,
               "mode": "offline_mock", "status": status, "stages": stages,
               "error": error_record, "model_artifact_ref": artifact_ref,
               "execution_plan": {name: {"requested_plugin_id": settings.get(name, {}).get("plugin_id"),
                    "status": "not_available", "reason": "Offline profile only validates and stores public artifacts."}
                    for name in ["compiler", "model_backend", "solver", "executor"]} if settings_valid else {},
               "artifacts": list(store.refs)}, "bundle")
    return RunResult(store.run_id, store.path, status)


def _run_offline(store: RunStore, problem: Path, config: Path, settings: dict[str, Any],
                 ledger: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
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
               "llm4om": "0.1.0", "packages": {name: version(name) for name in ["PyYAML", "jsonschema"]},
               "mode": "offline_mock", "method_variant": "hand_authored_fixture_replay"}, "environment")
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
    artifact_ref = store.json("candidates/001/artifact.json", artifact, artifact["artifact_id"])
    store.json("candidates/001/candidate.json", {"schema_version": "0.2.0", "candidate_id": "001",
               "run_id": store.run_id, "parent_ids": [], "sequence_no": 1, "artifact_ref": artifact_ref,
               "created_by": {"method_id": settings["method"]["plugin_id"], "method_version": "0.1.0",
                              "variant_id": "hand_authored_fixture_replay", "call_ids": ["mock-1"],
                              "prompt_hash": None, "role": "formulation"}, "status": "proposed"}, "001")
    ledger["candidates"] = 1
    store.emit("formulation_saved", artifact_ref=artifact_ref, call_id="mock-1", evidence_origin="mock_fixture")
    stages = {**artifact["stage_status"], "solve": {
        "status": "not_available", "reason": "Offline mode does not compile or call a solver."}}
    store.json("evaluation.json", {"schema_version": "0.2.0", "protocol_id": "llm4om.eval.public-v0.1",
               "formulation_validation": {"status": "pass", "level": "structural"},
               "code_validation": {"status": "not_available"},
               "semantic_validation": {"status": "not_available"}}, "evaluation")
    return artifact_ref, stages
