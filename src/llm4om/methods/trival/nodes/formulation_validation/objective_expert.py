from typing import Any

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

from .context_utils import get_expert_instruction_and_context
from .formulation_prompts import FORMULATION_FORMAT_PROMPT, FORMULATION_SHARED_RULES

OBJECTIVE_EXPERT_SYSTEM_PROMPT_BASE = """
You are the objective expert. Your responsibility is to build a high-quality, correct formulation from an objective design perspective. Output only the final formulation text. Do not output any other fields or commentary.

## General Rules
{formulation_shared_rules}

## Objective Expert Guidelines
- First fully fix the "billing/penalty metric" of the objective according to semantic_facts/ambiguity_resolutions, then write the objective expression; do not change the metric on your own.
- The objective function should be as concise as possible, avoiding introducing additional accounting variables; only add the minimum number of variables when the objective cannot be directly expressed with existing variables.
- Any quantities appearing in the objective (such as backlog, delay, deviation, etc.) that are not direct decision variables must have clear variable definitions and constraint relationship support; otherwise, do not introduce them.
- Clearly specify type (min|max|satisfy) and expr; all symbols in expr must be defined with consistent indexing.
- Do not create multiple objectives; if there are multiple cost items, express them directly in a single objective by summation (coefficients must come from the problem or ambiguity_resolutions).
- Under the premise of not affecting semantic correctness, prioritize objective formulations with fewer variables and more direct expressions.

## Modeling Rules
{formulation_format_prompt}
""".strip()


async def objective_expert(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Objective expert node - structures the objective and a full formulation."""
    logger.info("🎯 Objective expert analysis started")

    system_prompt = OBJECTIVE_EXPERT_SYSTEM_PROMPT_BASE.format(
        formulation_format_prompt=FORMULATION_FORMAT_PROMPT,
        formulation_shared_rules=FORMULATION_SHARED_RULES,
    ).strip()

    agent = create_agent(
        model=runtime.context.llm("trival.objective_expert"),
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=system_prompt,
        name="objective_expert",
    )

    instruction_msg = get_expert_instruction_and_context(state)

    result: dict[str, Any] = await agent.ainvoke(
        {**state, "messages": [instruction_msg]}, config=config
    )
    messages = result.get("messages", [])
    output_text = messages[-1].text

    logger.info("✅ Objective expert analysis completed")
    return {"objective_candidate": output_text}
