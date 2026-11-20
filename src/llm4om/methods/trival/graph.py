"""TriVAL workflow: semantic, formulation and code validation on one flat StateGraph."""

import re
from collections.abc import Callable, Sequence
from typing import Any, Literal, TypeVar

from langchain.tools import tool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field, ValidationError

from llm4om.methods import presets
from llm4om.methods.trival import prompts as P
from llm4om.runtime import Context, ModelingState

T = TypeVar("T", bound=BaseModel)

EXPERTS = [
    "parameter_index_expert",
    "constraint_expert",
    "decision_variable_expert",
    "objective_expert",
]


class State(ModelingState, total=False):
    problem_description: str
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

    code_executable: bool | None
    execution_feedback: str | None
    code_execution_count: int
    code_validation_count: int
    code_validation_passed: bool | None
    code_validation_feedback: str | None
    error_attribution: str | None


class SemanticValidationOutput(BaseModel):
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


class FormulationValidationOutput(BaseModel):
    formulation_validation_feedback: str = Field(
        description="Complete validation opinion and reasons, covering the causes for passing/failing and key issues."
    )
    formulation_validation_passed: bool = Field(
        description="True if it passes the validation, False otherwise."
    )
    formulation_revision_action: Literal["partial_revise", "reformulate"] | None = Field(
        default=None,
        description="Given 'partial_revise' or 'reformulate' when formulation_validation_passed is False; None when passed.",
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


def _strip_invalid_calls(reply: AIMessage) -> tuple[AIMessage, list[dict[str, Any]]]:
    """Strip malformed tool calls and raw function_call blocks so Chat Completions, Responses and core stay 1-to-1 paired."""
    invalid = list(getattr(reply, "invalid_tool_calls", None) or [])
    if not invalid:
        return reply, []
    extra = {key: value for key, value in reply.additional_kwargs.items() if key != "tool_calls"}
    content = reply.text or ("" if reply.tool_calls else "[malformed tool call]")
    return reply.model_copy(update={"content": content, "invalid_tool_calls": [], "additional_kwargs": extra}), invalid


async def _run_tools(llm: Any, system_prompt: str, user_content: str, tools: Sequence[BaseTool],
                     *, require_done: Callable[[], bool] | None = None, max_reminders: int = 2) -> None:
    """Execute a tool-calling turn loop sequentially in call order without nested StateGraphs or Command replays."""
    bound = llm.bind_tools(tools)
    by_name = {item.name: item for item in tools}
    messages: list[BaseMessage] = [SystemMessage(system_prompt), HumanMessage(user_content)]
    reminders = 0
    while True:
        reply, invalid = _strip_invalid_calls(await bound.ainvoke(messages))
        if not reply.tool_calls and not invalid:
            if require_done is not None and not require_done() and reminders < max_reminders:
                reminders += 1
                messages.append(reply if reply.text else reply.model_copy(update={"content": "[empty response]"}))
                messages.append(HumanMessage(f"Call one of {list(by_name)} to record your decision."))
                continue
            return
        messages.append(reply)
        for index, call in enumerate(reply.tool_calls):
            call_id = call.get("id") or f"call_{index}"
            selected = by_name.get(call["name"])
            if selected is None:
                output = f"Unknown tool {call['name']!r}; choose from {list(by_name)}."
            else:
                try:
                    output = selected.invoke(call["args"])
                except ValidationError as error:
                    output = f"Invalid arguments: {error}"
            messages.append(ToolMessage(str(output), tool_call_id=call_id, name=call["name"]))
        if invalid:
            errors = "; ".join(str(bad.get("error") or "invalid JSON arguments") for bad in invalid)
            messages.append(HumanMessage(f"Malformed tool call ({errors}). Retry with valid JSON arguments."))


async def _validate(llm: Any, system_prompt: str, user_content: str, schema: type[T]) -> T:
    """Collect a structured validation verdict via its tool schema, with JSON-text fallback when unforced."""
    submit = StructuredTool.from_function(
        lambda **values: values,
        name=schema.__name__,
        args_schema=schema,
        description="Submit the complete validation decision and feedback.",
    )
    bound = llm.bind_tools([submit])
    messages: list[BaseMessage] = [
        SystemMessage(f"{system_prompt}\nSubmit your decision using {schema.__name__}."),
        HumanMessage(user_content),
    ]
    while True:
        reply, invalid = _strip_invalid_calls(await bound.ainvoke(messages))
        if not reply.tool_calls and not invalid:
            cleaned = re.sub(r"^```(?:json)?[ \t]*\r?\n?|\r?\n?```$", "", reply.text.strip(), flags=re.I).strip()
            try:
                return schema.model_validate_json(cleaned)
            except ValidationError:
                messages.append(reply if reply.text else reply.model_copy(update={"content": "[empty response]"}))
                messages.append(HumanMessage(f"Call {schema.__name__} once with a valid validation decision."))
                continue
        messages.append(reply)
        parsed: list[T] = []
        for index, call in enumerate(reply.tool_calls):
            call_id = call.get("id") or f"call_{index}"
            if call["name"] != schema.__name__:
                messages.append(ToolMessage(f"Call {schema.__name__}.", tool_call_id=call_id, name=call["name"]))
                continue
            try:
                parsed.append(schema.model_validate(call["args"]))
                messages.append(ToolMessage(f"Recorded {schema.__name__}.", tool_call_id=call_id, name=call["name"]))
            except ValidationError as error:
                messages.append(ToolMessage(str(error), tool_call_id=call_id, name=call["name"]))
        total_calls = len(reply.tool_calls) + len(invalid)
        if len(parsed) == 1 and total_calls == 1:
            return parsed[0]
        if total_calls > 1 or invalid:
            messages.append(HumanMessage(f"Submit exactly one valid {schema.__name__} decision."))


def _semantic_context(state: State) -> str:
    return (
        f"## Original Problem Description\n{state.get('problem_description') or ''}\n\n"
        f"## Semantic Specification\n{state.get('semantic_facts') or ''}\n{state.get('ambiguity_resolutions') or ''}\n"
    )


def _expert_instruction(state: State) -> str:
    parts = [_semantic_context(state)]
    formulation_feedback = state.get("formulation_validation_feedback", "")
    previous_formulation = state.get("formulation", "")
    has_feedback = bool(formulation_feedback and previous_formulation)
    code_feedback = state.get("code_validation_feedback", "")
    requires_revision = state.get("error_attribution") == "formulation"

    if has_feedback or (requires_revision and code_feedback):
        parts.append(f"## Previous Formulation\n{previous_formulation}")
        if has_feedback:
            parts.append(f"## Formulation Validation Feedback\n{formulation_feedback}")
        if requires_revision and code_feedback:
            parts.append(f"## Code Validation Feedback (Indicating Formulation Defect)\n{code_feedback}")
        parts.append("Please improve the formulation based on the feedback above and provide a new complete mathematical formulation.")
    else:
        parts.append("Please build a complete mathematical formulation based on the original problem and semantic specification.")
    return "\n\n".join(parts)


def _expert_node(name: str, system_prompt: str, field: str) -> Callable[[State, Runtime[Context]], Any]:
    async def run_expert(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
        reply = await runtime.context.llm(f"trival.{name}").ainvoke(
            [SystemMessage(system_prompt), HumanMessage(_expert_instruction(state))]
        )
        return {field: reply.text}

    run_expert.__name__ = name
    return run_expert


parameter_index_expert = _expert_node("parameter_index_expert", P.PARAMETER_INDEX_EXPERT_PROMPT, "parameter_index_candidate")
decision_variable_expert = _expert_node("decision_variable_expert", P.DECISION_VARIABLE_EXPERT_PROMPT, "decision_variable_candidate")
constraint_expert = _expert_node("constraint_expert", P.CONSTRAINT_EXPERT_PROMPT, "constraint_candidate")
objective_expert = _expert_node("objective_expert", P.OBJECTIVE_EXPERT_PROMPT, "objective_candidate")


async def semantic_fact_extractor(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    facts_faithful = state.get("facts_faithful")
    ambiguities_relevant = state.get("ambiguities_relevant")
    feedback = state.get("semantic_validation_feedback")

    draft: dict[str, Any] = {
        "semantic_facts": state.get("semantic_facts"),
        "semantic_ambiguities": None if ambiguities_relevant is False else state.get("semantic_ambiguities"),
        "ambiguity_resolutions": None if ambiguities_relevant is False else state.get("ambiguity_resolutions"),
        "resolutions_consistent": None if ambiguities_relevant is False else state.get("resolutions_consistent"),
    }

    @tool("write_semantic_facts")
    def write_semantic_facts(semantic_facts: str) -> str:
        """Write the generated semantic_facts text to state. Input is the complete Markdown content."""
        draft["semantic_facts"] = semantic_facts
        return "semantic_facts has been written."

    @tool("write_semantic_ambiguities")
    def write_semantic_ambiguities(semantic_ambiguities: str) -> str:
        """Write the generated semantic_ambiguities text to state. Input is the complete Markdown content."""
        if semantic_ambiguities != draft["semantic_ambiguities"] or not semantic_ambiguities.strip():
            draft["ambiguity_resolutions"] = None
            draft["resolutions_consistent"] = None
        draft["semantic_ambiguities"] = semantic_ambiguities
        return "semantic_ambiguities has been written."

    if (facts_faithful is False or ambiguities_relevant is False) and feedback:
        user_content = (
            f"## Original Problem Description\n{state['problem_description']}\n\n"
            f"## Current Semantic Facts\n{state.get('semantic_facts') or '(none)'}\n\n"
            f"## Current Ambiguities\n{state.get('semantic_ambiguities') or '(none)'}\n\n"
            f"## Validation Feedback\n{feedback}\n\n"
            "Revise the current semantic specification to satisfy the validation requirements."
        )
    else:
        user_content = (
            f"## Original Problem Description\n{state['problem_description']}\n\n"
            "Generate semantic specification: extract semantic facts and ambiguities."
        )

    await _run_tools(
        runtime.context.llm("trival.semantic_fact_extractor"),
        P.SEMANTIC_FACT_EXTRACTOR_SYSTEM_PROMPT,
        user_content,
        [write_semantic_facts, write_semantic_ambiguities],
    )
    return draft


async def ambiguity_resolver(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    feedback = state.get("semantic_validation_feedback")
    validation_section = f"\n\n## Validation Feedback\n{feedback}\n" if feedback else ""
    user_content = (
        f"## Original Problem Description\n{state.get('problem_description')}\n\n"
        f"## Extracted Semantic Facts\n{state.get('semantic_facts') or ''}\n\n"
        f"## Identified Ambiguities\n{state.get('semantic_ambiguities') or ''}"
        f"{validation_section}\n"
        "Complete semantic ambiguity resolution based on the above materials."
    )
    reply = await runtime.context.llm("trival.ambiguity_resolver").ainvoke(
        [SystemMessage(P.AMBIGUITY_RESOLVER_SYSTEM_PROMPT), HumanMessage(user_content)]
    )
    return {"ambiguity_resolutions": reply.text}


async def semantic_validator(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    user_content = (
        f"## Original Problem Description\n{state.get('problem_description')}\n\n"
        f"## Semantic Facts Under Validation\n{state.get('semantic_facts') or ''}\n\n"
        f"## Ambiguities Under Validation\n{state.get('semantic_ambiguities') or ''}\n\n"
        f"## Resolutions Under Validation\n{state.get('ambiguity_resolutions') or ''}\n\n"
        "Please complete the validation based on the content above."
    )
    verdict = await _validate(
        runtime.context.llm("trival.semantic_validator"),
        P.SEMANTIC_VALIDATOR_SYSTEM_PROMPT,
        user_content,
        SemanticValidationOutput,
    )
    return {
        "facts_faithful": verdict.facts_faithful,
        "ambiguities_relevant": verdict.ambiguities_relevant,
        "resolutions_consistent": verdict.resolutions_consistent,
        "semantic_validation_feedback": verdict.feedback,
        "semantic_validation_count": state.get("semantic_validation_count", 0) + 1,
    }


async def formulation_selector(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    candidates = {
        "parameter_index_expert": state.get("parameter_index_candidate") or "",
        "constraint_expert": state.get("constraint_candidate") or "",
        "decision_variable_expert": state.get("decision_variable_candidate") or "",
        "objective_expert": state.get("objective_candidate") or "",
    }
    chosen: dict[str, Any] = {
        "formulation": "",
        "selected_formulation_expert": None,
    }

    @tool("select_formulation")
    def select_formulation(expert_name: str) -> str:
        """Select the highest-quality expert candidate and copy it to formulation.

        Args:
            expert_name: The expert name to select. Valid options: parameter_index_expert, constraint_expert, decision_variable_expert, objective_expert
        """
        candidate = candidates.get(expert_name, "")
        if not candidate:
            return (
                f"Error: Expert name '{expert_name}' is incorrect or this expert has no output. "
                "Valid expert names are: parameter_index_expert, constraint_expert, decision_variable_expert, objective_expert."
            )
        chosen["formulation"] = candidate
        chosen["selected_formulation_expert"] = expert_name
        return f"Selected {expert_name}'s candidate as the highest quality formulation."

    user_content = (
        f"{_semantic_context(state)}\n\n"
        f"## Parameter-and-index Expert Candidate:\n{candidates['parameter_index_expert']}\n\n"
        f"## Constraint Expert Candidate:\n{candidates['constraint_expert']}\n\n"
        f"## Decision-variable Expert Candidate:\n{candidates['decision_variable_expert']}\n\n"
        f"## Objective Expert Candidate:\n{candidates['objective_expert']}\n\n"
        "Analyze these candidates thoroughly and select the highest-quality one using the select_formulation tool."
    )
    await _run_tools(
        runtime.context.llm("trival.formulation_selector"),
        P.FORMULATION_SELECTOR_SYSTEM_PROMPT,
        user_content,
        [select_formulation],
        require_done=lambda: bool(chosen["formulation"].strip()),
    )
    if not chosen["formulation"].strip():
        for name, candidate in candidates.items():
            if candidate.strip():
                chosen["formulation"] = candidate
                chosen["selected_formulation_expert"] = name
                break
    return chosen


async def formulation_validator(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    user_content = f"{_semantic_context(state)}\n\n## Selected Formulation\n{state.get('formulation', '')}\n"
    verdict = await _validate(
        runtime.context.llm("trival.formulation_validator"),
        P.FORMULATION_VALIDATOR_SYSTEM_PROMPT,
        user_content,
        FormulationValidationOutput,
    )
    return {
        "formulation_validation_feedback": verdict.formulation_validation_feedback,
        "formulation_validation_passed": verdict.formulation_validation_passed,
        "formulation_revision_action": verdict.formulation_revision_action,
        "formulation_validation_count": state.get("formulation_validation_count", 0) + 1,
    }


async def revise_formulation(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    revised = {"formulation": state.get("formulation", "")}

    @tool("write_formulation")
    def write_formulation(formulation: str) -> str:
        """Write the corrected formulation after minimal fixes."""
        revised["formulation"] = formulation
        return "Fixed formulation has been written."

    parts = [_semantic_context(state), f"## Selected Formulation\n{state.get('formulation') or ''}"]
    if state.get("formulation_validation_passed") is False and (feedback := state.get("formulation_validation_feedback")):
        parts.append(f"## Formulation Validation Feedback\n{feedback}")
    if state.get("error_attribution") == "formulation" and (code_feedback := state.get("code_validation_feedback")):
        parts.append(f"## Code Validation Feedback (Reason for Formulation Revision)\n{code_feedback}")

    await _run_tools(
        runtime.context.llm("trival.revise_formulation"),
        P.FORMULATION_REVISION_SYSTEM_PROMPT,
        "\n\n".join(parts),
        [write_formulation],
    )
    return {
        "formulation": revised["formulation"],
        "code": None,
        "error_attribution": None,
        "code_validation_passed": None,
        "code_validation_feedback": None,
        "code_executable": None,
        "execution_feedback": None,
    }


async def code_agent(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    buf = {"code": state.get("code")}

    @tool("write_code")
    def write_code(code: str) -> str:
        """Overwrite the entire code in state with new code.

        Use this for: initial code generation or major rewrites (>50% changes).

        Args:
            code: Complete Python code to write
        """
        buf["code"] = code
        line_count = len(code.strip().split("\n")) if code else 0
        return f"<result>Code written: {line_count} lines</result>"

    @tool("edit_code")
    def edit_code(search: str, replace: str) -> str:
        """Replace a code fragment with new content.

        Use this for: bug fixes, small changes, parameter adjustments.
        Critical: The search fragment must be UNIQUE in current code. Include 3-5 surrounding lines for context.
        """
        current = buf["code"]
        if current is None:
            return "<error>Code is empty. Use write_code() first.</error>"
        occurrences = current.count(search)
        if occurrences == 0:
            return "<error>Search fragment not found.\nFix: Use read_code() to check current code, ensure exact match including indentation.</error>"
        if occurrences > 1:
            return "<error>Search fragment appears multiple times.\nFix: Include more surrounding lines to make it unique.</error>"
        buf["code"] = current.replace(search, replace, 1)
        old_lines = len(search.strip().split("\n") if search else [])
        new_lines = len(replace.strip().split("\n") if replace else [])
        return f"<result>Replaced {old_lines} lines with {new_lines} lines</result>"

    @tool("read_code")
    def read_code() -> str:
        """Read the current code from state."""
        current = buf["code"]
        if not current:
            return "<result>No code in state. Use write_code() first.</result>"
        line_count = len(current.strip().split("\n"))
        return f"<code lines={line_count}>\n{current}\n</code>"

    content = (
        f"## Original Problem Description\n{state.get('problem_description')}\n\n"
        f"## Mathematical Formulation\n{state.get('formulation', '')}\n\n"
        "The mathematical formulation above expresses the problem at the mathematical layer, for your reference when writing code.\n"
    )
    if state.get("code_validation_passed") is False and state.get("code_validation_feedback") and state.get("code_executable") is not False:
        content += (
            f"## Current Code\n{state.get('code') or ''}\n\n"
            f"## Validation Feedback\n{state['code_validation_feedback']}\n\n"
            "Please fix the code based on the validation feedback above.\n"
        )
    elif state.get("code_executable") is False and state.get("execution_feedback"):
        content += (
            f"## Current Code\n{state.get('code') or ''}\n\n"
            f"## Execution Error\n{state['execution_feedback']}\n\n"
            "Please fix the code based on the error information above.\n"
        )
    else:
        content += "\nPlease generate the complete optimization solver code based on the mathematical formulation above."

    await _run_tools(
        runtime.context.llm("trival.code_agent"),
        P.CODE_AGENT_SYSTEM_PROMPT + "\n\n" + runtime.context.target.prompt,
        content,
        [write_code, edit_code, read_code],
    )
    code = buf["code"]
    return {
        "code": code,
        "failure": None if code else state.get("failure"),
        "code_validation_passed": None,
        "code_validation_feedback": None,
    }


async def code_executor(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    code = state.get("code") or ""
    count = state.get("code_execution_count", 0)
    if not code:
        return {
            "code_executable": False,
            "execution_feedback": "[Code Executor] state.code is empty, no code executed.",
            "code_execution_count": count + 1,
        }
    result = await runtime.context.solve(code, title=f"执行代码（第 {count + 1} 次）")
    return {
        "code_executable": result.executed,
        "execution_feedback": result.feedback(),
        "code_execution_count": count + 1,
    }


async def code_validator(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    user_content = (
        f"## Original Problem Description\n{state.get('problem_description')}\n\n\n"
        f"## Mathematical Formulation\n{state.get('formulation', '')}\n\n"
        f"## Code\n{state.get('code', '')}\n\n"
        f"## Execution Output\n{state.get('execution_feedback', '')}\n\n"
        "Please complete the validation based on the content above."
    )
    verdict = await _validate(
        runtime.context.llm("trival.code_validator"),
        P.CODE_VALIDATOR_SYSTEM_PROMPT,
        user_content,
        CodeValidationOutput,
    )
    return {
        "code_validation_passed": verdict.code_validation_passed,
        "code_validation_feedback": verdict.code_validation_feedback,
        "code_validation_count": state.get("code_validation_count", 0) + 1,
        "error_attribution": verdict.error_attribution,
    }


def receive_problem(state: State) -> dict[str, Any]:
    return {
        "problem_description": state["problem"],
        "code_execution_count": 0,
        "code_validation_count": 0,
        "failure": None,
    }


def finish(state: State) -> dict[str, Any]:
    if not state.get("code"):
        detail = state.get("execution_feedback") or "TriVAL finished without generating code."
        return {"failure": detail}
    code_feedback = (state.get("code_validation_feedback")
                     or (state.get("execution_feedback") if state.get("code_executable") is False else None))
    checks = (
        ("semantic", all(state.get(key) for key in ("facts_faithful", "ambiguities_relevant", "resolutions_consistent")),
         state.get("semantic_validation_feedback")),
        ("formulation", state.get("formulation_validation_passed"), state.get("formulation_validation_feedback")),
        ("code", state.get("code_validation_passed"), code_feedback),
    )
    unresolved = [f"{stage}: {feedback or 'validation did not pass'}" for stage, passed, feedback in checks if not passed]
    return {"failure": "TriVAL ended with unresolved validation: " + "; ".join(unresolved) if unresolved else None}


def _after_semantic_extraction(state: State) -> str:
    ambiguities = (state.get("semantic_ambiguities") or "").strip()
    if not ambiguities or ambiguities in ("(None)", "none", "None") or ambiguities.lower() == "none":
        return "semantic_validator"
    is_retry = any(state.get(key) is not None for key in ("facts_faithful", "ambiguities_relevant", "resolutions_consistent"))
    if is_retry and state.get("facts_faithful") is False and state.get("ambiguities_relevant") is True and state.get("resolutions_consistent") is True:
        return "semantic_validator"
    return "ambiguity_resolver"


def _after_semantic_validation(state: State) -> str | list[str]:
    if state.get("semantic_validation_count", 0) >= presets.TRIVAL.max_validations:
        return EXPERTS
    if state.get("facts_faithful") and state.get("ambiguities_relevant") and state.get("resolutions_consistent"):
        return EXPERTS
    if state.get("facts_faithful") is False or state.get("ambiguities_relevant") is False:
        return "semantic_fact_extractor"
    if state.get("resolutions_consistent") is False:
        return "ambiguity_resolver"
    return "semantic_fact_extractor"


def _after_formulation_selector(state: State) -> str | list[str]:
    return "formulation_validator" if (state.get("formulation") or "").strip() else EXPERTS


def _after_formulation_validation(state: State) -> str | list[str]:
    if state.get("formulation_validation_count", 0) >= presets.TRIVAL.max_validations or state.get("formulation_validation_passed"):
        return "code_agent"
    if (state.get("formulation_revision_action") or "").strip().lower() == "partial_revise":
        return "revise_formulation"
    return EXPERTS


def _after_code_execution(state: State) -> str:
    if state.get("code_executable"):
        return "code_validator"
    return "finish" if state.get("code_execution_count", 0) >= presets.TRIVAL.max_code_executions else "code_agent"


def _after_code_validation(state: State) -> str:
    if (state.get("code_validation_passed")
            or state.get("code_execution_count", 0) >= presets.TRIVAL.max_code_executions
            or state.get("code_validation_count", 0) >= presets.TRIVAL.max_validations):
        return "finish"
    return "revise_formulation" if state.get("error_attribution") == "formulation" else "code_agent"


def create_trival_graph() -> Any:
    graph = StateGraph(State, context_schema=Context)
    for node in (
        receive_problem,
        semantic_fact_extractor,
        ambiguity_resolver,
        semantic_validator,
        parameter_index_expert,
        constraint_expert,
        decision_variable_expert,
        objective_expert,
        formulation_selector,
        formulation_validator,
        revise_formulation,
        code_agent,
        code_executor,
        code_validator,
        finish,
    ):
        graph.add_node(node.__name__, node)

    graph.add_edge(START, "receive_problem")
    graph.add_edge("receive_problem", "semantic_fact_extractor")
    graph.add_conditional_edges("semantic_fact_extractor", _after_semantic_extraction, ["semantic_validator", "ambiguity_resolver"])
    graph.add_edge("ambiguity_resolver", "semantic_validator")
    graph.add_conditional_edges("semantic_validator", _after_semantic_validation, ["semantic_fact_extractor", "ambiguity_resolver", *EXPERTS])
    for expert in EXPERTS:
        graph.add_edge(expert, "formulation_selector")
    graph.add_conditional_edges("formulation_selector", _after_formulation_selector, ["formulation_validator", *EXPERTS])
    graph.add_conditional_edges("formulation_validator", _after_formulation_validation, ["code_agent", "revise_formulation", *EXPERTS])
    graph.add_edge("revise_formulation", "formulation_validator")
    graph.add_edge("code_agent", "code_executor")
    graph.add_conditional_edges("code_executor", _after_code_execution, ["code_validator", "code_agent", "finish"])
    graph.add_conditional_edges("code_validator", _after_code_validation, ["revise_formulation", "code_agent", "finish"])
    graph.add_edge("finish", END)
    return graph.compile(name="trival")
