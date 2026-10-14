"""OR-LLM-Agent's mathematical modeling, coding and debugging workflow."""

from typing import Any

from llm4om.contracts import RunError
from llm4om.methods import DirectFactory, MethodContext, MethodOutcome
from llm4om.prompt_methods import PromptSession, NATIVE_CODE_INSTRUCTION


SOURCE: dict[str, Any] = {"upstream_url": "https://github.com/bwz96sco/or_llm_agent",
    "upstream_commit": "5dccdaab89ab91c3cb28066fe849423dc124d287",
    "variant_id": "or_llm_agent-public_math-code-debug/0.1.0", "adaptation": "original_prompts_shared_resources"}


class ORLLMAgentMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if checkpoint is not None:
            raise RunError("checkpoint_incompatible", "admission", "OR-LLM-Agent has no internal continuation checkpoint.")
        session = PromptSession("or_llm_agent", SOURCE, problem, context)
        formulation = await session.complete("math_model", "Act as the mathematical modeling agent. Translate the public "
            "natural-language problem into a complete mathematical model: sets, parameters, decision variables and domains, "
            "objective and every constraint. Explain assumptions and explicitly identify missing information. Do not write code.", session.inputs)
        source = await session.complete("code", NATIVE_CODE_INSTRUCTION, {**session.inputs, "formulation": formulation}, phase="code")
        limit = min(self.config["max_debug_attempts"], int(context.budget["max_repairs"]))
        code, execution_id = await session.debug_script(source, {**session.inputs, "formulation": formulation}, limit)
        return session.outcome({"mathematical_model": formulation}, code, execution_id)


class ORLLMAgentFactory:
    def describe(self) -> dict[str, Any]:
        manifest = DirectFactory().describe()
        manifest.update(plugin_id="llm4om.methods.or_llm_agent", plugin_version="0.1.0", display_name="OR-LLM-Agent",
            description="Natural language to mathematical model, native code and bounded public-feedback debugging.", source=SOURCE,
            config_schema={"type": "object", "properties": {"max_debug_attempts": {"type": "integer", "minimum": 0, "maximum": 10}},
                "additionalProperties": False})
        manifest["capabilities"].update(method_profile="native_script/0.2.0", data_access="full",
            formulation_representations=["native_formulation"], code_representations=["native_script"],
            model_backends=["llm4om.model_backends.gurobipy"], solvers=["llm4om.solvers.gurobi"],
            execution_modes=["container"], supports_checkpoint=False)
        return manifest

    def create(self, config: dict[str, Any]) -> ORLLMAgentMethod:
        return ORLLMAgentMethod({"max_debug_attempts": 2, **config})
