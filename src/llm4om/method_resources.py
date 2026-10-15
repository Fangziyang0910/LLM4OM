"""Run-owned public script execution, evidence, budgets and replay identity."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from llm4om.contracts import RunError, parse_json, public_path, read_public_bytes
from llm4om.methods import GenerationFailure, LLMResponse, MethodOutcome, ModelProposal, ScriptCodeProposal
from llm4om.preflight import AdmissionPlan
from llm4om.storage import RunStore
from llm4om.checks import persist_proposal, compile_model, execute_model
from llm4om.run_records import load_run_record
from llm4om.script_execution import ScriptExecutions


class RunMethodResources:
    def __init__(self, store: RunStore, public: dict[str, Any], settings: dict[str, Any], plan: AdmissionPlan,
                 *, responses: list[LLMResponse] | None = None) -> None:
        self.store, self.public, self.settings, self.plan = store, public, settings, plan
        self.responses = responses if responses is not None else []
        self.scripts = ScriptExecutions(store, public, settings, plan)

    def remaining_budget(self) -> dict[str, Any]:
        ledger, budget = self.store.state["ledger"], self.settings["budget"]
        result = {name: max(0, budget[limit] - ledger.get(name, 0)) for name, limit in (
            ("checks", "max_checks"), ("repairs", "max_repairs"),
            ("solver_calls", "max_solver_calls"), ("llm_attempts", "max_llm_attempts"))}
        result["total_tokens"] = max(0, budget["max_total_tokens"] - ledger.get("known_total_tokens", ledger.get("total_tokens") or 0)
                                     - ledger.get("reserved_tokens", 0))
        return {**result, "wall_time_s": max(0, self.plan.deadline - time.time())}

    async def check(self, check_id: str, proposal: ModelProposal | GenerationFailure, *, parent_id: str | None = None,
                     change_reason: str | None = None) -> dict[str, Any]:
        store = self.store
        store.cancellation.check()
        if (not isinstance(check_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", check_id)
                or not isinstance(proposal, (ModelProposal, GenerationFailure))):
            raise RunError("invalid_proposal", "formulation", "A public check needs a bounded ID and a ModelProposal.")
        if store.state["offline"]:
            raise RunError("capability_mismatch", "admission", "Public checks require an online Solver execution plan.")
        if self.plan.snapshot["method_profile"] not in ("grounded_checked/0.2.0", "factory_checked/0.2.0", "native_checked/0.2.0"):
            raise RunError("capability_mismatch", "admission", "Public checks require the admitted grounded_checked profile.")
        if parent_id is not None and (not isinstance(parent_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", parent_id)):
            raise RunError("invalid_proposal", "formulation", "A repair parent needs a bounded check ID.")
        if parent_id is not None and (not isinstance(change_reason, str) or not change_reason.strip() or len(change_reason) > 4096):
            raise RunError("invalid_proposal", "formulation", "A repair needs a public change reason.")
        if isinstance(proposal, GenerationFailure) and (
                proposal.code not in ("invalid_json", "invalid_object", "invalid_method_outcome", "llm_output_truncated")
                or proposal.stage not in ("formulation", "code")
                or not isinstance(proposal.message, str) or not proposal.message or len(proposal.message) > 4096
                or not any(response.call_id == proposal.call_id and response.source_sha256 == proposal.response_sha256
                           for response in self.responses)):
            raise RunError("invalid_generation_failure", "formulation", "Decoder feedback must name an actual response and a supported public failure.")
        def encode(value: Any) -> dict[str, str]:
            if not isinstance(value, bytes):
                raise TypeError("Unsupported proposal value.")
            return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
        try:
            raw = json.dumps({"proposal": asdict(proposal), "parent_id": parent_id, "change_reason": change_reason},
                             sort_keys=True, allow_nan=False, default=encode).encode()
        except (TypeError, ValueError) as failure:
            raise RunError("invalid_proposal", "formulation", "Proposal metadata must contain finite JSON values.") from failure
        if len(raw) > 8 * 1024 * 1024:
            raise RunError("invalid_proposal", "formulation", "Proposal metadata exceeds its byte limit.")
        parse_json(raw)
        identity = hashlib.sha256(raw).hexdigest()
        records = store.state.setdefault("checks", {})
        prior = records.get(check_id)
        if prior is not None:
            if prior["identity"] != identity:
                raise RunError("checkpoint_incompatible", "formulation", "Check ID was rebound to another proposal or parent.")
            if prior.get("result_ref") is not None:
                return deepcopy(load_run_record(self.store, prior["result_ref"]))
            raise RunError("execution_outcome_unknown", "execution", "An admitted public check has no receipt; it will not be repeated.")
        if parent_id is not None and (parent_id not in records or records[parent_id].get("result_ref") is None):
            raise RunError("invalid_proposal", "formulation", "A repair parent must be a checked proposal in this run.")
        ledger = store.state["ledger"]
        if time.time() >= self.plan.deadline:
            raise RunError("deadline_exhausted", "formulation", "No shared run deadline remains.")
        if ledger["checks"] >= self.settings["budget"]["max_checks"]:
            raise RunError("budget_exhausted", "formulation", "No shared public check slot remains.")
        if parent_id is not None and ledger.get("repairs", 0) >= self.settings["budget"]["max_repairs"]:
            raise RunError("budget_exhausted", "formulation", "No shared repair slot remains.")
        ledger["checks"] += 1
        ledger["repairs"] = ledger.get("repairs", 0) + int(parent_id is not None)
        records[check_id] = {"identity": identity, "result_ref": None}
        store.state.update(check_id=check_id, check_parent_ids=[parent_id] if parent_id else [],
                           check_change_reason=change_reason, check_pending=True,
                           artifact_ref=None, solve_ref=None, execution_ref=None, executed_artifact_ref=None,
                           phase="check_pending")
        store.checkpoint()
        path = "checks/" + check_id + "/"
        proposal_ref = store.write(path + "supplied-proposal.txt", raw, check_id + "-supplied-proposal")
        error = None
        artifact_ref = solve_ref = execution_ref = changes_ref = None
        stages: dict[str, Any] = {name: {"status": "not_available", "reason": "Stage has not run."}
                  for name in ("formulation", "code", "solve")}
        try:
            if isinstance(proposal, GenerationFailure):
                raise RunError(proposal.code, proposal.stage, proposal.message)
            public_ref = store.projections["public-problem.json"]
            replay = {"mode": self.responses[-1].evidence_origin if self.responses else "no_calls",
                      "call_ids": [response.call_id for response in self.responses],
                      "response_sha256": self.responses[-1].source_sha256 if self.responses else None}
            artifact_ref, stages = persist_proposal(store, proposal, self.public, public_ref,
                hashlib.sha256(read_public_bytes(Path(store.state["problem"]))).hexdigest(),
                self.settings, False, self.plan, replay)
            if parent_id is not None:
                parent = load_run_record(self.store, records[parent_id]["result_ref"])
                changes = self._formulation_changes(parent_id, parent, proposal)
                changes_ref = store.json(path + "formulation-changes.json", changes, check_id + "-changes")
                if changes["requirements_lost"]:
                    raise RunError("requirement_coverage_lost", "formulation", "Repair lost an existing public requirement trace; it cannot win by deleting that coverage.")
            artifact_ref, compiled = compile_model(store, artifact_ref, self.settings)
            stages["code"] = {"status": "available", "reason": None}
            store.state.update(artifact_ref=artifact_ref, phase="code_done")
            solve_ref, execution_ref, error = execute_model(store, compiled, artifact_ref, self.settings, ledger, self.plan)
            artifact_ref = store.state.get("executed_artifact_ref", artifact_ref)
            if solve_ref is not None:
                stages["solve"] = {"status": "available", "reason": None}
        except (RunError, ValueError, KeyError, TypeError) as failure:
            if not isinstance(failure, RunError):
                failure = RunError("invalid_method_outcome", "formulation", "Proposal output does not match the declared model contract.")
            if failure.code == "run_cancelled":
                raise
            error = failure
        if parent_id is not None and isinstance(proposal, ModelProposal) and changes_ref is None:
            parent = load_run_record(self.store, records[parent_id]["result_ref"])
            changes_ref = store.json(path + "formulation-changes.json",
                self._formulation_changes(parent_id, parent, proposal), check_id + "-changes")
        solve = load_run_record(self.store, solve_ref) if solve_ref is not None else None
        result = {"schema_version": "0.1.0", "check_id": check_id, "proposal_sha256": identity,
                  "proposal_ref": proposal_ref,
                  "formulation_changes_ref": changes_ref,
                  "status": "invalid" if error is not None and execution_ref is None else "executed",
                  "stages": stages, "artifact_ref": artifact_ref, "execution_result_ref": execution_ref,
                  "solve_result_ref": solve_ref, "has_primal_solution": solve["has_primal_solution"] if solve else False,
                  "termination": solve["termination"] if solve else None,
                  "diagnostics": [{"code": error.code, "stage": error.stage, "message": str(error),
                      "origin": "method_decoder" if isinstance(proposal, GenerationFailure) else "engine"}] if error else []}
        record_ref = store.projections.get(path + "record-snapshot.json")
        record = load_run_record(self.store, record_ref) if record_ref else {
            "schema_version": "0.2.0", "check_id": check_id, "run_id": store.run_id,
            "sequence_no": ledger["checks"], "parent_ids": [parent_id] if parent_id else [],
            "change_reason": change_reason, "artifact_ref": artifact_ref,
            "created_by": {"method_id": self.plan.method.manifest["plugin_id"],
                "method_version": self.plan.method.manifest["plugin_version"],
                "variant_id": (self.plan.method.manifest["source"] or {}).get("variant_id", "grounded_checked"),
                "call_ids": [response.call_id for response in self.responses], "prompt_hash": None, "role": "formulation"}}
        record.update(status=result["status"], artifact_ref=artifact_ref)
        store.json(path + "record.json", record, check_id)
        records[check_id]["result_ref"] = store.json(path + "check.json", result, check_id + "-check")
        store.state.update(phase="method_pending", stages=stages)
        store.checkpoint()
        store.emit("check_finished", check_id=check_id, check_ref=records[check_id]["result_ref"])
        return deepcopy(result)

    def _formulation_changes(self, parent_id: str, parent: dict[str, Any], proposal: ModelProposal) -> dict[str, Any]:
        raw = read_public_bytes(public_path(self.store.path, parent["proposal_ref"]["relative_path"]))
        previous = parse_json(raw)["proposal"]
        old_formulation = previous.get("formulation") if isinstance(previous.get("formulation"), dict) else {}
        new_formulation = proposal.formulation if isinstance(proposal.formulation, dict) else {}
        before, after = old_formulation.get("representation", {}), new_formulation.get("representation", {})
        before = before if isinstance(before, dict) else {}
        after = after if isinstance(after, dict) else {}
        old_ir = previous.get("structured_ir") if isinstance(previous.get("structured_ir"), dict) else {}
        new_ir = proposal.structured_ir if isinstance(proposal.structured_ir, dict) else {}
        def requirements(value: Any) -> set[str]:
            result: set[str] = set()
            if isinstance(value, dict):
                refs = value.get("requirement_ids", [])
                if isinstance(refs, list):
                    result.update(ref for ref in refs if isinstance(ref, str))
                for item in value.values():
                    result.update(requirements(item))
            elif isinstance(value, list):
                for item in value:
                    result.update(requirements(item))
            return result
        def ids(value: Any) -> set[str]:
            return {item["id"] for item in value if isinstance(item, dict) and isinstance(item.get("id"), str)} if isinstance(value, list) else set()
        lost = ((requirements(before) - requirements(after)) | (requirements(old_ir) - requirements(new_ir)))
        public_ids = {r["id"] for r in self.public["requirements"]}
        return {"schema_version": "0.1.0", "origin": "declared_output_comparison",
                "parent_check_id": parent_id, "parent_proposal_ref": parent["proposal_ref"],
                "changed_sections": [key for key in ("sets", "parameters", "variables", "objective", "constraints")
                                     if before.get(key) != after.get(key)],
                "ir_changed_sections": [key for key in ("problem_type", "variables", "objective", "constraints", "assumptions")
                                        if old_ir.get(key) != new_ir.get(key)],
                "requirements_lost": sorted(lost & public_ids),
                "constraint_ids_removed": sorted(ids(before.get("constraints")) - ids(after.get("constraints"))),
                "constraint_ids_added": sorted(ids(after.get("constraints")) - ids(before.get("constraints"))),
                "source_formulation_available": bool(old_formulation),
                "semantic_validation": "not_proven_by_declaration_comparison"}

    def select(self, check_id: str, *, rule: str, reason: str) -> MethodOutcome:
        store = self.store
        store.cancellation.check()
        if not all(isinstance(value, str) and value.strip() and len(value) <= 4096 for value in (rule, reason)):
            raise RunError("invalid_selection", "formulation", "Selection needs a declared rule and a public reason.")
        if not isinstance(check_id, str):
            raise RunError("invalid_selection", "formulation", "The selection needs a check ID.")
        record = store.state.get("checks", {}).get(check_id)
        if record is None or record.get("result_ref") is None:
            raise RunError("invalid_selection", "formulation", "The selected proposal must be checked in this run.")
        result = load_run_record(self.store, record["result_ref"])
        if result["diagnostics"] or result["artifact_ref"] is None or result["solve_result_ref"] is None:
            raise RunError("invalid_selection", "formulation", "Selection requires a valid check with trusted completed Solver evidence.")
        selection = {"schema_version": "0.1.0", "check_id": check_id,
                     "rule": rule, "reason": reason, "check_ref": record["result_ref"]}
        previous = store.projections.get("selection.json")
        if previous is not None and load_run_record(self.store, previous) != selection:
            raise RunError("invalid_selection", "formulation", "A saved final selection is immutable.")
        store.json("selection.json", selection, "selection")
        if previous is None:
            store.emit("selection_saved", check_id=check_id, rule=rule, reason=reason)
        record = load_run_record(self.store, store.projections["checks/" + check_id + "/record.json"])
        record["status"] = "selected"
        store.json("checks/" + check_id + "/record.json", record, check_id)
        store.state.update(check_id=check_id, artifact_ref=result["artifact_ref"], stages=result["stages"],
                           solve_ref=result["solve_result_ref"], execution_ref=result["execution_result_ref"],
                           check_pending=False, phase="execute_done")
        store.checkpoint()
        return MethodOutcome("selected", check_id, None)

    def selected(self, check_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        store = self.store
        if (check_id is None or check_id != store.state.get("check_id")
                or store.state.get("check_pending") or "selection.json" not in store.projections):
            raise RunError("invalid_method_outcome", "formulation", "A reference-only outcome requires a saved selection.")
        selection = load_run_record(self.store, store.projections["selection.json"])
        if selection["check_id"] != check_id:
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
        if value.get("type") == "modeling_step":
            if (value.get("schema_version") != "0.1.0" or value.get("phase") not in {"formulation", "code", "solve", "coordination"}
                    or value.get("status") not in {"running", "completed", "failed"}
                    or any(not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 512
                           for key in ("step_id", "label", "actor"))):
                raise RunError("invalid_method_event", "validation", "Modeling progress needs a declared phase, step identity and lifecycle.")
            value["timestamp"] = time.time()
        self.store.emit("method_event", method_event=value)

    async def execute(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]:
        # The event-loop thread owns checkpoints and ledger updates throughout execution.
        return await self.scripts.execute(execution_id, code)

    def reuse(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]:
        return self.scripts.reuse(execution_id, code)

    def reconcile(self) -> None:
        """Accept complete execution receipts before the application clears them."""
        for check_id, record in self.store.state.get("checks", {}).items():
            receipts = self.store.interrupted_publications.get("checks/" + check_id + "/check.json", [])
            if record.get("result_ref") is not None or not receipts:
                continue
            result = load_run_record(self.store, receipts[-1])
            if result["check_id"] != check_id or result["proposal_sha256"] != record["identity"]:
                raise RunError("checkpoint_incompatible", "execution", "Public check receipt identity differs.")
            self.store.accept_publications()
            record["result_ref"] = receipts[-1]
            self.store.state["phase"] = "method_pending"
            self.store.checkpoint()
        for execution_id, record in self.store.state.get("method_executions", {}).items():
            receipts = self.store.interrupted_publications.get("method/executions/" + execution_id + "/result.json", [])
            if record.get("result_ref") is not None or not receipts:
                continue
            result = load_run_record(self.store, receipts[-1])
            source = read_public_bytes(public_path(self.store.path, result["source_ref"]["relative_path"]))
            data = read_public_bytes(public_path(self.store.path, result["data_ref"]["relative_path"]))
            self.reuse(execution_id, ScriptCodeProposal(source.decode(), record["identity"]["source_sha256"],
                       record["identity"]["data_bindings"], data))
        selections = self.store.interrupted_publications.get("selection.json", [])
        if selections:
            selection = load_run_record(self.store, selections[-1])
            record = self.store.state.get("checks", {}).get(selection["check_id"])
            if record is None or selection["check_ref"] != record.get("result_ref"):
                raise RunError("checkpoint_incompatible", "execution", "Selection receipt differs from the checked proposal.")
            self.store.accept_publications()
            self.select(selection["check_id"], rule=selection["rule"], reason=selection["reason"])
