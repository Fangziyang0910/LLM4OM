from typing import Any

from langchain.agents import create_agent
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

from .context_utils import get_expert_instruction_and_context
from .formulation_prompts import FORMULATION_FORMAT_PROMPT, FORMULATION_SHARED_RULES

CONSTRAINT_EXPERT_SYSTEM_PROMPT_BASE = """
You are the constraint expert. Your responsibility is to build a high-quality, correct formulation from a constraint design perspective. Output only the final formulation text. Do not output any other fields or commentary.

## General Rules
{formulation_shared_rules}

## Constraint Expert Guidelines
- First list all constraint categories that must be covered (from semantic_facts/ambiguity_resolutions), then write specific constraint expressions; ensure no omissions and no semantic drift.
- Constraint expressions should be as direct as possible: avoid nesting, avoid repetition, avoid stacking multiple equivalent constraints for the same semantics.
- Do not strengthen or weaken semantics for implementation convenience; strictly determine inequality directions, boundary conditions, inter-period relationships, etc. according to semantic conventions.
- If current variables cannot directly express key constraints, prioritize requesting variable design changes; only introduce the minimum auxiliary variables when truly unavoidable, and ensure their semantics are clear.
- Each constraint must provide: description + expr, and all symbols in expr must have been defined in parameters/variables.
- Prioritize ensuring feasible domain correctness; under the premise of correctness, minimize constraint count and complexity.

## Modeling Rules
{formulation_format_prompt}
""".strip()


async def constraint_expert(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Constraint expert node - organizes constraints and a full formulation."""
    logger.info("⚖️  Constraint expert analysis started")

    system_prompt = CONSTRAINT_EXPERT_SYSTEM_PROMPT_BASE.format(
        formulation_format_prompt=FORMULATION_FORMAT_PROMPT,
        formulation_shared_rules=FORMULATION_SHARED_RULES,
    ).strip()

    agent = create_agent(
        model=runtime.context.llm("trival.constraint_expert"),
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=system_prompt,
        name="constraint_expert",
    )

    instruction_msg = get_expert_instruction_and_context(state)

    result: dict[str, Any] = await agent.ainvoke(
        {**state, "messages": [instruction_msg]}, config=config
    )
    messages = result.get("messages", [])
    output_text = messages[-1].text

    logger.info("✅ Constraint expert analysis completed")
    return {"constraint_candidate": output_text}
