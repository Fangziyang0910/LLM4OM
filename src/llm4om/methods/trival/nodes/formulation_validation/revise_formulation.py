from typing import Any

from langchain.agents import create_agent
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import Command

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

from .context_utils import build_semantic_context
from .formulation_prompts import FORMULATION_FORMAT_PROMPT, FORMULATION_SHARED_RULES


@tool("write_formulation")
def write_formulation(formulation: str, runtime: ToolRuntime[ContextSchema]) -> Command:
    """Write the corrected formulation after minimal fixes."""
    logger.info("🛠️ write_formulation: Writing fixed formulation")

    return Command(
        update={
            "formulation": formulation,
            "messages": [
                ToolMessage(
                    content="Fixed formulation has been written.",
                    tool_call_id=runtime.tool_call_id,
                    name="write_formulation",
                )
            ],
        }
    )


FORMULATION_REVISION_SYSTEM_PROMPT = f"""
You are a formulation repair expert. Correct the given formulation using the confirmed semantic ground truth and the validation feedback.

Inputs:
- selected_formulation: current formulation
- semantic_facts, ambiguity_resolutions: confirmed semantic ground truth
- formulation_validation_feedback: issues to fix

General Rules:
{FORMULATION_SHARED_RULES}

Formulation format:
{FORMULATION_FORMAT_PROMPT}

Fixing guidance:
- Apply minimal edits to resolve the validation issues, prioritizing correctness and semantic fidelity.
- Keep the formulation high-quality and lean: favor simpler variable design and direct, elegant constraints; remove redundancy; avoid unnecessary auxiliary variables.
- When a feedback item conflicts with semantic_facts/ambiguity_resolutions, follow the semantic ground truth.

Action:
Write the full corrected formulation via `write_formulation`.
""".strip()


async def revise_formulation(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Revise the formulation with minimal corrections."""
    logger.info("🛠️ Formulation Revision: Applying minimal corrections")

    semantic_context = build_semantic_context(state)
    selected_formulation = state.get("formulation", "")
    formulation_validation_feedback = state.get("formulation_validation_feedback", "")

    code_validation_feedback = state.get("code_validation_feedback", "")
    error_attribution = state.get("error_attribution")

    user_content_parts = [semantic_context]

    user_content_parts.append(f"## Selected Formulation\n{selected_formulation}")

    if formulation_validation_feedback:
        user_content_parts.append(
            f"## Formulation Validation Feedback\n{formulation_validation_feedback}"
        )

    if error_attribution == "formulation" and code_validation_feedback:
        user_content_parts.append(
            f"## Code Validation Feedback (Reason for Formulation Revision)\n{code_validation_feedback}"
        )

    user_content = "\n\n".join(user_content_parts)

    agent = create_agent(
        model=runtime.context.llm("trival.revise_formulation"),
        tools=[write_formulation],
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=FORMULATION_REVISION_SYSTEM_PROMPT,
        name="revise_formulation",
    )

    result = await agent.ainvoke(
        {**state, "messages": [HumanMessage(content=user_content)]},
        config=config,
    )
    return {
        "formulation": result.get("formulation", ""),
        "error_attribution": None,
        "code_validation_passed": None,
        "code_validation_feedback": None,
        "code_executable": None,
        "execution_feedback": None,
    }
