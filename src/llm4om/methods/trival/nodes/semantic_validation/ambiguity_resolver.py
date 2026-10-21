"""Ambiguity Resolver node - resolves ambiguities with final choices."""

from typing import Any

from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

AMBIGUITY_RESOLVER_SYSTEM_PROMPT = """
You are the ambiguity resolver. Based on semantic_facts and semantic_ambiguities, resolve the ambiguous points and provide clear conventions for subsequent mathematical modeling.

Scope:
- Stay at the semantic level only; do not work at the equation/solver level.
- Do not invent new problem features; only clarify how to interpret what is already in the problem and semantic_facts.
- Do not introduce new mathematical symbols, decision variables, indices, or explicit equations/inequalities; express all resolutions in natural language.

Resolution Principles:
- Consistency:
  - Resolutions must not contradict the original problem description or semantic_facts.
- Coverage:
  - Provide one clear convention for every item listed in semantic_ambiguities.
  - Keep the original ambiguity names; do not rename or merge them.
- Plausibility:
  - Prefer interpretations that best match the wording of the problem and standard domain practice.
- Simplicity without Distortion:
  - When several interpretations are plausible and consistent, choose the simpler one.
  - Do not oversimplify in a way that changes intended system dynamics, accounting logic, or objective/constraint semantics.
- Modelability:
  - Each convention should be precise enough that different modelers would later translate it into the same mathematical structure.
  - Describe timing, roles, priorities, and evolution in words, not formulas.
- No New Ambiguities:
  - Do not introduce new ambiguity items; you may add minor, closely related clarifications inside an existing convention if they help modeling.

Output format (use exactly this structure):
## Assumptions and Conventions
- <ambiguity name>: <clear convention>
"""


async def ambiguity_resolver(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Resolve ambiguities with final choices."""
    logger.info("🔧 Ambiguity Resolver: Resolving ambiguities")

    feedback = state.get("semantic_validation_feedback")

    if feedback:
        validation_section = f"""

## Validation Feedback
{feedback}
"""
    else:
        validation_section = ""

    human_message = f"""## Original Problem Description
{state.get("problem_description")}

## Extracted Semantic Facts
{state.get("semantic_facts") or ""}

## Identified Ambiguities
{state.get("semantic_ambiguities") or ""}
{validation_section}
Complete semantic ambiguity resolution based on the above materials."""

    agent = create_agent(
        model=runtime.context.llm("trival.ambiguity_resolver"),
        tools=[],
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=AMBIGUITY_RESOLVER_SYSTEM_PROMPT,
        name="ambiguity_resolver",
    )

    result = await agent.ainvoke(
        {**state, "messages": [HumanMessage(content=human_message)]}, config=config
    )

    messages = result.get("messages", [])
    resolved_text = messages[-1].text

    logger.info("✅ Ambiguity Resolver: Completed")
    return {
        "ambiguity_resolutions": resolved_text,
    }
