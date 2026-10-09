"""The grounded single-candidate method profile and built-in direct method."""

from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol

from llm4om.contracts import RunError, parse_json


@dataclass(frozen=True)
class LLMResponse:
    text: str
    call_id: str
    evidence_origin: str
    source_sha256: str
    finish_reason: str | None = None


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
        instructions = (
            "Return only one JSON object with representation and structured_ir. "
            "representation has exactly sets, parameters, variables, objective, constraints, using five-element schema: "
            "sets=[{id,elements or source:{data_id,column}}]; "
            "parameters=[{id,index_sets,value or source:{data_id,column,key_column}}]; "
            "variables=[{id,index_sets,domain:continuous|integer|binary,lower_bound,upper_bound,requirement_ids}]; "
            "objective={sense:min|max,expression_text,requirement_ids}; "
            "constraints=[{id,expression_text,requirement_ids}]. "
            "structured_ir has exactly problem_type:lp|milp,variables,objective,constraints,assumptions. "
            "IR variables=[{id,name,domain:continuous|integer|binary,lower_bound,upper_bound,requirement_ids}]; "
            "IR objective={sense:min|max,expression,requirement_ids}; "
            "IR constraints=[{id,expression,sense:le|ge|eq,rhs,requirement_ids}]. "
            "Each expression={constant:number,terms:[{variable_id,coefficient:number}]}. "
            "Use finite numeric coefficients grounded in explicit public CSV values. Null means unbounded. "
            "Use only public requirement IDs. assumptions is an array. "
            "Do not generate platform IDs, references, hashes, provenance, code, or answers. "
            "Five-element text and grounded LPIR must express the same model."
        )
        response = await context.llm.complete({"messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps({"problem": problem,
                "data": {key: value.decode("utf-8") for key, value in context.data.items()}}, ensure_ascii=False)}]})
        if response.finish_reason == "length":
            raise RunError("llm_output_truncated", "formulation", "The LLM reached its output limit before completing the formulation.")
        value = parse_json(response.text.encode())
        if "artifact" in value:
            if response.evidence_origin != "mock_fixture":
                raise RunError("invalid_method_outcome", "formulation", "External Direct requires the compact mathematical output.")
            proposal = ModelProposal(value["artifact"], value["formulation"], value["structured_ir"])
        else:
            if set(value) != {"representation", "structured_ir"} or not isinstance(value["structured_ir"], dict):
                raise RunError("invalid_method_outcome", "formulation", "Direct requires representation and structured_ir.")
            ir = value["structured_ir"]
            if set(ir) != {"problem_type", "variables", "objective", "constraints", "assumptions"}:
                raise RunError("invalid_method_outcome", "formulation", "Direct IR contains unsupported or missing mathematical fields.")
            bindings = [{"data_id": item["data_id"], "sha256": item["sha256"]} for item in problem["data_refs"]]
            provenance = {"origin": response.evidence_origin, "call_id": response.call_id,
                          "response_sha256": response.source_sha256,
                          "ir_relationship": "jointly_generated_not_compiled_from_text"}
            ir.update(schema_version="0.1.0", ir_kind="grounded_lp", model_id="direct-ir-001",
                      problem_id=problem["problem_id"], problem_revision=problem["revision"],
                      data_bindings=bindings, provenance=provenance)
            formulation = {"schema_version": "0.2.0", "formulation_id": "direct-formulation-001",
                           "problem_id": problem["problem_id"], "problem_revision": problem["revision"],
                           "representation_kind": "five_element", "representation": value["representation"],
                           "data_bindings": bindings, "structured_ir_ref": {}, "provenance": provenance}
            artifact = {"schema_version": "0.2.0", "artifact_id": "direct-artifact-001",
                        "problem_ref": {"sha256": context.problem_sha256}, "formulation_ref": {}, "code_ref": None,
                        "data_bindings": bindings, "assumptions": ir["assumptions"], "requirement_traces": [],
                        "diagnostics": [], "warnings": [], "optional_views": [], "provenance": provenance,
                        "stage_status": {"formulation": {"status": "available", "reason": None},
                                         "code": {"status": "pending", "reason": "Deterministic compilation has not run."}}}
            proposal = ModelProposal(artifact, formulation, ir)
        return MethodOutcome("candidate_selected", "001", proposal)


class DirectFactory:
    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": "0.2.0", "plugin_id": "llm4om.methods.direct", "kind": "method",
            "plugin_version": "0.4.0", "contract_range": ">=0.2.0,<0.3.0",
            "display_name": "Direct (grounded text profile)",
            "description": "One public text response produces a five-element Formulation and grounded LPIR.",
            "capabilities": {"method_profile": "grounded_single_candidate/0.1.0", "problem_types": ["lp", "milp"],
                "input_artifact_kinds": ["public_problem"], "output_artifact_kinds": ["model_artifact"],
                "formulation_representations": ["five_element"], "code_representations": ["python_factory"],
                "model_backends": ["llm4om.model_backends.pyomo_factory"], "solvers": ["llm4om.solvers.highs"],
                "llm_features": ["text"], "execution_modes": ["trusted_local", "container"],
                "supports_checkpoint": False, "supports_clarification": False, "oracle_requirements": []},
            "config_schema": {"type": "object", "properties": {
                "formulation_mode": {"const": "five_element"}, "output_mode": {"const": "lp_ir"}},
                "required": ["formulation_mode", "output_mode"], "additionalProperties": False},
            "dependencies": {"python": []}, "source": None,
        }

    def create(self, config: dict[str, Any]) -> DirectMethod:
        return DirectMethod()
