"""Shared public calls, target code and public check feedback for prompt methods."""

import hashlib
import json
import re
import time
from typing import Any

from llm4om.contracts import RunError, parse_json
from llm4om.methods import FactoryCodeProposal, MethodContext, MethodOutcome, ModelProposal, code_instructions


def json_reply(text: str) -> Any:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character in "[{":
            try:
                value, end = decoder.raw_decode(text[index:])
                if isinstance(value, dict):
                    return parse_json(text[index:index + end].encode())
            except (ValueError, TypeError):
                continue
    raise RunError("invalid_method_reply", "formulation", "The method expected a JSON object.")


def python_reply(text: str) -> str:
    blocks = re.findall(r"```(?:python|Python)?\s*\n(.*?)```", text, re.S)
    source = blocks[0] if len(blocks) == 1 else text
    return source


class PromptSession:
    def __init__(self, method: str, source: dict[str, Any], problem: dict[str, Any], context: MethodContext) -> None:
        if context.resources is None:
            raise RunError("resource_unavailable", "admission", "The method requires public artifact and execution resources.")
        self.method, self.source, self.problem, self.context = method, source, problem, context
        self.resources = context.resources
        self.calls: list[dict[str, Any]] = []
        self.bindings = [{"data_id": ref["data_id"], "sha256": ref["sha256"]} for ref in problem["data_refs"]]
        self.inputs = {"problem": problem, "public_data": {key: value.decode("utf-8") for key, value in context.data.items()},
            "clarifications": list(context.clarifications)}
        self.record("fidelity-report.json", {**source, "prompts": "independently_authored",
            "model": "configured_external_gateway", "execution": "configured_backend_solver_in_isolated_worker",
            "code_target": dict(context.code_target) if context.code_target else None,
            "paper_benchmark_reproduction": False})

    def record(self, name: str, value: Any) -> None:
        self.resources.record(name, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

    async def complete(self, role: str, instruction: str, inputs: Any, *, phase: str = "formulation") -> str:
        self.context.cancellation.check()
        if self.context.deadline is not None:
            if time.time() >= self.context.deadline:
                raise RunError("deadline_exhausted", phase, "The shared run deadline expired.")
        request_id = f"{self.method}-{len(self.calls) + 1:04d}"
        progress = {"type": "modeling_step", "schema_version": "0.1.0", "step_id": request_id,
            "phase": phase, "label": role, "actor": self.method + "." + role}
        self.resources.emit({**progress, "status": "running"})
        try:
            reply = await self.context.llm.complete({"request_id": request_id, "role": self.method + "." + role,
                "messages": [{"role": "system", "content": instruction},
                    {"role": "user", "content": json.dumps(inputs, ensure_ascii=False, allow_nan=False)}]})
            if reply.finish_reason == "length":
                raise RunError("llm_output_truncated", phase, "The method response reached its output limit.")
        except BaseException:
            self.resources.emit({**progress, "status": "failed"})
            raise
        self.resources.emit({**progress, "status": "completed"})
        self.calls.append({"role": role, "call_id": reply.call_id, "response_sha256": reply.source_sha256,
            "evidence_origin": reply.evidence_origin, "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest()})
        self.resources.record(request_id + "-reply.txt", reply.text.encode())
        self.record("calls.json", {"calls": self.calls})
        return reply.text

    @property
    def code_instruction(self) -> str:
        return code_instructions(self.context) + " Return only the Python source in one code block."

    def proposal(self, state: dict[str, Any], source: str, *, code_repair: bool = False) -> ModelProposal:
        target = self.context.code_target
        if target is None:
            raise RunError("capability_mismatch", "code", "A code generation target is required.")
        source = python_reply(source)
        code = FactoryCodeProposal(source, hashlib.sha256(source.encode()).hexdigest(), self.bindings,
            representation_kind=target["representation_kind"])
        provenance = {**self.source, "origin": "source_derived_workflow", "call_ids": [call["call_id"] for call in self.calls]}
        formulation = {"schema_version": "0.3.0", "formulation_id": self.method + "-formulation",
            "problem_id": self.problem["problem_id"], "problem_revision": self.problem["revision"],
            "representation_kind": "native_formulation", "representation": {"schema": self.method + "/0.1.0", "state": state},
            "structured_ir_ref": None, "data_bindings": self.bindings, "provenance": provenance}
        artifact = {"schema_version": "0.2.0", "artifact_id": self.method + "-artifact",
            "problem_ref": {"sha256": self.context.problem_sha256}, "formulation_ref": {}, "code_ref": None,
            "data_bindings": self.bindings, "assumptions": [], "requirement_traces": [], "diagnostics": [],
            "warnings": [], "optional_views": [], "provenance": {**provenance,
                **({"repair": {"stage": "code", "reason": "Repair from public execution feedback."}} if code_repair else {})},
            "stage_status": {"formulation": {"status": "available", "reason": None},
                "code": {"status": "pending", "reason": "Factory must pass isolated model construction and solving."}}}
        return ModelProposal(artifact, formulation, code=code)

    async def debug_factory(self, source: str, state: dict[str, Any], inputs: dict[str, Any], limit: int) -> MethodOutcome:
        parent = None
        for attempt in range(limit + 1):
            check_id = f"{attempt + 1:03d}"
            checked = await self.resources.check(check_id, self.proposal(state, source, code_repair=parent is not None),
                parent_id=parent, change_reason="Repair from public execution feedback." if parent else None)
            if not checked["diagnostics"] and checked["solve_result_ref"] is not None:
                self.record("selection.json", {"check_id": check_id, "debug_attempts": attempt})
                return self.resources.select(check_id, rule="first_executable_model",
                    reason="The configured Solver returned a trusted result without execution diagnostics.")
            if attempt == limit:
                raise RunError("method_debug_exhausted", "code", "The method exhausted its bounded debugging attempts.")
            remaining = self.resources.remaining_budget()
            if not remaining["checks"] or not remaining["solver_calls"]:
                raise RunError("budget_exhausted", "code", "No public check or Solver slot remains for code repair.")
            self.record(f"debug-{attempt + 1:03d}.json", checked)
            source = await self.complete("debug", self.code_instruction + " Repair the previous code using public execution "
                "feedback. Preserve the mathematical formulation and all business requirements. An infeasible or unbounded "
                "model is not a code error; never relax requirements to manufacture a solution.",
                {**inputs, "formulation": state, "previous_code": source, "feedback": checked}, phase="code")
            parent = check_id
        raise AssertionError("Bounded debug loop must return or raise.")
