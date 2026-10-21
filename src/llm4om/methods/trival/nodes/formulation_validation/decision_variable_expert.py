from typing import Any

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

from .context_utils import get_expert_instruction_and_context
from .formulation_prompts import FORMULATION_FORMAT_PROMPT, FORMULATION_SHARED_RULES

DECISION_VARIABLE_EXPERT_SYSTEM_PROMPT_BASE = """
You are the decision-variable expert. Your responsibility is to build a high-quality, correct formulation from a variable design perspective. Output only the final formulation text. Do not output any other fields or commentary.

## General Rules
{formulation_shared_rules}

## Decision-variable Expert Guidelines
- First design a set of primary decision variables: use the minimum number of variables to express core decisions, prioritize atomic decisions, fewer variable types, and clear indexing.
- Once variables are determined, constraints should be expressed directly and concisely within that variable system; if a variable design forces constraints to become verbose or convoluted, change the variable design.
- Do not introduce auxiliary variables unless semantically necessary; especially avoid adding intermediate variables just for "writing convenience" or "aesthetic purposes."
- Each variable must clearly specify: description + var_type + domain + shape + unit (if applicable); domain/shape must be consistent with index sets.
- Prioritize encoding approaches that enable the most natural constraint expressions; do not pursue "advanced encoding" or complex structures.
- Objective expressions should depend directly on primary variables as much as possible; if additional quantities must be introduced, first consider rewriting with primary variables to avoid new variables.

## Modeling Rules
{formulation_format_prompt}
""".strip()


async def decision_variable_expert(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Decision-variable expert node - designs decision encodings and a full formulation."""
    logger.info("📊 Decision-variable expert analysis started")

    system_prompt = DECISION_VARIABLE_EXPERT_SYSTEM_PROMPT_BASE.format(
        formulation_format_prompt=FORMULATION_FORMAT_PROMPT,
        formulation_shared_rules=FORMULATION_SHARED_RULES,
    ).strip()

    agent = create_agent(
        model=runtime.context.llm("trival.decision_variable_expert"),
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=system_prompt,
        name="decision_variable_expert",
    )

    instruction_msg = get_expert_instruction_and_context(state)

    result: dict[str, Any] = await agent.ainvoke(
        {**state, "messages": [instruction_msg]}, config=config
    )
    messages = result.get("messages", [])
    output_text = messages[-1].text

    logger.info("✅ Decision-variable expert analysis completed")
    return {"decision_variable_candidate": output_text}
