"""The grounded single-candidate method profile and built-in direct method."""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from llm4om.contracts import RunError, parse_json


@dataclass(frozen=True)
class LLMResponse:
    text: str
    call_id: str
    evidence_origin: str
    source_sha256: str


class LLMGateway(Protocol):
    async def complete(self, request: dict[str, Any]) -> LLMResponse: ...


@dataclass(frozen=True)
class ModelProposal:
    artifact: dict[str, Any]
    formulation: dict[str, Any]
    structured_ir: dict[str, Any]


@dataclass(frozen=True)
class MethodOutcome:
    status: str
    final_candidate_id: str | None
    proposal: ModelProposal | None


@dataclass(frozen=True)
class MethodContext:
    llm: LLMGateway
    data: Mapping[str, bytes]
    budget: Mapping[str, Any]
    problem_sha256: str


class DirectMethod:
    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if checkpoint is not None:
            raise RunError("checkpoint_incompatible", "formulation", "This method profile does not support checkpoint.")
        response = await context.llm.complete({"messages": [{"role": "user", "content": problem["description"]}]})
        value = parse_json(response.text.encode())
        return MethodOutcome("candidate_selected", "001", ModelProposal(value["artifact"], value["formulation"], value["structured_ir"]))


class DirectFactory:
    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": "0.2.0", "plugin_id": "llm4om.methods.direct", "kind": "method",
            "plugin_version": "0.2.0", "contract_range": ">=0.2.0,<0.3.0",
            "display_name": "Direct (Mock engineering profile)",
            "description": "One public Mock text response produces a five-element Formulation and grounded LPIR.",
            "capabilities": {"method_profile": "grounded_single_candidate/0.1.0", "problem_types": ["lp", "milp"],
                "input_artifact_kinds": ["public_problem"], "output_artifact_kinds": ["model_artifact"],
                "formulation_representations": ["five_element"], "code_representations": ["python_factory"],
                "model_backends": ["llm4om.model_backends.pyomo_factory"], "solvers": ["llm4om.solvers.highs"],
                "llm_features": ["text"], "execution_modes": ["trusted_local"],
                "supports_checkpoint": False, "supports_clarification": False, "oracle_requirements": []},
            "config_schema": {"type": "object", "properties": {
                "formulation_mode": {"const": "five_element"}, "output_mode": {"const": "lp_ir"}},
                "required": ["formulation_mode", "output_mode"], "additionalProperties": False},
            "dependencies": {"python": []}, "source": None,
        }

    def create(self, config: dict[str, Any]) -> DirectMethod:
        return DirectMethod()
