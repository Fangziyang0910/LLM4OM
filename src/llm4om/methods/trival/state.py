from langchain.agents import AgentState


class State(AgentState):
    problem: str  # llm4om: the platform's input
    failure: str | None  # llm4om: reported when the graph ends without code
    problem_description: str
    formulation: str
    selected_formulation_expert: str | None

    semantic_facts: str | None
    semantic_ambiguities: str | None
    ambiguity_resolutions: str | None
    facts_faithful: bool | None
    ambiguities_relevant: bool | None
    resolutions_consistent: bool | None
    semantic_validation_feedback: str | None
    semantic_validation_count: int

    constraint_candidate: str | None
    parameter_index_candidate: str | None
    decision_variable_candidate: str | None
    objective_candidate: str | None

    formulation_validation_feedback: str | None
    formulation_validation_passed: bool | None
    formulation_revision_action: str | None
    formulation_validation_count: int

    code: str
    code_executable: bool | None
    execution_feedback: str | None
    code_execution_count: int
    code_validation_count: int
    code_validation_passed: bool | None
    code_validation_feedback: str | None
    error_attribution: str | None
