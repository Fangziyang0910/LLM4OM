"""The grounded single-candidate method profile and built-in direct method."""

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
from typing import Any, Callable, Mapping, Protocol
from dataclasses import field
from uuid import uuid4
from llm4om.control import CancellationToken

from llm4om.contracts import RunError, parse_json


@dataclass(frozen=True)
class LLMResponse:
    text: str
    call_id: str
    evidence_origin: str
    source_sha256: str
    finish_reason: str | None = None


@dataclass(frozen=True)
class GenerationFailure:
    """Method-reported decoder failure bound to a real response, without raw text."""

    call_id: str
    response_sha256: str
    code: str
    stage: str
    message: str


class LLMGateway(Protocol):
    async def complete(self, request: dict[str, Any]) -> LLMResponse: ...


@dataclass(frozen=True)
class FactoryCodeProposal:
    """Versioned method output; source bytes are never executed on the host."""

    source: str
    source_sha256: str
    data_bindings: list[dict[str, Any]]
    schema_version: str = "0.1.0"
    representation_kind: str = "python_factory"


@dataclass(frozen=True)
class ScriptCodeProposal:
    """Original native script and explicitly derived public data.json bytes."""

    source: str
    source_sha256: str
    data_bindings: list[dict[str, Any]]
    data_json: bytes
    schema_version: str = "0.1.0"
    representation_kind: str = "native_script"


