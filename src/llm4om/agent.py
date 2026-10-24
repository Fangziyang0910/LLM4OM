"""Conversational access to complete modeling workflows and frozen solver results."""

import asyncio
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ClearToolUsesEdit, ContextEditingMiddleware
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph_sdk import get_client

from llm4om.capabilities import assemble_capabilities
from llm4om.capabilities.session import AgentContext as AgentContext
from llm4om.capabilities.session import AgentPlanState, Conversation, ConversationInput, ConversationState
from llm4om.chat_prompts import CONVERSATION_STYLE
from llm4om.graph import get_resources, run
from llm4om.runtime import Recorder


def _conversation_graph(*, optimization: bool) -> Any:
    async def discuss(state: ConversationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
        messages = state.get("messages") or []
        if not messages or messages[-1].type != "human" or not messages[-1].text.strip():
            raise ValueError("Ask about the plan or describe the changes you want to calculate.")
        choice = runtime.context or AgentContext()
        resources = get_resources()
        session = Conversation(state, choice, resources, get_client(url=None), run, optimization=optimization)
        current = state.get("current") or state.get("source")
        original = await session.load(current) if current else {}
        if not optimization and (not original.get("spec") or not original.get("description")):
            raise ValueError("The source must be a saved modeling run.")
        preset, settings, _ = await asyncio.to_thread(resources.resolve, choice.preset or original.get("spec", {}).get("preset"))
        settings = settings.with_thinking(choice.thinking)
        recorder = Recorder(resources.limits, charge=resources.charge(preset))
        kind = "optimization" if optimization else "solution_chat"
        model = resources.model_factory(settings, callbacks=[recorder.callback], metadata={"llm4om_role": kind})
        language = "Simplified Chinese" if choice.locale == "zh" else "English"

        try:
            tools, middleware = assemble_capabilities(session, preset, settings)
            agent = create_agent(model, tools, system_prompt=CONVERSATION_STYLE.format(language=language),
                middleware=[*middleware, ContextEditingMiddleware(
                    edits=[ClearToolUsesEdit(trigger=16_000, keep=3, clear_tool_inputs=True)])],
                state_schema=AgentPlanState, context_schema=AgentContext, checkpointer=False, name=f"{kind}_agent")
            async with asyncio.timeout(resources.limits.run_timeout):
                result = await agent.ainvoke({"messages": messages, "current": current})
            if not result["messages"][-1].text.strip():
                raise ValueError("The assistant did not return a reply.")
            update = {"messages": result["messages"], "current": result["current"], "failure": None}
        except Exception as error:
            advanced = session.completed[0]["source"] if len(session.completed) == 1 and session.pending is None else session.selected_plan
            update = {"current": advanced if advanced and session.cache[(advanced["thread_id"], advanced["checkpoint_id"])].get("spec") else current,
                      "failure": f"{type(error).__name__}: {error}"}
        plans = {item["source"]["thread_id"]: item for item in [*(state.get("plans") or []), *session.completed]}
        usage = {key: state.get("usage", {}).get(key, 0) + value for key, value in recorder.usage.items()}
        first = session.completed[0]["source"] if session.completed else None
        initial = first if first and session.cache[(first["thread_id"], first["checkpoint_id"])].get("spec") else None
        return {**update, "plans": list(plans.values()), "pending": session.pending, "pending_model": session.pending_model,
                **({"source": initial} if not state.get("source") and initial else {}), "usage": usage}

    graph = StateGraph(ConversationState, input_schema=ConversationInput, context_schema=AgentContext)
    graph.add_node("discuss", discuss)
    graph.add_edge(START, "discuss")
    graph.add_edge("discuss", END)
    return graph.compile(name="optimization" if optimization else "solution_chat")


def solution_graph() -> Any:
    return _conversation_graph(optimization=False)


def optimization_graph() -> Any:
    return _conversation_graph(optimization=True)
