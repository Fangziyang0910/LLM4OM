from langgraph.graph import END, START, StateGraph

from llm4om.methods import presets
from llm4om.methods.trival.nodes.semantic_validation import (
    ambiguity_resolver,
    semantic_fact_extractor,
    semantic_validator,
)
from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

from .nodes import (
    code_agent,
    code_executor,
    code_validator,
)
from .nodes.formulation_validation import (
    constraint_expert,
    decision_variable_expert,
    formulation_selector,
    formulation_validator,
    objective_expert,
    parameter_index_expert,
    revise_formulation,
)


def route_after_formulation_selector(state: State) -> str | list[str]:
    formulation = state.get("formulation", "")
    if formulation and formulation.strip():
        return "formulation_validator"
    return [
        "parameter_index_expert",
        "constraint_expert",
        "decision_variable_expert",
        "objective_expert",
    ]


def route_formulation_validation(state: State) -> str | list[str]:
    formulation_validation_count = state.get("formulation_validation_count", 0)
    if formulation_validation_count >= presets.TRIVAL.max_validations:
        logger.warning(
            "⚠️ Formulation validation reached its limit (%d); ending this stage",
            formulation_validation_count,
        )
        return END

    if state.get("formulation_validation_passed"):
        return END

    action = (state.get("formulation_revision_action") or "").strip().lower()
    if action == "partial_revise":
        return "revise_formulation"
    return [
        "parameter_index_expert",
        "constraint_expert",
        "decision_variable_expert",
        "objective_expert",
    ]


def route_after_code_execution(state: State) -> str | list[str]:
    if state.get("code_executable"):
        return "code_validator"
    if state.get("code_execution_count", 0) >= presets.TRIVAL.max_code_executions:
        return END
    return "code_agent"


def route_code_validation(state: State) -> str | list[str]:
    code_validation_count = state.get("code_validation_count", 0)

    if state.get("code_validation_passed"):
        return END

    if state.get("error_attribution") == "formulation":
        return END

    if state.get("code_execution_count", 0) >= presets.TRIVAL.max_code_executions:
        return END

    if code_validation_count >= presets.TRIVAL.max_validations:
        logger.warning(
            "⚠️ Code validation reached maximum attempts (%d), forcing exit",
            code_validation_count,
        )
        return END

    return "code_agent"


def route_after_semantic_extraction(state: State) -> str:
    ambiguities = state.get("semantic_ambiguities")

    facts_faithful = state.get("facts_faithful")
    ambiguities_relevant = state.get("ambiguities_relevant")
    resolutions_consistent = state.get("resolutions_consistent")
    is_retry = (
        facts_faithful is not None
        or ambiguities_relevant is not None
        or resolutions_consistent is not None
    )

    is_ambiguities_empty = (
        not ambiguities
        or ambiguities.strip() == ""
        or ambiguities.strip() == "(None)"
        or ambiguities.strip().lower() == "none"
    )

    if is_ambiguities_empty:
        return "semantic_validator"

    if (
        is_retry
        and facts_faithful is False
        and ambiguities_relevant is True
        and resolutions_consistent is True
    ):
        return "semantic_validator"

    return "ambiguity_resolver"


def route_semantic_validation(state: State) -> str | list[str]:
    semantic_validation_count = state.get("semantic_validation_count", 0)

    if semantic_validation_count >= presets.TRIVAL.max_validations:
        logger.warning(
            "⚠️ Semantic validation reached its limit (%d); ending this stage",
            semantic_validation_count,
        )
        return END

    facts_faithful = state.get("facts_faithful")
    ambiguities_relevant = state.get("ambiguities_relevant")
    resolutions_consistent = state.get("resolutions_consistent")

    if facts_faithful and ambiguities_relevant and resolutions_consistent:
        return END

    facts_or_ambiguities_failed = (facts_faithful is False) or (
        ambiguities_relevant is False
    )
    if facts_or_ambiguities_failed:
        return "semantic_fact_extractor"

    if resolutions_consistent is False:
        return "ambiguity_resolver"

    return "semantic_fact_extractor"


def route_start_formulation_validation(state: State) -> str | list[str]:
    """Determine where to start in the formulation subgraph."""
    if state.get("error_attribution") == "formulation":
        logger.info(
            "🩺 Entering Formulation Validation for partial formulation revision"
        )
        return "revise_formulation"

    return [
        "parameter_index_expert",
        "constraint_expert",
        "decision_variable_expert",
        "objective_expert",
    ]


def create_semantic_validation_subgraph():
    """Build fact extraction, ambiguity resolution, and semantic validation."""
    graph = StateGraph(State, context_schema=ContextSchema)

    graph.add_node("semantic_fact_extractor", semantic_fact_extractor)
    graph.add_node("ambiguity_resolver", ambiguity_resolver)
    graph.add_node("semantic_validator", semantic_validator)

    graph.add_edge(START, "semantic_fact_extractor")

    graph.add_conditional_edges(
        "semantic_fact_extractor", route_after_semantic_extraction
    )

    graph.add_edge("ambiguity_resolver", "semantic_validator")

    graph.add_conditional_edges(
        "semantic_validator",
        route_semantic_validation,
        {
            "semantic_fact_extractor": "semantic_fact_extractor",
            "ambiguity_resolver": "ambiguity_resolver",
            END: END,
        },
    )

    return graph.compile(name="semantic_validation")


