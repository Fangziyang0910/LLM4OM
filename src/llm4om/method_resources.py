"""Run-owned public script execution, evidence, budgets and replay identity."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from llm4om.contracts import RunError, parse_json, public_path, read_public_bytes, validate_bindings, validate_worker_response
from llm4om.executors import run_container
from llm4om.methods import LLMResponse, MethodOutcome, ModelProposal, ScriptCodeProposal
from llm4om.preflight import AdmissionPlan
from llm4om.storage import RunStore


class RunMethodResources:
    def __init__(self, store: RunStore, public: dict[str, Any], settings: dict[str, Any], plan: AdmissionPlan,
                 *, responses: list[LLMResponse] | None = None) -> None:
        self.store, self.public, self.settings, self.plan = store, public, settings, plan
        self.responses = responses if responses is not None else []

    async def assess(self, candidate_id: str, proposal: ModelProposal, *, parent_id: str | None = None,
                     change_reason: str | None = None) -> dict[str, Any]:
        from llm4om.application import _persist_proposal, _compile_candidate, _execute_candidate

        store = self.store
        store.cancellation.check()
        if (not isinstance(candidate_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", candidate_id)
                or not isinstance(proposal, ModelProposal)):
            raise RunError("invalid_candidate", "formulation", "A candidate needs a bounded ID and a ModelProposal.")
        if store.state["offline"]:
            raise RunError("capability_mismatch", "admission", "Candidate assessment requires an online Solver execution plan.")
        if self.plan.snapshot["method_profile"] != "grounded_candidates/0.1.0":
            raise RunError("capability_mismatch", "admission", "Candidate assessment requires the admitted grounded_candidates profile.")
        if parent_id is not None and (not isinstance(parent_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", parent_id)):
            raise RunError("invalid_candidate", "formulation", "A repair parent needs a bounded candidate ID.")
        if parent_id is not None and (not isinstance(change_reason, str) or not change_reason.strip() or len(change_reason) > 4096):
            raise RunError("invalid_candidate", "formulation", "A repair needs a public change reason.")
        def encode(value: Any) -> dict[str, str]:
            if not isinstance(value, bytes):
                raise TypeError("Unsupported candidate value.")
            return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
        try:
            raw = json.dumps({"proposal": asdict(proposal), "parent_id": parent_id, "change_reason": change_reason},
                             sort_keys=True, allow_nan=False, default=encode).encode()
        except (TypeError, ValueError) as failure:
            raise RunError("invalid_candidate", "formulation", "Candidate metadata must contain finite JSON values.") from failure
        if len(raw) > 8 * 1024 * 1024:
            raise RunError("invalid_candidate", "formulation", "Candidate metadata exceeds its byte limit.")
        parse_json(raw)
        identity = hashlib.sha256(raw).hexdigest()
        records = store.state.setdefault("candidate_assessments", {})
        prior = records.get(candidate_id)
        if prior is not None:
            if prior["identity"] != identity:
                raise RunError("checkpoint_incompatible", "formulation", "Candidate ID was rebound to another proposal or parent.")
            if prior.get("result_ref") is not None:
                return deepcopy(self._load(prior["result_ref"]))
            raise RunError("execution_outcome_unknown", "execution", "An admitted candidate has no assessment receipt; it will not be repeated.")
        if parent_id is not None and (parent_id not in records or records[parent_id].get("result_ref") is None):
            raise RunError("invalid_candidate", "formulation", "A repair parent must be an assessed candidate in this run.")
        ledger = store.state["ledger"]
        if time.time() >= self.plan.deadline:
            raise RunError("deadline_exhausted", "formulation", "No shared run deadline remains.")
        if ledger["candidates"] >= self.settings["budget"]["max_candidates"]:
            raise RunError("budget_exhausted", "formulation", "No shared candidate slot remains.")
        if parent_id is not None and ledger.get("repairs", 0) >= self.settings["budget"]["max_repairs"]:
            raise RunError("budget_exhausted", "formulation", "No shared repair slot remains.")
        ledger["candidates"] += 1
        ledger["repairs"] = ledger.get("repairs", 0) + int(parent_id is not None)
        records[candidate_id] = {"identity": identity, "result_ref": None}
        store.state.update(candidate_id=candidate_id, candidate_parent_ids=[parent_id] if parent_id else [],
                           candidate_change_reason=change_reason, candidate_assessment_pending=True,
                           artifact_ref=None, solve_ref=None, execution_ref=None, executed_artifact_ref=None,
                           phase="candidate_pending")
        store.checkpoint()
        path = "candidates/" + candidate_id + "/"
        proposal_ref = store.write(path + "supplied-proposal.txt", raw, candidate_id + "-supplied-proposal")
        error = None
        artifact_ref = solve_ref = execution_ref = None
        stages: dict[str, Any] = {name: {"status": "not_available", "reason": "Stage has not run."}
                  for name in ("formulation", "code", "solve")}
        try:
            public_ref = store.projections["public-problem.json"]
            replay = {"mode": self.responses[-1].evidence_origin if self.responses else "no_calls",
                      "call_ids": [response.call_id for response in self.responses],
                      "response_sha256": self.responses[-1].source_sha256 if self.responses else None}
            artifact_ref, stages = _persist_proposal(store, proposal, self.public, public_ref,
                hashlib.sha256(read_public_bytes(Path(store.state["problem"]))).hexdigest(),
                self.settings, False, self.plan, replay)
            artifact_ref, compiled = _compile_candidate(store, artifact_ref, self.settings)
            stages["code"] = {"status": "available", "reason": None}
            store.state.update(artifact_ref=artifact_ref, phase="code_done")
            solve_ref, execution_ref, error = _execute_candidate(store, compiled, artifact_ref, self.settings, ledger, self.plan)
            artifact_ref = store.state.get("executed_artifact_ref", artifact_ref)
            if solve_ref is not None:
                stages["solve"] = {"status": "available", "reason": None}
        except (RunError, ValueError, KeyError, TypeError) as failure:
            if not isinstance(failure, RunError):
                failure = RunError("invalid_method_outcome", "formulation", "Candidate output does not match the declared model contract.")
            if failure.code == "run_cancelled":
                raise
            error = failure
        solve = self._load(solve_ref) if solve_ref is not None else None
        result = {"schema_version": "0.1.0", "candidate_id": candidate_id, "proposal_sha256": identity,
                  "proposal_ref": proposal_ref,
                  "status": "invalid" if error is not None and execution_ref is None else "executed",
                  "stages": stages, "artifact_ref": artifact_ref, "execution_result_ref": execution_ref,
                  "solve_result_ref": solve_ref, "has_primal_solution": solve["has_primal_solution"] if solve else False,
                  "termination": solve["termination"] if solve else None,
                  "diagnostics": [{"code": error.code, "stage": error.stage, "message": str(error)}] if error else []}
        candidate_ref = store.projections.get(path + "candidate-snapshot.json")
        candidate = self._load(candidate_ref) if candidate_ref else {
            "schema_version": "0.2.0", "candidate_id": candidate_id, "run_id": store.run_id,
            "sequence_no": ledger["candidates"], "parent_ids": [parent_id] if parent_id else [],
            "change_reason": change_reason, "artifact_ref": artifact_ref,
            "created_by": {"method_id": self.plan.method.manifest["plugin_id"],
                "method_version": self.plan.method.manifest["plugin_version"],
                "variant_id": (self.plan.method.manifest["source"] or {}).get("variant_id", "grounded_candidates"),
                "call_ids": [response.call_id for response in self.responses], "prompt_hash": None, "role": "formulation"}}
        candidate.update(status=result["status"], artifact_ref=artifact_ref)
        store.json(path + "candidate.json", candidate, candidate_id)
        records[candidate_id]["result_ref"] = store.json(path + "assessment.json", result, candidate_id + "-assessment")
        store.state.update(phase="method_pending", stages=stages)
        store.checkpoint()
        store.emit("candidate_assessed", candidate_id=candidate_id, assessment_ref=records[candidate_id]["result_ref"])
        return deepcopy(result)

    def select(self, candidate_id: str, *, rule: str, reason: str) -> MethodOutcome:
        store = self.store
        store.cancellation.check()
        if not all(isinstance(value, str) and value.strip() and len(value) <= 4096 for value in (rule, reason)):
            raise RunError("invalid_selection", "formulation", "Selection needs a declared rule and a public reason.")
        if not isinstance(candidate_id, str):
            raise RunError("invalid_selection", "formulation", "The selection needs a candidate ID.")
        record = store.state.get("candidate_assessments", {}).get(candidate_id)
        if record is None or record.get("result_ref") is None:
            raise RunError("invalid_selection", "formulation", "The selected candidate must be assessed in this run.")
        result = self._load(record["result_ref"])
        if result["diagnostics"] or result["artifact_ref"] is None or result["solve_result_ref"] is None:
            raise RunError("invalid_selection", "formulation", "Selection requires a valid candidate with trusted completed Solver evidence.")
        selection = {"schema_version": "0.1.0", "candidate_id": candidate_id,
                     "rule": rule, "reason": reason, "assessment_ref": record["result_ref"]}
        previous = store.projections.get("candidate-selection.json")
        if previous is not None and self._load(previous) != selection:
            raise RunError("invalid_selection", "formulation", "A saved final selection is immutable.")
        store.json("candidate-selection.json", selection, "candidate-selection")
        candidate = self._load(store.projections["candidates/" + candidate_id + "/candidate.json"])
        candidate["status"] = "selected"
        store.json("candidates/" + candidate_id + "/candidate.json", candidate, candidate_id)
        store.state.update(candidate_id=candidate_id, artifact_ref=result["artifact_ref"], stages=result["stages"],
                           solve_ref=result["solve_result_ref"], execution_ref=result["execution_result_ref"],
                           candidate_assessment_pending=False, phase="execute_done")
        store.checkpoint()
        return MethodOutcome("candidate_selected", candidate_id, None)

    def selected(self, candidate_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        store = self.store
        if (candidate_id is None or candidate_id != store.state.get("candidate_id")
                or store.state.get("candidate_assessment_pending") or "candidate-selection.json" not in store.projections):
            raise RunError("invalid_method_outcome", "formulation", "A reference-only outcome requires a saved selection.")
        selection = self._load(store.projections["candidate-selection.json"])
        if selection["candidate_id"] != candidate_id:
            raise RunError("invalid_method_outcome", "formulation", "Outcome differs from the saved selection.")
        return store.state["artifact_ref"], store.state["stages"]

    def record(self, name: str, value: bytes) -> dict[str, Any]:
        self.store.cancellation.check()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", name) or len(value) > 8 * 1024 * 1024:
            raise RunError("invalid_method_artifact", "storage", "Method artifacts need a bounded public filename and bytes.")
        if name.endswith(".json"):
            parse_json(value)
        return self.store.write("method/" + name, value, "method-" + name)

    def emit(self, event: dict[str, Any]) -> None:
        value = parse_json(json.dumps(event, allow_nan=False).encode())
        self.store.emit("method_event", method_event=value)

    async def execute(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]:
        # The event-loop thread owns checkpoints and ledger updates throughout execution.
        return self._execute(execution_id, code)

    def reuse(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]:
        if execution_id not in self.store.state.get("method_executions", {}):
            raise RunError("invalid_method_outcome", "execution", "Selected script has no admitted execution record.")
        return self._execute(execution_id, code)

    def reconcile(self) -> None:
        """Accept complete execution receipts before the application clears them."""
        for candidate_id, record in self.store.state.get("candidate_assessments", {}).items():
            receipts = self.store.interrupted_publications.get("candidates/" + candidate_id + "/assessment.json", [])
            if record.get("result_ref") is not None or not receipts:
                continue
            result = self._load(receipts[-1])
            if result["candidate_id"] != candidate_id or result["proposal_sha256"] != record["identity"]:
                raise RunError("checkpoint_incompatible", "execution", "Candidate assessment receipt identity differs.")
            self.store.accept_publications()
            record["result_ref"] = receipts[-1]
            self.store.state["phase"] = "method_pending"
            self.store.checkpoint()
        for execution_id, record in self.store.state.get("method_executions", {}).items():
            receipts = self.store.interrupted_publications.get("method/executions/" + execution_id + "/result.json", [])
            if record.get("result_ref") is not None or not receipts:
                continue
            result = self._load(receipts[-1])
            source = read_public_bytes(public_path(self.store.path, result["source_ref"]["relative_path"]))
            data = read_public_bytes(public_path(self.store.path, result["data_ref"]["relative_path"]))
            self.reuse(execution_id, ScriptCodeProposal(source.decode(), record["identity"]["source_sha256"],
                       record["identity"]["data_bindings"], data))
        selections = self.store.interrupted_publications.get("candidate-selection.json", [])
        if selections:
            selection = self._load(selections[-1])
            record = self.store.state.get("candidate_assessments", {}).get(selection["candidate_id"])
            if record is None or selection["assessment_ref"] != record.get("result_ref"):
                raise RunError("checkpoint_incompatible", "execution", "Selection receipt differs from the assessed candidate.")
            self.store.accept_publications()
            self.select(selection["candidate_id"], rule=selection["rule"], reason=selection["reason"])

    def _execute(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]:
        store, plan = self.store, self.plan
        store.cancellation.check()
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", execution_id)
                or not isinstance(code, ScriptCodeProposal) or code.schema_version != "0.1.0"
                or code.representation_kind != "native_script" or not code.source
                or hashlib.sha256(code.source.encode()).hexdigest() != code.source_sha256):
            raise RunError("invalid_script_proposal", "execution", "Invalid raw script identity or source bytes.")
        validate_bindings({"data_bindings": code.data_bindings}, self.public)
        if len(code.data_json) > 8 * 1024 * 1024 or len(code.source.encode()) > 8 * 1024 * 1024:
            raise RunError("invalid_script_proposal", "execution", "Script or derived data exceeds its byte limit.")
        parse_json(code.data_json)
        identity = {"source_sha256": code.source_sha256, "data_sha256": hashlib.sha256(code.data_json).hexdigest(),
                    "data_bindings": code.data_bindings, "admission": store.state["admission"]}
        identity = parse_json(json.dumps(identity, allow_nan=False).encode())
        records = store.state.setdefault("method_executions", {})
        prior = records.get(execution_id)
        path = "method/executions/" + execution_id + "/"
        if prior is not None:
            if prior["identity"] != identity:
                raise RunError("checkpoint_incompatible", "execution", "Script execution ID was rebound to different inputs or resources.")
            ref = prior.get("result_ref")
            if ref is None:
                receipts = store.interrupted_publications.get(path + "result.json", [])
                ref = receipts[-1] if receipts else None
            if ref is None:
                raise RunError("execution_outcome_unknown", "execution", "An admitted script execution has no completed evidence; it will not be repeated.")
            result = self._load(ref)
            if (result["identity"] != identity or result["execution_id"] != execution_id
                    or result["solver_call"] != prior["solver_call"]):
                raise RunError("checkpoint_incompatible", "execution", "Script execution receipt identity differs.")
            if prior.get("result_ref") is None:
                store.accept_publications()
                prior["result_ref"] = ref
                store.checkpoint()
            store.emit("method_execution_reused", execution_id=execution_id)
            return deepcopy(result)
        if plan.snapshot["method_profile"] not in ("native_script/0.1.0", "native_script/0.2.0"):
            raise RunError("capability_mismatch", "execution", "The admitted method has no raw-script execution profile.")
        ledger = store.state["ledger"]
        remaining = plan.deadline - time.time()
        if remaining <= 0:
            raise RunError("deadline_exhausted", "execution", "No run deadline remains.")
        if ledger["solver_calls"] + 2 > self.settings["budget"]["max_solver_calls"]:
            raise RunError("budget_exhausted", "execution", "Script and independent collector require two available Solver slots.")
        limits = dict(self.settings["executor"]["config"])
        limits["wall_time_s"] = min(limits["wall_time_s"], remaining)
        byte_limit = min(limits.get("output_limit_bytes", 1048576), 8 * 1024 * 1024)
        source_ref = store.write(path + "code.py", code.source.encode(), execution_id + "-source")
        data_ref = store.write(path + "data.json", code.data_json, execution_id + "-data")
        ledger["solver_calls"] += 1
        ledger["script_executions"] = ledger.get("script_executions", 0) + 1
        ledger["source_optimize_calls"] = None
        ledger["source_optimize_measurement"] = "untrusted_hook_observations_only"
        records[execution_id] = {"identity": identity, "result_ref": None, "solver_call": ledger["solver_calls"]}
        store.checkpoint()
        request = {"schema_version": "0.1.0", "source_sha256": code.source_sha256, "data_json": code.data_json.decode(),
                   "wall_time_s": limits["wall_time_s"], "output_limit_bytes": byte_limit}
        execution = run_container(["python", "-I", "-m", "llm4om.script_worker", "/input/request.json"],
            {"request.json": json.dumps(request, allow_nan=False).encode(), "model.py": code.source.encode()}, limits,
            image=plan.snapshot["worker"]["image_id"], deadline=plan.deadline, cancellation=store.cancellation)
        execution_details = asdict(execution)
        execution_details["stdout"] = execution.stdout.decode(errors="replace")
        execution_details["stderr"] = execution.stderr.decode(errors="replace")
        worker_ref = store.json(path + "worker.json", execution_details, execution_id + "-worker")
        if execution.status != "completed" or execution.exit_code != 0:
            raise RunError("run_cancelled" if execution.status == "cancelled" else "execution_" + execution.status,
                           "execution", "Raw-script Worker did not return a complete record.")
        payload = parse_json(execution.stdout)
        if payload.get("schema_version") != "0.1.0" or payload.get("source_sha256") != code.source_sha256:
            raise RunError("worker_protocol_error", "execution", "Raw script Worker returned another source identity.")
        source = payload["source"]
        if (set(source) != {"status", "exit_code", "stdout", "stderr"}
                or type(source["exit_code"]) is not int or source["status"] not in {"completed", "timeout", "output_limit"}
                or not isinstance(source["stdout"], str) or not isinstance(source["stderr"], str)):
            raise RunError("worker_protocol_error", "execution", "Invalid source exit diagnostics.")
        capture = payload["capture"]
        capture_ref = store.json(path + "capture.json", payload, execution_id + "-capture")
        ledger["capture_attempts"] = ledger.get("capture_attempts", 0) + (capture["optimize_calls"] if capture else 0)
        ledger["hook_optimize_observations"] = ledger.get("hook_optimize_observations", 0) + (capture["optimize_calls"] if capture else 0)
        solve_ref = None
        collector_ref = None
        collector_error: str | None = "capture_missing_or_unsupported"
        if capture and capture["model_count"] == 1 and capture["optimize_calls"] == 1 and capture["transport"] is not None and capture["error"] is None:
            ledger["solver_calls"] += 1
            ledger["collector_calls"] = ledger.get("collector_calls", 0) + 1
            store.checkpoint()
            remaining = plan.deadline - time.time()
            options = dict(self.settings["solver"].get("options", {}))
            options["time_limit_s"] = min(options.get("time_limit_s", remaining), remaining)
            collection = {"schema_version": "0.1.0", "transport": capture["transport"],
                "source_sha256": code.source_sha256, "solver_options": options,
                "allowed_problem_types": plan.snapshot["allowed_problem_types"]}
            try:
                collected = run_container(["python", "-I", "-m", "llm4om.worker", "--collect-native", "/input/capture.json",
                        "--solver", self.settings["solver"]["plugin_id"]],
                    {"capture.json": json.dumps(collection, allow_nan=False).encode()}, limits,
                    image=plan.snapshot["worker"]["image_id"], deadline=plan.deadline, cancellation=store.cancellation)
                if collected.status != "completed" or collected.exit_code != 0:
                    raise RunError("run_cancelled" if collected.status == "cancelled" else "collector_failed", "execution", "Independent collector did not complete.")
                trusted = parse_json(collected.stdout)
                expected = {name: value for name, value in plan.snapshot["worker"].items()
                            if name in ("python", "llm4om", "packages")}
                validate_worker_response(trusted, expected, solver_id=self.settings["solver"]["plugin_id"],
                                         model_backend=self.settings["model_backend"]["plugin_id"])
                collector_ref = store.json(path + "collector.json", trusted, execution_id + "-collector")
                if "error" in trusted:
                    raise RunError(trusted["error"]["code"], "execution", "Independent collector rejected the model.")
                solve = trusted["result"]
                variables = solve.pop("variables")
                solve.update(schema_version="0.2.0", evidence_origin="trusted_container_worker")
                solve["solution_ref"] = store.json(path + "solution.json", {"schema_version": "0.2.0", "variables": variables,
                    "evidence_origin": "trusted_container_worker"}, execution_id + "-solution") if variables is not None else None
                solve_ref = store.json(path + "solve-result.json", solve, execution_id + "-solve")
                collector_error = None
            except RunError as error:
                if error.code == "run_cancelled":
                    raise
                collector_error = error.code
        result = {"schema_version": "0.1.0", "execution_id": execution_id, "identity": identity,
                  "mode": "container", "status": "completed" if source["status"] == "completed" and source["exit_code"] == 0 and collector_error is None else "failed",
                  "solver_call": records[execution_id]["solver_call"], "source_ref": source_ref, "data_ref": data_ref,
                  "worker_ref": worker_ref, "capture_ref": capture_ref, "collector_ref": collector_ref,
                  "source": source, "solve_result_ref": solve_ref, "collector_error": collector_error}
        result_ref = store.json(path + "result.json", result, execution_id)
        records[execution_id]["result_ref"] = result_ref
        store.checkpoint()
        store.emit("method_execution_finished", execution_id=execution_id, result_ref=result_ref)
        return deepcopy(result)

    def _load(self, ref: dict[str, Any]) -> dict[str, Any]:
        if ref not in self.store.refs:
            raise RunError("checkpoint_incompatible", "execution", "Method execution refers to an unverified record.")
        raw = read_public_bytes(public_path(self.store.path, ref["relative_path"]))
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise RunError("checkpoint_incompatible", "execution", "Method execution bytes changed.")
        value = parse_json(raw)
        def verify(value: Any) -> None:
            if isinstance(value, dict):
                if {"relative_path", "namespace", "sha256"} <= value.keys():
                    if value not in self.store.refs or value["namespace"] != "run_public":
                        raise RunError("checkpoint_incompatible", "execution", "Execution contains an unverified reference.")
                    content = read_public_bytes(public_path(self.store.path, value["relative_path"]))
                    if hashlib.sha256(content).hexdigest() != value["sha256"] or len(content) != value["size_bytes"]:
                        raise RunError("checkpoint_incompatible", "execution", "Execution reference bytes changed.")
                    if value["media_type"] == "application/json":
                        verify(parse_json(content))
                else:
                    for item in value.values():
                        verify(item)
            elif isinstance(value, list):
                for item in value:
                    verify(item)
        verify(value)
        return value
