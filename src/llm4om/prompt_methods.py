"""Shared public calls, progress and native output for prompt-based methods."""

import hashlib
import json
import re
from typing import Any

from llm4om.contracts import RunError, parse_json
from llm4om.methods import MethodContext, MethodOutcome, ModelProposal, ScriptCodeProposal


def json_reply(text: str) -> Any:
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character in "[{":
            try:
                value, _ = decoder.raw_decode(text[index:])
                if isinstance(value, dict):
                    return parse_json(json.dumps(value, allow_nan=False).encode())
            except (ValueError, TypeError):
                continue
    raise RunError("invalid_method_reply", "formulation", "The method expected a JSON object.")


def python_reply(text: str) -> str:
    blocks = re.findall(r"```(?:python|Python)?\s*\n(.*?)```", text, re.S)
    source = blocks[0] if len(blocks) == 1 else text
    try:
        compile(source, "<generated-code>", "exec")
    except (SyntaxError, ValueError) as error:
        raise RunError("invalid_method_reply", "code", "The method expected one complete Python script.") from error
    return source


class PromptSession:
    def __init__(self, method: str, source: dict[str, Any], problem: dict[str, Any], context: MethodContext) -> None:
        if context.resources is None:
            raise RunError("resource_unavailable", "admission", "The method requires public artifact and execution resources.")
        self.method, self.source, self.problem, self.context = method, source, problem, context
        self.resources = context.resources
        self.calls: list[dict[str, Any]] = []
        self.bindings = [{"data_id": ref["data_id"], "sha256": ref["sha256"]} for ref in problem["data_refs"]]
        self.inputs = {"problem": problem, "public_data": {key: value.decode("utf-8") for key, value in context.data.items()}}
        self.record("fidelity-report.json", {**source, "prompts": "independently_authored",
            "model": "configured_external_gateway", "execution": "isolated_worker_and_independent_collector",
            "paper_benchmark_reproduction": False})

    def record(self, name: str, value: Any) -> None:
        self.resources.record(name, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

    async def complete(self, role: str, instruction: str, inputs: Any, *, phase: str = "formulation") -> str:
        self.context.cancellation.check()
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

    async def execute(self, source: str, attempt: int) -> tuple[ScriptCodeProposal, str, dict[str, Any]]:
        code = ScriptCodeProposal(source, hashlib.sha256(source.encode()).hexdigest(), self.bindings,
            json.dumps({"public_data": self.inputs["public_data"]}, ensure_ascii=False).encode())
        execution_id = f"{self.method}-{attempt:03d}"
        return code, execution_id, await self.resources.execute(execution_id, code)

    async def debug_script(self, source: str, inputs: dict[str, Any], limit: int) -> tuple[ScriptCodeProposal, str]:
        for attempt in range(limit + 1):
            try:
                script = python_reply(source)
            except RunError as error:
                feedback: dict[str, Any] = {"parse_error": str(error)}
            else:
                code, execution_id, result = await self.execute(script, attempt + 1)
                feedback = {"source": result["source"], "collector_error": result.get("collector_error")}
                if result["source"]["exit_code"] == 0 and result.get("collector_error") is None:
                    self.record("selection.json", {"execution_id": execution_id, "debug_attempts": attempt})
                    return code, execution_id
            if attempt == limit:
                raise RunError("method_debug_exhausted", "code", "The method exhausted its bounded debugging attempts.")
            self.record(f"debug-{attempt + 1:03d}.json", feedback)
            source = await self.complete("debug", NATIVE_CODE_INSTRUCTION + " Repair the previous code using only public "
                "execution feedback. Preserve the mathematical model unless the description requires a correction.",
                {**inputs, "previous_code": source, "feedback": feedback}, phase="code")
        raise AssertionError("Bounded debug loop must return or raise.")

    def outcome(self, state: dict[str, Any], code: ScriptCodeProposal, execution_id: str) -> MethodOutcome:
        provenance = {**self.source, "origin": "source_derived_workflow", "call_ids": [call["call_id"] for call in self.calls]}
        formulation = {"schema_version": "0.3.0", "formulation_id": self.method + "-formulation",
            "problem_id": self.problem["problem_id"], "problem_revision": self.problem["revision"],
            "representation_kind": "native_formulation", "representation": {"schema": self.method + "/0.1.0", "state": state},
            "structured_ir_ref": None, "data_bindings": self.bindings, "provenance": provenance}
        artifact = {"schema_version": "0.2.0", "artifact_id": self.method + "-artifact",
            "problem_ref": {"sha256": self.context.problem_sha256}, "formulation_ref": {}, "code_ref": None,
            "data_bindings": self.bindings, "assumptions": [], "requirement_traces": [], "diagnostics": [],
            "warnings": [], "optional_views": [], "provenance": provenance,
            "stage_status": {"formulation": {"status": "available", "reason": None},
                "code": {"status": "pending", "reason": "Native script must pass trusted collection."}}}
        return MethodOutcome("candidate_selected", "001", ModelProposal(artifact, formulation, code=code, execution_id=execution_id))


NATIVE_CODE_INSTRUCTION = (
    "Write one complete executable Python gurobipy LP/MILP script for the public problem and formulation. "
    "Use the original problem's numbers and data, never the template's example values. "
    "Build exactly one model and call optimize exactly once. Name all decision variables. "
    "Use only gurobipy, json, math and Python standard library. Public uploaded data is available "
    "in data.json under public_data as data_id -> original CSV/JSON text. "
    "Return only the Python code in one code block."
)
