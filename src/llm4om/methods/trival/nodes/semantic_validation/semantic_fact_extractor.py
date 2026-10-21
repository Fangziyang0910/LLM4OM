"""Extract semantic facts and formulation-relevant ambiguities from the problem description."""

from typing import Any

from langchain.agents import create_agent
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import Command

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

SEMANTIC_FACT_EXTRACTOR_SYSTEM_PROMPT = """
You are the semantic fact extractor. Extract or revise the semantic facts and formulation-relevant ambiguities according to the instructions.

Goal:
- Extract, in natural language, what parameters are known, what objectives should be achieved, and what constraints/rules exist.
- Work at the semantic level only: do NOT define decision variables, do NOT write mathematical expressions, and do NOT propose solution methods.
- The output will be used later for formal mathematical modeling and should avoid speculation that is not supported by the problem.

Semantic Facts:
- Focus on objects/sets, key data types, objective meaning, and constraint categories / system logic (e.g., flows, balances, evolution rules).
- It is acceptable to include simple derived facts that are directly implied by the problem (e.g., fixed monthly wage per worker), as long as they do not introduce new assumptions.

Ambiguity Criteria:
- List an item in semantic_ambiguities only when:
  - The problem statement leaves multiple reasonable semantic interpretations, AND
  - Different interpretations would change system dynamics, cost accounting, or the semantics of the objective/constraints (even if the optimal solution might end up the same), AND
  - The preferred interpretation is not uniquely forced by the wording; common practice can suggest a choice, but alternatives remain plausible.
- If the semantics are effectively fixed by the problem text, do not list them as ambiguous.
- It is acceptable that semantic_ambiguities is empty when no such points exist.

Tool Usage:
- You must call write_semantic_facts to write or update semantic_facts (in Markdown format with the fixed structure below).
- Only call write_semantic_ambiguities when there are ambiguities according to the criteria above.
- When revising, change only the parts that validation feedback identifies as needing correction or completion; do not rewrite correct sections.

semantic_facts Writing Format (exactly these three sections):
## Parameters
- <objects/sets, key data and their meanings>

## Objective
- <optimization direction and semantic meaning of cost/benefit>

## Constraints
- <constraint categories and natural language rule expressions>

semantic_ambiguities Writing Format:
## Ambiguities
- <ambiguity name>: <why this point has multiple reasonable interpretations and how it could affect system dynamics, cost accounting, or objective/constraint semantics>
"""


@tool("write_semantic_facts")
def write_semantic_facts(semantic_facts: str, runtime: ToolRuntime[ContextSchema]) -> Command:
    """Write the generated semantic_facts text to state. Input is the complete Markdown content."""
    logger.info("📝 write_semantic_facts: Writing semantic_facts")
    return Command(
        update={
            "semantic_facts": semantic_facts,
            "messages": [
                ToolMessage(
                    content="semantic_facts has been written.",
                    tool_call_id=runtime.tool_call_id,
                    name="write_semantic_facts",
                )
            ],
        }
    )


@tool("write_semantic_ambiguities")
def write_semantic_ambiguities(
    semantic_ambiguities: str, runtime: ToolRuntime[ContextSchema]
) -> Command:
    """Write the generated semantic_ambiguities text to state. Input is the complete Markdown content."""
    logger.info("📝 write_semantic_ambiguities: Writing semantic_ambiguities")
    update = {
        "semantic_ambiguities": semantic_ambiguities,
        "messages": [
            ToolMessage(
                content="semantic_ambiguities has been written.",
                tool_call_id=runtime.tool_call_id,
                name="write_semantic_ambiguities",
            )
        ],
    }
    if (
        semantic_ambiguities != runtime.state.get("semantic_ambiguities")
        or not semantic_ambiguities.strip()
    ):
        update.update(ambiguity_resolutions=None, resolutions_consistent=None)
    return Command(update=update)


async def semantic_fact_extractor(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Extract semantic facts and formulation-relevant ambiguities."""
    logger.info("🔍 Semantic Fact Extractor: Extracting facts and ambiguities")

    facts_faithful = state.get("facts_faithful")
    ambiguities_relevant = state.get("ambiguities_relevant")
    feedback = state.get("semantic_validation_feedback")

    is_semantic_revision = (
        facts_faithful is False or ambiguities_relevant is False
    ) and feedback

    if is_semantic_revision:
        human_message = f"""## Original Problem Description
{state["problem_description"]}

## Current Semantic Facts
{state.get("semantic_facts", "(none)")}

## Current Ambiguities
{state.get("semantic_ambiguities", "(none)")}

## Validation Feedback
{feedback}

Revise the current semantic specification to satisfy the validation requirements.
"""
    else:
        human_message = f"""## Original Problem Description
{state["problem_description"]}

Generate semantic specification: extract semantic facts and ambiguities.
"""

    agent = create_agent(
        model=runtime.context.llm("trival.semantic_fact_extractor"),
        tools=[write_semantic_facts, write_semantic_ambiguities],
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=SEMANTIC_FACT_EXTRACTOR_SYSTEM_PROMPT,
        name="semantic_fact_extractor",
    )

    agent_state = dict(state)
    if ambiguities_relevant is False:
        agent_state.update(
            semantic_ambiguities=None,
            ambiguity_resolutions=None,
            resolutions_consistent=None,
        )

    result = await agent.ainvoke(
        {**agent_state, "messages": [HumanMessage(content=human_message)]},
        config=config,
    )

    logger.info("✅ Semantic Fact Extractor: Completed")
    return {
        "semantic_facts": result.get("semantic_facts"),
        "semantic_ambiguities": result.get("semantic_ambiguities"),
        "ambiguity_resolutions": result.get(
            "ambiguity_resolutions", agent_state.get("ambiguity_resolutions")
        ),
        "resolutions_consistent": result.get(
            "resolutions_consistent", agent_state.get("resolutions_consistent")
        ),
    }
