from typing import Any

from langchain.agents import create_agent
from langchain.messages import AnyMessage, HumanMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import Command

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

from .context_utils import build_semantic_context


@tool("select_formulation")
def select_formulation(expert_name: str, runtime: ToolRuntime[ContextSchema]) -> Command:
    """Select the highest-quality expert candidate and copy it to formulation.

    Args:
        expert_name: The expert name to select. Valid options: parameter_index_expert, constraint_expert, decision_variable_expert, objective_expert
    """
    logger.info(f"🎯 select_formulation: Selected expert '{expert_name}'")

    expert_field_mapping = {
        "parameter_index_expert": "parameter_index_candidate",
        "constraint_expert": "constraint_candidate",
        "decision_variable_expert": "decision_variable_candidate",
        "objective_expert": "objective_candidate",
    }

    state = runtime.state
    field_name = expert_field_mapping.get(expert_name)
    selected_formulation = state.get(field_name, "")

    if not selected_formulation:
        logger.warning(f"⚠️ Selected expert '{expert_name}' has empty output")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Error: Expert name '{expert_name}' is incorrect or this expert has no output. Valid expert names are: parameter_index_expert, constraint_expert, decision_variable_expert, objective_expert. Please check the spelling and try again.",
                        tool_call_id=runtime.tool_call_id,
                        name="select_formulation",
                    )
                ],
            }
        )

    return Command(
        update={
            "formulation": selected_formulation,
            "selected_formulation_expert": expert_name,
            "messages": [
                ToolMessage(
                    content=f"Selected {expert_name}'s candidate as the highest quality formulation.",
                    tool_call_id=runtime.tool_call_id,
                    name="select_formulation",
                )
            ],
        }
    )


FORMULATION_SELECTOR_SYSTEM_PROMPT = """
You are the Formulation Selector. Your mission is to select the single best mathematical formulation from four expert candidates.

### 1. Decision Authority: Ground Truth
- **Absolute Truth**: The **problem_description** is the ultimate source of truth.\x20
- **Reference**: The semantic specification (semantic_facts, ambiguity_resolutions) is a helpful summary for understanding, but it might contain errors or omissions. If an expert candidate aligns with the original description but contradicts the semantic specification, prioritize the one that matches the original description.

### 2. Selection Hierarchy

#### TIER 1: Mathematical Fidelity (Mandatory)
- **Completeness**: Does it cover all hard constraints and the correct objective purpose described in the problem?
- **Soundness**: Are the variable domains and index ranges mathematically valid? Reject candidates with logical contradictions (e.g., negative supply, impossible demands).
- **Index Alignment**: Does the indexing correctly represent the underlying dimensions of the problem?

#### TIER 2: Modeling Elegance (Quality)
- **Variable Parsimony**: Prefer the most concise variable definition that captures the necessary decisions. Avoid bloated or redundant variable sets.
- **Constraint Clarity**: Favor direct, transparent, and atomic constraints over complex, coupled, or heavily nested expressions.
- **Self-Cleaning**: Give preference to models that define clean, necessary parameters and avoid inventing data not found in the original description.

### 3. Selection Process
1.  **Elimination**: Discard any candidate that misinterprets the objective goal or misses a core constraint from the **original description**.
2.  **Comparison**: Compare the remaining valid candidates on "clarity" and "simplicity".
3.  **Selection**: Pick the winner that offers the best balance of absolute correctness and implementation-friendly simplicity.

### 4. Action
Call `select_formulation` with the name of the chosen expert.
""".strip()


async def formulation_selector(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Formulation Selector node - select the highest-quality expert candidate."""
    semantic_context = build_semantic_context(state)

    parameter_index_candidate = state.get("parameter_index_candidate", "")
    constraint_candidate = state.get("constraint_candidate", "")
    decision_variable_candidate = state.get("decision_variable_candidate", "")
    objective_candidate = state.get("objective_candidate", "")

    human_message = f"""{semantic_context}

## Parameter-and-index Expert Candidate:
{parameter_index_candidate}

## Constraint Expert Candidate:
{constraint_candidate}

## Decision-variable Expert Candidate:
{decision_variable_candidate}

## Objective Expert Candidate:
{objective_candidate}

Analyze these candidates thoroughly and select the highest-quality one using the select_formulation tool.
"""
    messages: list[AnyMessage] = [HumanMessage(content=human_message)]

    agent = create_agent(
        model=runtime.context.llm("trival.formulation_selector"),
        tools=[select_formulation],
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=FORMULATION_SELECTOR_SYSTEM_PROMPT,
        name="formulation_selector",
    )

    result: dict[str, Any] = await agent.ainvoke(
        {**state, "messages": messages}, config=config
    )

    return {
        "formulation": result.get("formulation", ""),
        "selected_formulation_expert": result.get("selected_formulation_expert"),
    }
