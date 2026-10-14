"""OptiMUS clause extraction, mathematical modeling and public code debugging."""

from typing import Any

from llm4om.contracts import RunError, parse_json
from llm4om.methods import MethodContext, MethodOutcome
from llm4om.or_llm_agent import ORLLMAgentFactory
from llm4om.prompt_methods import PromptSession, json_reply

COMMIT = "e182e9ef5841605c2a7e87467021fd83522b6484"
VARIANT = "optimus-clause_math-configured_code/0.2.0"
SOURCE: dict[str, Any] = {"upstream_commit": COMMIT, "upstream_url": "https://github.com/teshnizi/OptiMUS",
    "variant_id": VARIANT, "adaptation": "clause_modeling_public_debug_configured_backend_solver", "license": "MIT"}


class OptimusMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if checkpoint is not None:
            raise RunError("checkpoint_incompatible", "admission", "OptiMUS has no internal continuation checkpoint.")
        if self.config["rag_mode"] is not None:
            raise RunError("rag_resources_unavailable", "admission", "RAG requires admitted compatible public resources.")
        session = PromptSession("optimus", SOURCE, problem, context)
        declared = {}
        if "params_data_id" in self.config:
            try:
                params = parse_json(context.data[self.config["params_data_id"]])
                labels = parse_json(context.data[self.config["labels_data_id"]])
            except KeyError as error:
                raise RunError("invalid_method_input", "admission", "Declared public parameters and labels are missing.") from error
            if (not isinstance(labels, dict) or any(not isinstance(value, dict) or
                    not {"value", "shape", "definition"} <= value.keys() for value in params.values())):
                raise RunError("invalid_method_input", "admission", "Public parameters require value, shape and definition.")
            declared = params
        inputs = {**session.inputs, "declared_parameters": declared}
        state: dict[str, Any] = {}
        state["parameters"] = json_reply(await session.complete("parameters", "Extract the sets and numerical parameters "
            "from the public problem and data. Preserve their values, shapes, units and definitions. Use supplied declarations "
            "when present. Do not invent missing values. Return a JSON object keyed by parameter symbol.", inputs))
        session.record("state_1_params.json", state)
        state["objective_description"] = await session.complete("objective", "Identify the optimization goal and direction "
            "from the description. Separate the objective from conditions on the decisions. Do not introduce a new goal.",
            {**inputs, "parameters": state["parameters"]})
        session.record("state_2_objective.json", state)
        constraints = json_reply(await session.complete("constraints", "Extract every condition the decisions must satisfy, "
            "including variable domains and necessary non-negativity. Include implicit conditions only when justified by the "
            "public description. Check coverage against every requirement and remove only semantically redundant duplicates. "
            "Return JSON {constraints:[string]}; keep the objective separate.", {**inputs, **state}))
        if (set(constraints) != {"constraints"} or not isinstance(constraints["constraints"], list)
                or any(not isinstance(item, str) or not item.strip() for item in constraints["constraints"])):
            raise RunError("invalid_method_reply", "formulation", "OptiMUS requires an explicit constraint list.")
        state["constraint_descriptions"] = constraints["constraints"]
        state["constraints"], state["variables"] = [], {}
        session.record("state_3_constraints.json", state)
        for clause in state["constraint_descriptions"]:
            modeled = json_reply(await session.complete("constraint_model", "Model this condition mathematically for an "
                "LP/MILP, using the public parameters and variables defined so far. Introduce necessary decision variables "
                "with their domain, shape and meaning; introduce auxiliary constraints when needed. Reuse existing symbols "
                "consistently. Return JSON {formulation:string,new_variables:object,auxiliary_constraints:[string]}.",
                {**inputs, "parameters": state["parameters"], "variables": state["variables"], "constraint": clause}))
            if (set(modeled) != {"formulation", "new_variables", "auxiliary_constraints"}
                    or not isinstance(modeled["formulation"], str) or not modeled["formulation"].strip()
                    or not isinstance(modeled["new_variables"], dict) or not isinstance(modeled["auxiliary_constraints"], list)
                    or any(not isinstance(item, str) or not item.strip() for item in modeled["auxiliary_constraints"])):
                raise RunError("invalid_method_reply", "formulation", "OptiMUS requires a mathematical clause and variable declarations.")
            for name, variable in modeled["new_variables"].items():
                if name in state["variables"] and state["variables"][name] != variable:
                    raise RunError("invalid_method_reply", "formulation", "OptiMUS changed an existing variable definition.")
                state["variables"][name] = variable
            state["constraints"].append({"description": clause, **modeled})
        session.record("state_4_constraints_modeled.json", state)
        state["objective"] = await session.complete("objective_model", "Formulate the extracted objective mathematically "
            "using the existing parameters and variables. Preserve its direction and constant terms. Explain any additional "
            "variables that are needed; do not silently change the goal.", {**inputs, **state})
        state["mathematical_model"] = state["objective"] + "\n" + "\n".join(
            item["formulation"] + "\n" + "\n".join(item["auxiliary_constraints"]) for item in state["constraints"])
        session.record("state_5_objective_modeled.json", state)
        source = await session.complete("code", "Assemble the objective, decision variables and all modeled clauses into "
            "one consistent implementation. " + session.code_instruction, {**inputs, "formulation": state}, phase="code")
        session.record("state_6_code.json", {**state, "code": source})
        return await session.debug_factory(source, state, inputs,
            min(self.config["max_debug_attempts"], int(context.budget["max_repairs"])))


class OptimusFactory:
    def describe(self) -> dict[str, Any]:
        manifest = ORLLMAgentFactory().describe()
        manifest.update(plugin_id="llm4om.methods.optimus", display_name="OptiMUS",
            description="Objective and constraint extraction, clause modeling, code assembly and public-feedback debugging.",
            source=SOURCE, config_schema={"type": "object", "properties": {
                "rag_mode": {"enum": [None, "problem_description", "constraint_or_objective", "problem_labels"]},
                "params_data_id": {"type": "string", "minLength": 1}, "labels_data_id": {"type": "string", "minLength": 1},
                "max_debug_attempts": {"type": "integer", "minimum": 0, "maximum": 10}},
                "required": ["rag_mode"], "dependentRequired": {"params_data_id": ["labels_data_id"], "labels_data_id": ["params_data_id"]},
                "additionalProperties": False})
        return manifest

    def create(self, config: dict[str, Any]) -> OptimusMethod:
        return OptimusMethod({"rag_mode": None, "max_debug_attempts": 2, **config})


class OptimusInlineFactory(OptimusFactory):
    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(plugin_id="llm4om.methods.optimus_inline", display_name="OptiMUS")
        return manifest
