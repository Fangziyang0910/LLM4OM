from typing import Any

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

from .context_utils import get_expert_instruction_and_context
from .formulation_prompts import FORMULATION_FORMAT_PROMPT, FORMULATION_SHARED_RULES

PARAMETER_INDEX_EXPERT_SYSTEM_PROMPT_BASE = """
You are the parameter-and-index expert. Your responsibility is to build a high-quality, correct formulation from a parameter design perspective. Output only the final formulation text. Do not output any other fields or commentary.

## General Rules
{formulation_shared_rules}

## Parameter-and-index Expert Guidelines
- First establish and fix all index sets/ranges (e.g., t, i, j, k, etc.) before writing any parameters/variables/constraints/objectives.
- Parameters must provide complete data that can be directly referenced: for each parameter, clearly specify description + value + unit (if applicable); do not simply write "known/given/see table."
- Parameter names should reflect both indices and semantics (e.g., demand[f,t], cost[i]); avoid ambiguous naming.
- Only list parameters that will actually be used in variables/constraints/objectives; do not add derived parameters or intermediate quantities for the sake of "completeness."
- Do not invent information not given in the problem; if problem information is insufficient, refer to ambiguity_resolutions rather than making up your own.
- Variable and constraint expressions should directly reference parameters and indices as much as possible; do not introduce additional structures to "beautify the expression."

## Modeling Rules
{formulation_format_prompt}
""".strip()


async def parameter_index_expert(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Parameter-and-index expert node - builds index/parameter system and a full formulation."""
    logger.info("📐 Parameter-and-index expert analysis started")

    system_prompt = PARAMETER_INDEX_EXPERT_SYSTEM_PROMPT_BASE.format(
        formulation_format_prompt=FORMULATION_FORMAT_PROMPT,
        formulation_shared_rules=FORMULATION_SHARED_RULES,
    ).strip()

    agent = create_agent(
        model=runtime.context.llm("trival.parameter_index_expert"),
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=system_prompt,
        name="parameter_index_expert",
    )

    instruction_msg = get_expert_instruction_and_context(state)

    result: dict[str, Any] = await agent.ainvoke(
        {**state, "messages": [instruction_msg]}, config=config
    )
    messages = result.get("messages", [])
    output_text = messages[-1].text

    logger.info("✅ Parameter-and-index expert analysis completed")
    return {"parameter_index_candidate": output_text}