def create_formulation_validation_subgraph():
    """Build parallel formulation candidates, selection, and formulation validation."""
    graph = StateGraph(State, context_schema=ContextSchema)

    graph.add_node("parameter_index_expert", parameter_index_expert)
    graph.add_node("constraint_expert", constraint_expert)
    graph.add_node("decision_variable_expert", decision_variable_expert)
    graph.add_node("objective_expert", objective_expert)
    graph.add_node("formulation_selector", formulation_selector)
    graph.add_node("formulation_validator", formulation_validator)
    graph.add_node("revise_formulation", revise_formulation)

    graph.add_conditional_edges(START, route_start_formulation_validation)

    graph.add_edge("parameter_index_expert", "formulation_selector")
    graph.add_edge("constraint_expert", "formulation_selector")
    graph.add_edge("decision_variable_expert", "formulation_selector")
    graph.add_edge("objective_expert", "formulation_selector")

    graph.add_conditional_edges(
        "formulation_selector",
        route_after_formulation_selector,
        {
            "formulation_validator": "formulation_validator",
            "parameter_index_expert": "parameter_index_expert",
            "constraint_expert": "constraint_expert",
            "decision_variable_expert": "decision_variable_expert",
            "objective_expert": "objective_expert",
        },
    )
    graph.add_conditional_edges(
        "formulation_validator",
        route_formulation_validation,
        {
            "revise_formulation": "revise_formulation",
            "parameter_index_expert": "parameter_index_expert",
            "constraint_expert": "constraint_expert",
            "decision_variable_expert": "decision_variable_expert",
            "objective_expert": "objective_expert",
            END: END,
        },
    )
    graph.add_edge("revise_formulation", "formulation_validator")

    return graph.compile(name="formulation_validation")


def create_code_validation_subgraph():
    """Build code generation, execution feedback, and code validation."""
    graph = StateGraph(State, context_schema=ContextSchema)

    graph.add_node("code_agent", code_agent)
    graph.add_node("code_executor", code_executor)
    graph.add_node("code_validator", code_validator)

    graph.add_edge(START, "code_agent")
    graph.add_edge("code_agent", "code_executor")
    graph.add_conditional_edges(
        "code_executor",
        route_after_code_execution,
        {"code_validator": "code_validator", "code_agent": "code_agent", END: END},
    )
    graph.add_conditional_edges(
        "code_validator", route_code_validation, {"code_agent": "code_agent", END: END}
    )

    return graph.compile(name="code_validation")


def route_after_code_validation(state: State) -> str:
    """Route formulation defects back to Formulation Validation."""
    if state.get("code_validation_count", 0) >= presets.TRIVAL.max_validations:
        logger.warning(
            "⚠️ Code validation reached maximum attempts (%d), stopping workflow",
            state.get("code_validation_count", 0),
        )
        return END
    if state.get("code_validation_passed"):
        return END

    if state.get("code_execution_count", 0) >= presets.TRIVAL.max_code_executions:
        return END

    if state.get("error_attribution") == "formulation":
        logger.info(
            "🔄 Routing back to Formulation Validation for partial formulation revision"
        )
        return "formulation_validation"

    return END


def route_after_semantic_validation(state: State) -> str:
    """Routing after semantic specification stage: check if it passed before moving to formulation."""
    if state.get("semantic_validation_count", 0) >= presets.TRIVAL.max_validations:
        logger.warning(
            "⚠️ Semantic validation reached maximum attempts (%d), forcing exit to formulation",
            state.get("semantic_validation_count", 0),
        )
        return "formulation_validation"
    if (
        state.get("facts_faithful")
        and state.get("ambiguities_relevant")
        and state.get("resolutions_consistent")
    ):
        return "formulation_validation"
    logger.error(
        "🛑 Semantic Specification stage failed to reach a valid state. Stopping."
    )
    return END


def route_after_formulation_validation(state: State) -> str:
    """Routing after formulation stage: check if it passed before moving to Code."""
    if state.get("formulation_validation_count", 0) >= presets.TRIVAL.max_validations:
        logger.warning(
            "⚠️ Formulation validation reached maximum attempts (%d), moving to Code Validation",
            state.get("formulation_validation_count", 0),
        )
        return "code_validation"
    if state.get("formulation_validation_passed"):
        return "code_validation"
    logger.error(
        "🛑 Formulation Validation failed to produce a valid formulation. Stopping."
    )
    return END


def receive_problem(state: State) -> dict:
    """llm4om: the platform passes `problem`; TriVAL starts from `problem_description` with zero counters."""
    return {
        "problem_description": state["problem"],
        "code_execution_count": 0,
        "code_validation_count": 0,
        "failure": "TriVAL stopped before code generation: the semantic or formulation stage did not pass.",
    }


def create_trival_graph():
    """Build semantic, formulation, and code stages with feedback routing."""
    semantic_validation = create_semantic_validation_subgraph()
    formulation_validation = create_formulation_validation_subgraph()
    code_validation = create_code_validation_subgraph()

    graph = StateGraph(State, context_schema=ContextSchema)

    graph.add_node("receive_problem", receive_problem)
    graph.add_node("semantic_validation", semantic_validation)
    graph.add_node("formulation_validation", formulation_validation)
    graph.add_node("code_validation", code_validation)

    graph.add_edge(START, "receive_problem")
    graph.add_edge("receive_problem", "semantic_validation")
    graph.add_conditional_edges(
        "semantic_validation",
        route_after_semantic_validation,
        {"formulation_validation": "formulation_validation", END: END},
    )
    graph.add_conditional_edges(
        "formulation_validation",
        route_after_formulation_validation,
        {"code_validation": "code_validation", END: END},
    )
    graph.add_conditional_edges(
        "code_validation",
        route_after_code_validation,
        {"formulation_validation": "formulation_validation", END: END},
    )

    return graph.compile(name="trival")
