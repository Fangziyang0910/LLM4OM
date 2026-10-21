import logging
from typing import Literal

from pydantic import BaseModel, Field

from llm4om.runtime import Context

logger = logging.getLogger("llm4om.trival")


# The platform's runtime context is the context of every TriVAL graph and agent.
ContextSchema = Context


class FormulationValidationOutput(BaseModel):
    formulation_validation_feedback: str = Field(
        description="Complete validation opinion and reasons, covering the causes for passing/failing and key issues."
    )
    formulation_validation_passed: bool = Field(
        description="True if it passes the validation, False otherwise."
    )
    formulation_revision_action: Literal["partial_revise", "reformulate"] | None = (
        Field(
            default=None,
            description="Given 'partial_revise' or 'reformulate' when formulation_validation_passed is False; None when passed.",
        )
    )


class CodeValidationOutput(BaseModel):
    code_validation_passed: bool = Field(
        description="True if the code passes validation with no changes required."
    )
    code_validation_feedback: str = Field(
        description="If not passed: errors and fix suggestions; if passed: brief validation summary or minor suggestions."
    )
    error_attribution: Literal["code", "formulation"] = Field(
        default="code",
        description="Where you suspect the error originated. 'code' for implementation bugs, 'formulation' for logical issues in the formulation.",
    )


class SemanticValidationOutput(BaseModel):
    """Output from semantic_validator: validation decision for each part."""

    facts_faithful: bool = Field(
        description="True if semantic_facts passes validation: no errors, no omissions, no extras."
    )
    ambiguities_relevant: bool = Field(
        description="True if semantic_ambiguities passes validation: no omissions, no extras. Set to True if no ambiguities exist."
    )
    resolutions_consistent: bool = Field(
        description="True if ambiguity_resolutions passes validation: no omissions, no errors, usable. Set to True if no ambiguities exist."
    )
    feedback: str | None = Field(
        default=None,
        description="Actionable feedback for failed parts (1-3 concise items). Required only when at least one part fails.",
    )


__all__ = [
    "ContextSchema",
    "FormulationValidationOutput",
    "CodeValidationOutput",
    "SemanticValidationOutput",
]
