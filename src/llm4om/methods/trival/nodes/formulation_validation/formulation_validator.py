from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, FormulationValidationOutput, logger
from llm4om.methods.trival.state import State

from .context_utils import build_semantic_context

FORMULATION_VALIDATOR_SYSTEM_PROMPT = """
You are the formulation validator in Stage II. Your only job is to judge whether the selected formulation faithfully represents the semantics of the original problem.

Validate the formulation as M = (P, V, C, O):
- P: parameters and index sets
- V: decision variables
- C: constraints
- O: objective

### Core Standard
- The original problem is the ground truth.
- The formulation must faithfully encode the problem's decision meaning, requirements, and optimization goal.
- Do not judge based on notation style, wording style, or whether the formulation looks more symbolic or less symbolic.
- Do not pass a formulation unless its semantics are correct and complete.

### What to check
1. Decision semantics
- Do the variables represent the real decisions required by the problem?
- If the variable design cannot express the required decisions, fail it.

2. Requirement semantics
- Do the constraints faithfully cover all problem requirements?
- Check for missing requirements, wrong logic direction, wrong scope, wrong boundary cases, and inconsistent meanings.

3. Goal semantics
- Does the objective faithfully match the actual optimization goal?
- Check for wrong direction, missing key terms, or a goal that no longer matches the problem.

4. Overall semantic consistency
- Are P, V, C, and O mutually consistent?
- Is any part semantically drifting away from the original problem, even if the math looks plausible?

### Decision Rule
- PASS: only if the formulation faithfully and completely represents the original problem semantics.
- FAIL -> PARTIAL_REVISE: the semantics are mostly right, but there is a limited local semantic error.
- FAIL -> REFORMULATE: the semantic defect is structural, so a new formulation should be explored.

### Output
- formulation_validation_feedback:
  - If failed, state the exact semantic mismatch, omission, or wrong formulation choice.
  - If passed, briefly state that the formulation faithfully captures the original problem semantics.
- formulation_validation_passed: boolean
- formulation_revision_action: null if passed, otherwise "partial_revise" or "reformulate"

Examples:
{{"formulation_validation_feedback": "Passed. The formulation faithfully captures the original problem's decisions, requirements, and optimization goal.", "formulation_validation_passed": true, "formulation_revision_action": null}}
{{"formulation_validation_feedback": "The formulation misses the capacity restriction required by the original problem, so the constraint semantics are incomplete. Add the missing capacity constraint.", "formulation_validation_passed": false, "formulation_revision_action": "partial_revise"}}
{{"formulation_validation_feedback": "The variable design cannot represent the assignment decisions required by the original problem, so the formulation does not faithfully capture the problem semantics and should be reformulated.", "formulation_validation_passed": false, "formulation_revision_action": "reformulate"}}
""".strip()


async def formulation_validator(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Validate the selected formulation and choose partial revision or reformulation."""
    current_count = state.get("formulation_validation_count", 0)
    logger.info(
        "🔎 Formulation Validator: Validating selected formulation (attempt %d)",
        current_count + 1,
    )

    semantic_context = build_semantic_context(state)
    selected_formulation = state.get("formulation", "")

    user_content = f"""{semantic_context}

## Selected Formulation
{selected_formulation}
"""

    agent = create_agent(
        model=runtime.context.llm("trival.formulation_validator"),
        tools=[],
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=FORMULATION_VALIDATOR_SYSTEM_PROMPT,
        response_format=ToolStrategy(FormulationValidationOutput),
        name="formulation_validator",
    )

    result = await agent.ainvoke(
        {**state, "messages": [HumanMessage(content=user_content)]},
        config=config,
    )
    structured: FormulationValidationOutput = result["structured_response"]

    if structured.formulation_validation_passed:
        logger.info("✅ Formulation Validator: PASSED")
    else:
        logger.info(
            "❌ Formulation Validator: NOT PASSED (%s)",
            structured.formulation_revision_action,
        )

    return {
        "formulation_validation_feedback": structured.formulation_validation_feedback,
        "formulation_validation_passed": structured.formulation_validation_passed,
        "formulation_revision_action": structured.formulation_revision_action,
        "formulation_validation_count": current_count + 1,
    }
