"""Project-authored bounded repair using public checks only."""

from copy import deepcopy
from dataclasses import replace
import json
from typing import Any
from uuid import uuid4

from llm4om.contracts import RunError
from llm4om.methods import DirectFactory, DirectMethod, GenerationFailure, MethodContext, MethodOutcome, ModelProposal


class FeedbackRepairMethod:
    def __init__(self, output_mode: str) -> None:
        self.output_mode = output_mode

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if context.resources is None:
            raise RunError("capability_mismatch", "admission", "Public check resources are required.")
        state = deepcopy(checkpoint) if checkpoint is not None else {
            "schema_version": "0.2.0", "request_id": uuid4().hex, "request_pending": False, "attempts": [], "feedback": None,
            "clarification": None, "clarification_count": 0}
        if (set(state) != {"schema_version", "request_id", "request_pending", "attempts", "feedback", "clarification", "clarification_count"}
                or state["schema_version"] != "0.2.0" or not isinstance(state["request_id"], str)
                or not isinstance(state["attempts"], list) or type(state["request_pending"]) is not bool
                or type(state["clarification_count"]) is not int or state["clarification_count"] < 0
                or state["clarification"] is not None and not isinstance(state["clarification"], dict)):
            raise RunError("checkpoint_incompatible", "formulation", "Invalid public repair checkpoint.")
        if state["clarification"] is not None:
            if len(context.clarifications) <= state["clarification_count"]:
                return MethodOutcome("needs_input", None, None, state["clarification"])
            state.update(clarification=None, clarification_count=len(context.clarifications), request_id=uuid4().hex,
                         request_pending=False)
        while (len(state["attempts"]) < min(context.budget["max_checks"], context.budget["max_repairs"] + 1)
                and not any(not a["diagnostics"] and a["has_primal_solution"] for a in state["attempts"])):
            context.cancellation.check()
            remaining = context.resources.remaining_budget()
            if not state["request_pending"] and (any(remaining[name] <= 0 for name in (
                    "checks", "solver_calls", "llm_attempts", "total_tokens", "wall_time_s"))
                    or state["attempts"] and remaining["repairs"] <= 0):
                break
            state["request_pending"] = True
            if context.save_checkpoint is not None:
                context.save_checkpoint(state)
            proposal: ModelProposal | GenerationFailure
            try:
                outcome = await DirectMethod(self.output_mode).run(problem, replace(context, save_checkpoint=None),
                    checkpoint={"schema_version": "0.1.0", "request_id": state["request_id"]},
                    feedback=state["feedback"], role="repair" if state["feedback"] is not None else "formulation", allow_clarification=True)
                if outcome.status == "needs_input":
                    state.update(clarification=outcome.clarification, clarification_count=len(context.clarifications), request_pending=False)
                    if context.save_checkpoint is not None:
                        context.save_checkpoint(state)
                    return outcome
                if outcome.proposal is None:
                    raise RunError("invalid_method_outcome", "formulation", "Generation did not produce a proposal.")
                proposal = outcome.proposal
            except RunError as error:
                if error.code not in ("invalid_json", "invalid_object", "invalid_method_outcome", "llm_output_truncated") or not error.details:
                    raise
                proposal = GenerationFailure(error.details["call_id"], error.details["response_sha256"], error.code,
                    "code" if error.stage == "code" else "formulation", str(error))
            check_id = f"{len(state['attempts']) + 1:03d}"
            parent_id = state["attempts"][-1]["check_id"] if state["attempts"] else None
            reason = (proposal.artifact["provenance"].get("repair", {}).get("reason") if isinstance(proposal, ModelProposal)
                      else "Regeneration still failed decoding; retain its public diagnostic and actual call identity.")
            if parent_id is None:
                reason = None
            checked = await context.resources.check(check_id, proposal, parent_id=parent_id, change_reason=reason)
            state["attempts"].append(checked)
            state["feedback"] = {"checked": checked, "previous_output": {
                "representation": proposal.formulation["representation"] if proposal.formulation else None,
                "source_formulation": proposal.formulation,
                "structured_ir": proposal.structured_ir,
                "code": proposal.code.source if proposal.code is not None else None} if isinstance(proposal, ModelProposal) else None}
            state["request_id"] = uuid4().hex
            state["request_pending"] = False
            if context.save_checkpoint is not None:
                context.save_checkpoint(state)
            if not checked["diagnostics"] and checked["has_primal_solution"]:
                break
        legal = [a for a in state["attempts"] if not a["diagnostics"] and a["solve_result_ref"] is not None]
        context.resources.record("repair-state.json", json.dumps({**state,
            "selection_rule": "legal-primal-completeness-latest/0.1.0"}, allow_nan=False).encode())
        if not legal:
            return MethodOutcome("exhausted", None, None)
        selected = max(enumerate(legal), key=lambda item: (item[1]["has_primal_solution"],
            sum(s["status"] == "available" for s in item[1]["stages"].values()), item[0]))[1]
        completed = sum(s["status"] == "available" for s in selected["stages"].values())
        return context.resources.select(selected["check_id"], rule="legal-primal-completeness-latest/0.1.0",
            reason=f"Selected {selected['check_id']}: trusted_primal={selected['has_primal_solution']}, completed_stages={completed}; prefer legal primals, then completeness and latest attempt. No reference or cross-model objective comparison.")


class FeedbackRepairFactory:
    def describe(self) -> dict[str, Any]:
        manifest = DirectFactory().describe()
        manifest.update(plugin_id="llm4om.methods.feedback_repair", display_name="Public Feedback Repair",
            description="Bounded project-authored repair from public stage diagnostics and trusted Solver evidence.",
            source={"kind": "engineering_baseline", "variant_id": "public_feedback_repair/0.1.0"})
        manifest["capabilities"]["method_profile"] = "grounded_checked/0.2.0"
        manifest["capabilities"]["supports_clarification"] = True
        return manifest

    def resolve_capabilities(self, config: dict[str, Any]) -> dict[str, Any]:
        capabilities = DirectFactory().resolve_capabilities(config)
        capabilities["supports_clarification"] = True
        capabilities["method_profile"] = {"lp_ir": "grounded_checked/0.2.0",
            "python_factory": "factory_checked/0.2.0", "native_gurobipy": "native_checked/0.2.0"}[config["output_mode"]]
        return capabilities

    def create(self, config: dict[str, Any]) -> FeedbackRepairMethod:
        return FeedbackRepairMethod(config["output_mode"])