class MethodResources(Protocol):
    def remaining_budget(self) -> dict[str, Any]: ...
    async def assess(self, candidate_id: str, proposal: "ModelProposal | GenerationFailure", *, parent_id: str | None = None,
                     change_reason: str | None = None) -> dict[str, Any]: ...
    def select(self, candidate_id: str, *, rule: str, reason: str) -> "MethodOutcome": ...
    async def execute(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]: ...
    def record(self, name: str, value: bytes) -> dict[str, Any]: ...
    def emit(self, event: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class ModelProposal:
    artifact: dict[str, Any]
    formulation: dict[str, Any] | None
    structured_ir: dict[str, Any] | None = None
    code: FactoryCodeProposal | ScriptCodeProposal | None = None
    execution_id: str | None = None


@dataclass(frozen=True)
class MethodOutcome:
    status: str
    final_candidate_id: str | None
    proposal: ModelProposal | None
    clarification: dict[str, Any] | None = None


@dataclass(frozen=True)
class MethodContext:
    llm: LLMGateway
    data: Mapping[str, bytes]
    budget: Mapping[str, Any]
    problem_sha256: str
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    save_checkpoint: Callable[[dict[str, Any]], None] | None = None
    resources: MethodResources | None = None
    deadline: float | None = None
    clarifications: tuple[dict[str, Any], ...] = ()


class DirectMethod:
    def __init__(self, output_mode: str = "lp_ir") -> None:
        self.output_mode = output_mode

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None, feedback: dict[str, Any] | None = None,
                  role: str | None = None, allow_clarification: bool = False) -> MethodOutcome:
        context.cancellation.check()
        if checkpoint is not None and (set(checkpoint) != {"schema_version", "request_id"}
                or checkpoint["schema_version"] != "0.1.0" or not isinstance(checkpoint["request_id"], str)):
            raise RunError("checkpoint_incompatible", "formulation", "Direct request checkpoint is invalid.")
        checkpoint = checkpoint or {"schema_version": "0.1.0", "request_id": uuid4().hex}
        if context.save_checkpoint is not None:
            context.save_checkpoint(checkpoint)
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
            "Ground finite numeric coefficients in the public problem and supplied CSV/JSON values. Preserve data value types. Null means unbounded. "
            "Use only public requirement IDs. assumptions is an array. "
            "Do not generate platform IDs, references, hashes, provenance, code, or answers. "
            "Five-element text and grounded LPIR must express the same model."
        )
        if self.output_mode in ("python_factory", "native_gurobipy"):
            instructions = (
                "Return only one JSON object with representation and python_factory (a Python source string). "
                "representation is the five-element schema: sets=[{id,elements or source:{data_id,column}}], "
                "parameters=[{id,index_sets,value or source:{data_id,column,key_column}}], "
                "variables=[{id,index_sets,domain,lower_bound,upper_bound,requirement_ids}], "
                "objective={sense:min|max,expression_text,requirement_ids}, "
                "constraints=[{id,expression_text,requirement_ids}]. "
                "Use parameterized expressions grounded in the public problem and provided data, not stale literal data. "
                "python_factory defines build_model(data), where data maps each public data_id to raw CSV/JSON bytes. Parse the declared format. "
                "Build a concrete Pyomo LP/MILP, and return llm4om.backends.ModelHandle(model, decision_map). "
                "decision_map maps explicit stable decision IDs to every scalar Pyomo variable, one to one. "
                "Only real/integer/binary interval domains and finite linear expressions are supported. "
                "Exactly one active objective is required; preserve objective and constraint constants. "
                "Do not solve or report answers, read files/environment, or create platform hashes/references. "
                "Source Formulation and factory must express the same public problem."
            )
        if self.output_mode == "native_gurobipy":
            instructions = instructions.replace("python_factory", "native_gurobipy").replace("concrete Pyomo", "native gurobipy")
            instructions = instructions.replace("scalar Pyomo variable", "scalar Gurobi variable (including range slack variables)")
            instructions += " Use gp.Env(empty=True), OutputFlag=0, LogFile=\"\", env.start(), and gp.Model(env=env)."
        if feedback is not None:
            instructions += (" Repair the previous candidate using only the public feedback. "
                "Also return repair_stage (formulation or code) and a nonempty change_reason. "
                "Preserve every business requirement, variable domain and data binding. "
                "Do not delete or relax requirements just to obtain a feasible model. "
                "A Solver primal does not prove the original problem is correctly modeled.")
            if self.output_mode in ("python_factory", "native_gurobipy"):
                instructions += " For repair_stage=code you may omit representation to reuse the source Formulation."
            else:
                instructions += " Grounded LPIR corrections use repair_stage=formulation because LPIR is the executable mathematical representation."
        payload: dict[str, Any] = {"problem": problem, "data": {key: value.decode("utf-8") for key, value in context.data.items()}}
        if allow_clarification:
            instructions += (" If a business rule is missing, return only {clarification:{questions:[{question_id,kind,question,statement_ref}]}}. "
                "kind is confirm_existing or new_information. Confirm existing requirement/assumption by statement_ref={kind:requirement|assumption,id}; "
                "new_information uses statement_ref=null. Do not guess missing rules. Confirmed clarification records are public input.")
            payload["clarifications"] = list(context.clarifications)
        if feedback is not None:
            payload["feedback"] = feedback
        response = await context.llm.complete({"request_id": checkpoint["request_id"], **({"role": role} if role else {}), "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]})
        try:
            if response.finish_reason == "length":
                raise RunError("llm_output_truncated", "formulation", "The LLM reached its output limit before completing the formulation.")
            value = parse_json(response.text.encode())
            if allow_clarification and set(value) == {"clarification"} and isinstance(value["clarification"], dict):
                return MethodOutcome("needs_input", None, None, {**value["clarification"], "provenance": {
                    "origin": response.evidence_origin, "call_id": response.call_id, "response_sha256": response.source_sha256}})
            repair = None
            if feedback is not None:
                repair = {"stage": value.pop("repair_stage", None), "reason": value.pop("change_reason", None)}
                if repair["stage"] not in ("formulation", "code") or not isinstance(repair["reason"], str) or not repair["reason"].strip():
                    raise RunError("invalid_method_outcome", "formulation", "Repair output needs a stage and a nonempty change reason.")
                if self.output_mode == "lp_ir" and repair["stage"] == "code":
                    raise RunError("invalid_method_outcome", "formulation", "Grounded LPIR corrections must declare the formulation stage.")
                if repair["stage"] == "code" and self.output_mode in ("python_factory", "native_gurobipy") and "representation" not in value:
                    previous = feedback.get("previous_output")
                    if not isinstance(previous, dict) or previous.get("representation") is None:
                        raise RunError("invalid_method_outcome", "formulation", "Code-only repair needs an existing source Formulation.")
                    value["representation"] = previous["representation"]
            if self.output_mode in ("python_factory", "native_gurobipy"):
                source_key = self.output_mode
                if set(value) != {"representation", source_key} or not isinstance(value[source_key], str):
                    raise RunError("invalid_method_outcome", "code", "Direct requires representation and Python factory source.")
                bindings = [{"data_id": item["data_id"], "sha256": item["sha256"]} for item in problem["data_refs"]]
                provenance = {"origin": response.evidence_origin, "call_id": response.call_id,
                              "response_sha256": response.source_sha256,
                              "code_relationship": "method_generated_from_source_formulation"}
                formulation = {"schema_version": "0.2.0", "formulation_id": "direct-formulation-001",
                               "problem_id": problem["problem_id"], "problem_revision": problem["revision"],
                               "representation_kind": "five_element", "representation": value["representation"],
                               "data_bindings": bindings, "structured_ir_ref": None, "provenance": provenance}
                if repair is not None and repair["stage"] == "code" and feedback is not None:
                    previous = feedback.get("previous_output")
                    if (isinstance(previous, dict) and isinstance(previous.get("source_formulation"), dict)
                            and value["representation"] == previous["source_formulation"]["representation"]):
                        formulation = deepcopy(previous["source_formulation"])
                artifact: dict[str, Any] = {"schema_version": "0.2.0", "artifact_id": "direct-artifact-001",
                            "problem_ref": {"sha256": context.problem_sha256}, "formulation_ref": {}, "code_ref": None,
                            "data_bindings": bindings, "assumptions": [], "requirement_traces": [],
                            "diagnostics": [], "warnings": [], "optional_views": [], "provenance": provenance,
                            "stage_status": {"formulation": {"status": "available", "reason": None},
                                             "code": {"status": "pending", "reason": "Factory contract has not been checked."}}}
                code = FactoryCodeProposal(value[source_key], hashlib.sha256(value[source_key].encode()).hexdigest(), bindings,
                                           representation_kind="native_code" if self.output_mode == "native_gurobipy" else "python_factory")
                if repair is not None:
                    artifact["provenance"]["repair"] = repair
                return MethodOutcome("candidate_selected", "001", ModelProposal(artifact, formulation, code=code))
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
            if repair is not None:
                proposal.artifact["provenance"]["repair"] = repair
            return MethodOutcome("candidate_selected", "001", proposal)
        except RunError as error:
            raise RunError(error.code, error.stage, str(error),
                details={"call_id": response.call_id, "response_sha256": response.source_sha256}) from error



class DirectFactory:
    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": "0.2.0", "plugin_id": "llm4om.methods.direct", "kind": "method",
            "plugin_version": "0.17.0", "contract_range": ">=0.2.0,<0.3.0",
            "display_name": "Direct (declared text output)",
            "description": "One public text response produces a five-element Formulation with grounded LPIR or parameterized Python factory.",
            "capabilities": {"method_profile": "grounded_single_candidate/0.1.0", "problem_types": ["lp", "milp"],
                "input_artifact_kinds": ["public_problem"], "output_artifact_kinds": ["model_artifact"],
                "formulation_representations": ["five_element"], "code_representations": ["python_factory"],
                "model_backends": ["llm4om.model_backends.pyomo_factory"], "solvers": ["llm4om.solvers.highs", "llm4om.solvers.gurobi"],
                "llm_features": ["text"], "execution_modes": ["trusted_local", "container"],
                "supports_checkpoint": True, "cancellation": "cooperative/0.1.0", "supports_clarification": False, "oracle_requirements": []},
            "config_schema": {"type": "object", "properties": {
                "formulation_mode": {"const": "five_element"}, "output_mode": {"enum": ["lp_ir", "python_factory", "native_gurobipy"]}},
                "required": ["formulation_mode", "output_mode"], "additionalProperties": False},
            "dependencies": {"python": []}, "source": None,
        }

    def resolve_capabilities(self, config: dict[str, Any]) -> dict[str, Any]:
        capabilities: dict[str, Any] = self.describe()["capabilities"]
        if config["output_mode"] == "python_factory":
            capabilities.update(method_profile="factory_single_candidate/0.1.0", execution_modes=["container"])
        if config["output_mode"] == "native_gurobipy":
            capabilities.update(method_profile="native_single_candidate/0.1.0", execution_modes=["container"],
                code_representations=["native_code"], model_backends=["llm4om.model_backends.gurobipy"],
                solvers=["llm4om.solvers.gurobi"])
        return capabilities

    def create(self, config: dict[str, Any]) -> DirectMethod:
        return DirectMethod(config["output_mode"])
