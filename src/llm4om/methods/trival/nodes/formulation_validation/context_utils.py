from langchain.messages import HumanMessage

from llm4om.methods.trival.state import State


def build_semantic_context(state: State) -> str:
    """Build context from the problem description and semantic specification."""
    return f"""## Original Problem Description
{state.get("problem_description")}

## Semantic Specification
{state.get("semantic_facts", "")}
{state.get("ambiguity_resolutions", "")}
"""


def get_expert_instruction_and_context(state: State) -> HumanMessage:
    """Generate expert task instructions based on the modeling phase."""
    parts = []

    semantic_context = build_semantic_context(state)
    parts.append(semantic_context)

    formulation_validation_feedback = state.get("formulation_validation_feedback", "")
    previous_formulation = state.get("formulation", "")
    has_feedback = bool(formulation_validation_feedback and previous_formulation)

    code_validation_feedback = state.get("code_validation_feedback", "")
    error_attribution = state.get("error_attribution")
    requires_formulation_revision = error_attribution == "formulation"

    if has_feedback or (requires_formulation_revision and code_validation_feedback):
        parts.append(f"""## Previous Formulation
{previous_formulation}""")

        if has_feedback:
            parts.append(f"""## Formulation Validation Feedback
{formulation_validation_feedback}""")

        if requires_formulation_revision and code_validation_feedback:
            parts.append(f"""## Code Validation Feedback (Indicating Formulation Defect)
{code_validation_feedback}""")

        parts.append(
            "Please improve the formulation based on the feedback above and provide a new complete mathematical formulation."
        )
    else:
        parts.append(
            "Please build a complete mathematical formulation based on the original problem and semantic specification."
        )

    return HumanMessage(content="\n\n".join(parts))
