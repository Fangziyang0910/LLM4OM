"""OR-LLM-Agent's mathematical modeling, coding and debugging workflow."""

from typing import Any

from llm4om.contracts import RunError
from llm4om.methods import DirectFactory, MethodContext, MethodOutcome
from llm4om.prompt_methods import PromptSession


SOURCE: dict[str, Any] = {"upstream_url": "https://github.com/bwz96sco/or_llm_agent",
    "upstream_commit": "5dccdaab89ab91c3cb28066fe849423dc124d287",
    "variant_id": "or_llm_agent-configured_math-code-debug/0.2.0", "adaptation": "math_code_public_debug_configured_backend_solver"}


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
        source = await session.complete("code", session.code_instruction, {**session.inputs, "formulation": formulation}, phase="code")
        limit = min(self.config["max_debug_attempts"], int(context.budget["max_repairs"]))
        return await session.debug_factory(source, {"mathematical_model": formulation}, session.inputs, limit)


class ORLLMAgentFactory:
    def describe(self) -> dict[str, Any]:
        manifest = DirectFactory().describe()
        manifest.update(plugin_id="llm4om.methods.or_llm_agent", plugin_version="0.2.0", display_name="OR-LLM-Agent",
            description="Mathematical modeling, configured target code and bounded public-feedback debugging.", source=SOURCE,
            config_schema={"type": "object", "properties": {"max_debug_attempts": {"type": "integer", "minimum": 0, "maximum": 10}},
                "additionalProperties": False})
        manifest["capabilities"].update(method_profile="factory_candidates/0.1.0", data_access="full",
            formulation_representations=["native_formulation"], code_representations=["python_factory", "native_code"],
            model_backends=["llm4om.model_backends.pyomo_factory", "llm4om.model_backends.gurobipy"],
            execution_modes=["container"], supports_checkpoint=False)
        return manifest

    def create(self, config: dict[str, Any]) -> ORLLMAgentMethod:
        return ORLLMAgentMethod({"max_debug_attempts": 2, **config})
