"""Load the explicit, input-bound Mock method response without execution."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import jsonschema

from llm4om.contracts import (
    RunError, parse_json, read_artifact, read_public_bytes, reject_additional_refs,
    validate_bindings, validate_formulation, validate_model_artifact,
)
from llm4om.methods import LLMResponse
from llm4om.storage import RunStore


@dataclass(frozen=True)
class MockOutput:
    artifact: dict[str, Any]
    formulation: dict[str, Any]
    structured_ir: dict[str, Any]
    source_sha256: str


def load_mock_output(response: Path, public: dict[str, Any], problem_sha256: str) -> MockOutput:
    raw = read_public_bytes(response)
    artifact = parse_json(raw)
    validate_model_artifact(artifact)
    validate_bindings(artifact, public)
    if problem_sha256 != artifact["problem_ref"].get("sha256"):
        raise RunError("artifact_problem_mismatch", "formulation", "Mock packet was authored for a different public input.")
    read_artifact(response.parent, artifact["problem_ref"], "0.2.0", "problem_id")
    formulation = read_artifact(response.parent, artifact["formulation_ref"], "0.2.0", "formulation_id")
    validate_formulation(formulation, public)
    ir = read_artifact(response.parent, formulation["structured_ir_ref"], "0.1.0", "model_id")
    reject_additional_refs(ir)
    if ir.get("problem_id") != public["problem_id"] or ir.get("problem_revision") != public["revision"]:
        raise RunError("artifact_problem_mismatch", "formulation", "Strict IR belongs to a different problem or revision.")
    validate_bindings(ir, public)
    return MockOutput(artifact, formulation, ir, hashlib.sha256(raw).hexdigest())


class MockGateway:
    def __init__(self, response: Path, public: dict[str, Any], problem_sha256: str,
                 store: RunStore, ledger: dict[str, Any], max_attempts: int) -> None:
        self.response, self.public, self.problem_sha256 = response, deepcopy(public), problem_sha256
        self.store, self.ledger, self.max_attempts = store, ledger, max_attempts
        self.calls: list[LLMResponse] = []

    async def complete(self, request: dict[str, Any]) -> LLMResponse:
        request = parse_json(json.dumps(request, allow_nan=False).encode())
        if set(request) - {"messages", "request_id", "role"}:
            raise RunError("capability_mismatch", "admission", "Mock supports text messages only.")
        try:
            jsonschema.Draft202012Validator({"type": "object", "properties": {
                "request_id": {"type": "string", "minLength": 1},
                "role": {"type": "string", "minLength": 1},
                "messages": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
                    "role": {"enum": ["system", "user", "assistant"]}, "content": {"type": "string"}},
                    "required": ["role", "content"], "additionalProperties": False}}},
                "required": ["messages"], "additionalProperties": False}).validate(request)
        except jsonschema.ValidationError as error:
            raise RunError("invalid_llm_request", "admission", "Mock requests need role/text messages.") from error
        self.store.cancellation.check()
        request_id = request.get("request_id")
        cached = self.store.state.setdefault("mock_responses", {})
        if request_id in cached:
            saved = cached[request_id]
            response = LLMResponse(saved["text"], saved["call_id"], "mock_fixture", saved["source_sha256"])
            self.calls.append(response)
            return response
        if self.ledger["llm_attempts"] >= self.max_attempts:
            raise RunError("budget_exhausted", "admission", "No Mock attempt remains.")
        self.ledger["llm_attempts"] += 1
        call_id = f"mock-{self.ledger['llm_attempts']}"
        self.store.emit("mock_call_started", call_id=call_id)
        output = load_mock_output(self.response, self.public, self.problem_sha256)
        text = json.dumps({"artifact": output.artifact, "formulation": output.formulation,
                           "structured_ir": output.structured_ir}, ensure_ascii=False, allow_nan=False)
        response = LLMResponse(text, call_id, "mock_fixture", output.source_sha256)
        if request_id is not None:
            cached[request_id] = {"text": text, "call_id": call_id, "source_sha256": output.source_sha256}
            self.store.checkpoint()
        self.calls.append(response)
        return response
