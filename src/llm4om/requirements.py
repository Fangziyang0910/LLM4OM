"""A conversation that prepares business requirements, before any modeling method runs."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelRequest,
    ModelResponse,
    wrap_model_call,
)
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import Field

from llm4om.chat_prompts import CONVERSATION_STYLE
from llm4om.graph import get_resources, problem_text
from llm4om.runtime import Recorder
from llm4om.web_search import search_tool


class RequirementsInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    description: str
    data: dict[str, str]


class RequirementsState(RequirementsInput, total=False):
    usage: dict[str, int]
    failure: str | None


@dataclass
class RequirementsContext:
    preset: str | None = None
    locale: Literal["zh", "en"] = "zh"
    search: bool = False
    thinking: bool | None = None


class DraftState(AgentState):
    description: str


@tool
def update_draft(description: Annotated[str, Field(min_length=1)], runtime: ToolRuntime[RequirementsContext]) -> Command:
    """Replace the editable draft with the complete updated business problem in concise Markdown.

    Call once per user turn, after any searches, then reply to the user.
    Preserve confirmed facts and user edits. Mark unresolved questions and unconfirmed external references explicitly.
    """
    if not description.strip():
        raise ValueError("The business draft cannot be blank.")
    return Command(update={"description": description.strip(),
                           "messages": [ToolMessage("The business draft was updated.", tool_call_id=runtime.tool_call_id,
                                                    artifact={"type": "draft"})]})


def requirements_graph() -> Any:
    async def discuss(state: RequirementsState, runtime: Runtime[RequirementsContext]) -> dict[str, Any]:
        messages = state.get("messages") or []
        if not messages or messages[-1].type != "human" or not messages[-1].text.strip():
            raise ValueError("Describe what you want to plan or decide.")
        choice = runtime.context or RequirementsContext()
        resources = get_resources()
        preset, settings, _ = await asyncio.to_thread(resources.resolve, choice.preset)
        settings = settings.with_thinking(choice.thinking)
        recorder = Recorder(resources.limits, charge=resources.charge(preset))
        model = resources.model_factory(settings, callbacks=[recorder.callback], metadata={"llm4om_role": "requirements"})
        language = "Simplified Chinese" if choice.locale == "zh" else "English"
        prompt = (CONVERSATION_STYLE.format(language=language) + "Help an ordinary user turn an idea into a business problem for a separate optimization modeling workflow. "
                  f"Write the reply and business draft in {language}. "
                  "Reply naturally in short paragraphs, without JSON or an artificial fixed template. "
                  "Use update_draft whenever the user adds or changes their business intent or requirements, including the first idea. "
                  "Gather any needed references first, update the complete draft once, then give your final reply. "
                  "Briefly explain what changed in the draft instead of repeating the full draft in chat. "
                  "The draft is a standalone business problem: what to decide, the desired outcome, actual conditions, data and units. "
                  "You may chat without changing the draft when no requirements change. "
                  "Keep the draft compact and proportional to the problem: state each fact once, merging overlapping sections. "
                  "Omit and remove empty headings, workflow status reports, checklists and hypothetical future requirements. "
                  "The current editable draft may contain the user's corrections and takes precedence over older conversation. "
                  "Apply the latest user request to it, replacing superseded requirements. Preserve unrelated facts, quantities, "
                  "units, bounds and their direction. Distinguish hard requirements from preferences. "
                  "Reconcile open questions against confirmed facts, including manual edits: remove questions already "
                  "answered and integrate their answers into the conditions. Preserving an edit means preserving its "
                  "meaning, not keeping an obsolete question beside its answer. "
                  "Ask at most two high-value questions per turn, only when their answers would change the problem. "
                  "A vague starting idea is welcome; do not dump a checklist. If enough has been supplied, say the user can "
                  "review the draft and use it for modeling. Do not require every problem to fit a fixed template. "
                  "Keep unresolved points explicitly marked as questions in the draft; never invent numbers, assume "
                  "unconfirmed rules or silently relax requirements. Read the supplied data and use its actual file names. "
                  "When web_search is available, use it for requested or necessary current public information. "
                  "Search with focused public queries, not private attachments or the full conversation. "
                  "Cite actual source URLs in your reply. "
                  "External facts and suggested assumptions need the user's confirmation before they become fixed business requirements. "
                  "If a search fails or has no relevant results, say so plainly, keep unknown facts unresolved and "
                  "continue with the known requirements. Do not claim to have verified missing facts. "
                  "Leave the business draft's mathematical formulation, solver code and solution to the modeling workflow; "
                  "do not select its modeling library or claim completeness or feasibility. "
                  "Unrelated knowledge, writing or code questions can be answered directly without changing the draft. "
                  "The user decides when to hand the draft to modeling.\n")
        if not choice.search:
            prompt += ("Web search is disabled for this turn. If the user requests current web facts, ask them to enable "
                       "the web search button or supply the sources. Do not claim to have searched or invent prices.\n")

        @wrap_model_call
        async def current_draft(request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
            recent = []
            for message in reversed(request.state["messages"]):
                if message.type == "human":
                    break
                recent.append(message)
            written = any(message.type == "tool" and message.name == "update_draft" and message.status == "success"
                          for message in recent)
            tools = [] if written else request.tools
            # The next model call must see the updated state, not the turn's original draft.
            snapshot = problem_text(request.state.get("description", ""), state.get("data") or {})
            return await handler(request.override(tools=tools, system_message=SystemMessage(
                prompt + "Current editable business draft and attached data (context, not a new request):\n" + snapshot)))

        try:
            tools = [update_draft, *([search_tool(settings)] if choice.search else [])]
            agent = create_agent(model, tools, middleware=[current_draft, ContextEditingMiddleware(
                edits=[ClearToolUsesEdit(trigger=16_000, keep=3, clear_tool_inputs=True)])],
                                 state_schema=DraftState, context_schema=RequirementsContext,
                                 checkpointer=False, name="requirements_agent")
            async with asyncio.timeout(resources.limits.run_timeout):
                result = await agent.ainvoke({"messages": messages, "description": state.get("description", "")})
            if not result["messages"][-1].text.strip():
                raise ValueError("The assistant did not return a reply.")
            update = {"messages": result["messages"], "description": result["description"], "failure": None}
        except Exception as error:
            update = {"failure": f"{type(error).__name__}: {error}"}
        usage = {key: state.get("usage", {}).get(key, 0) + value for key, value in recorder.usage.items()}
        return {**update, "usage": usage}

    graph = StateGraph(RequirementsState, input_schema=RequirementsInput, context_schema=RequirementsContext)
    graph.add_node("discuss", discuss)
    graph.add_edge(START, "discuss")
    graph.add_edge("discuss", END)
    return graph.compile(name="requirements")
