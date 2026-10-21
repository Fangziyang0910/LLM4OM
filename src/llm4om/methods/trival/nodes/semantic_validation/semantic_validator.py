"""Semantic Validator node - gatekeeper that validates semantic specification and resolutions."""

from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, SemanticValidationOutput, logger
from llm4om.methods.trival.state import State

SEMANTIC_VALIDATOR_SYSTEM_PROMPT = """
You are the semantic validator in Stage I. Judge whether the current semantic specification S = (F, A, R) is correct, coherent, and ready to support formulation.

Here:
- F = semantic facts
- A = formulation-relevant ambiguities
- R = adopted resolutions

### Core Scope
- Validate semantics only.
- Do not require variables, equations, linearization, or solution methods.
- The goal is not linguistic completeness in general, but a semantically sound specification for later formulation.
- Only treat something as an ambiguity if its interpretation could change the eventual optimization model.

### 1. Validation F: semantic facts
Set `facts_faithful = true` only if:
- F is faithful to the original problem.
- F captures the semantic content that later formulation must preserve:
  - key entities and conditions,
  - objective meaning,
  - constraint requirements,
  - important known quantities and system logic.
- F does not over-interpret the problem by adding unsupported semantics.

Set `facts_faithful = false` if:
- important facts are missing;
- facts are misread;
- unsupported semantics are added.

### 2. Validation A: formulation-relevant ambiguities
Set `ambiguities_relevant = true` only if:
- A includes the under-specified points whose interpretation could change later modeling decisions;
- listed ambiguities are genuinely formulation-relevant;
- items in A do not contradict the original problem or F;
- it is also acceptable for A to be empty if no such ambiguity is needed.
- do not fail it merely because additional minor ambiguities could also be listed.

Set `ambiguities_relevant = false` if:
- A omits an important formulation-relevant ambiguity; or
- A lists issues that are not real semantic ambiguities for modeling, but merely stylistic, trivial, or already determined by the problem.

### 3. Validation R: adopted resolutions
Set `resolutions_consistent = true` only if:
- each important ambiguity in A is resolved clearly;
- each resolution is consistent with the original problem and with F;
- resolutions fix the semantic reading that Stage II should follow;
- resolutions stay at the semantic level and do not jump into mathematical formulation details.

If A is empty, `resolutions_consistent` should normally be true.

Set `resolutions_consistent = false` if:
- a resolution contradicts the problem or F;
- a resolution is too vague to guide formulation;
- a resolution introduces formulation-level content instead of semantic interpretation.

### Output
- `facts_faithful`: true/false
- `ambiguities_relevant`: true/false
- `resolutions_consistent`: true/false
- `feedback`: string | null
  - If any field is false, give 1-3 concise and actionable revision suggestions.
  - If all are true, set `feedback = null`.

Overall pass condition: all three fields are true.

Example (PASS):
{"facts_faithful": true, "ambiguities_relevant": true, "resolutions_consistent": true, "feedback": null}

Example (FAIL):
{"facts_faithful": false, "ambiguities_relevant": true, "resolutions_consistent": true, "feedback": "Missing the core optimization goal in semantic_facts; state explicitly what the problem is trying to optimize."}
"""


async def semantic_validator(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Validation semantic specification and resolutions."""
    current_count = state.get("semantic_validation_count", 0)
    logger.info("🔍 Semantic Validator: Validating (attempt %d)", current_count + 1)

    validation_message = f"""## Original Problem Description
{state.get("problem_description")}

## Semantic Facts Under Validation
{state.get("semantic_facts") or ""}

## Ambiguities Under Validation
{state.get("semantic_ambiguities") or ""}

## Resolutions Under Validation
{state.get("ambiguity_resolutions") or ""}

Please complete the validation based on the content above.
"""

    agent = create_agent(
        model=runtime.context.llm("trival.semantic_validator"),
        tools=[],
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=SEMANTIC_VALIDATOR_SYSTEM_PROMPT,
        response_format=ToolStrategy(SemanticValidationOutput),
        name="semantic_validator",
    )

    result = await agent.ainvoke(
        {**state, "messages": [HumanMessage(content=validation_message)]}, config=config
    )

    structured_response = result["structured_response"]

    all_passed = (
        structured_response.facts_faithful
        and structured_response.ambiguities_relevant
        and structured_response.resolutions_consistent
    )

    if all_passed:
        logger.info("✅ Semantic Validator: PASSED")
    else:
        status_parts = []
        if not structured_response.facts_faithful:
            status_parts.append("facts")
        if not structured_response.ambiguities_relevant:
            status_parts.append("ambiguities")
        if not structured_response.resolutions_consistent:
            status_parts.append("resolutions")
        status_str = ", ".join(status_parts)
        logger.info("❌ Semantic Validator: FAILED (%s)", status_str)

    return {
        "facts_faithful": structured_response.facts_faithful,
        "ambiguities_relevant": structured_response.ambiguities_relevant,
        "resolutions_consistent": structured_response.resolutions_consistent,
        "semantic_validation_feedback": structured_response.feedback,
        "semantic_validation_count": current_count + 1,
    }
