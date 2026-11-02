"""First modeling runs and capability discovery through the existing platform graphs."""

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
    wrap_model_call,
    wrap_tool_call,
)
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.types import Command

from llm4om.languages import LANGUAGES
from llm4om.methods import methods
from llm4om.problem import problem_text, validate_description

from .session import AgentContext, Conversation, PlanRun, plan_result

OPTIMIZATION_TOOLS = """You are LLM4OM's conversational assistant. Your specialty is turning optimization questions into real plans,
and you can also help with ordinary conversation and related tasks. Let the user steer the conversation.
Explain or help edit code when asked; use the modeling tools when the user wants the platform to actually solve an optimization problem.
For a first calculation, a different problem, updated attachments or a different method/library, use model_and_solve with
the complete standalone business problem and actual file names. Defaults are Direct, Pyomo and automatic backend selection.
Use solve_scenarios for changes to an existing plan with unchanged configuration and data.
Use modeling_capabilities before selecting a non-default method, modeling library or explicit backend; honor linear_only scope.
Follow explicit user choices; pinned configuration takes priority over tool arguments. Users need not configure technical details.
Never invent missing quantities or business rules. Apply the user's latest corrections and remove superseded requirements.
When search is available, use focused public queries for requested or necessary current information, without private attachments.
Cite actual source URLs. Keep reference information distinct from confirmed requirements; use suggested assumptions when the user
authorizes them, otherwise clarify the assumption before calculation. Do not claim to have searched when search is disabled.
"""


def modeling(session: Conversation, preset: str | None) -> list[AgentMiddleware]:
    @tool
    async def modeling_capabilities() -> dict[str, Any]:
        """Read registered methods, problem scopes, modeling libraries and actual solver-backend availability.

        Consult this before choosing a non-default method, library or explicit backend. A library is not a backend.
        """
        return {"methods": [{"id": item.id, "name": item.name, "description": item.description,
            "linear_only": item.linear_only, "languages": sorted(item.languages) if item.languages is not None else None}
            for item in methods().values()],
            "libraries": [{"id": key, "name": item.name} for key, item in LANGUAGES.items()],
            "backends": await session.resources.sandbox.catalog()}

    @tool
    async def model_and_solve(description: str, name: str, runtime: ToolRuntime[AgentContext],
                              method: str | None = None, language: str | None = None,
                              solver: str | None = None) -> Command:
        """Model and actually solve a complete optimization problem through an existing method workflow.

        Supply the standalone business problem, preserving the user's facts and attached file names.
        Use this for the first calculation, a different problem, changed data, or a different method/library.
        Attached data comes from this conversation. Defaults are Direct, Pyomo and automatic backend.
        Do not call for ordinary conversation or when a missing business condition changes the answer.
        """
        validate_description(description)
        if not name.strip():
            raise ValueError("Supply a short name for this plan.")
        request = session.pending_model or {"turn_id": session.messages[-1].id, "description": description.strip(), "name": name.strip(),
            "method": session.choice.method or method or "direct", "language": session.choice.language or language or "pyomo",
            "solver": session.choice.solver or solver, "preset": preset, "data": session.state.get("data") or {}}
        selected = next((item for item in methods().values()
                         if request["method"].strip().casefold() in (item.id, item.name.casefold())), None)
        if selected is None:
            raise ValueError("Choose a registered method from modeling_capabilities.")
        library = next((item.id for item in LANGUAGES.values()
                        if request["language"].strip().casefold() in (item.id, item.name.casefold())), request["language"])
        target = selected.code_target(library, request["solver"])
        request = {**request, "method": selected.id, "language": target.language}
        session.pending_model = request
        identity = json.dumps(request, sort_keys=True, ensure_ascii=False)
        identifier = str(uuid5(NAMESPACE_URL, f"{runtime.config['configurable']['thread_id']}:{identity}"))

        def progress(step: dict[str, Any]) -> None:
            session.stream_step(step, runtime, request["name"], request["method"], request["language"])

        async def run_plan() -> PlanRun:
            calculated = await session.execute(request["description"], method=request["method"], language=request["language"],
                solver=request["solver"], preset=request["preset"], data=request["data"],
                explain=True, locale=session.choice.locale, resources=session.resources, on_step=progress)
            spec = calculated.get("spec") or {}
            return PlanRun(request["method"], {
                "title": request["name"], "method": request["method"], "language": request["language"],
                "solver": request["solver"], "preset": request["preset"],
                "provider": spec.get("llm", {}).get("provider"),
                "model": spec.get("preset_name") or spec.get("llm", {}).get("model"),
                "origin": runtime.config["configurable"]["thread_id"],
                "conversation": runtime.config["configurable"]["thread_id"],
            }, calculated)

        plan, result = await session.save_plan(identifier, {"name": request["name"], "instruction": request["description"],
            "group": None, "turn_id": session.messages[-1].id}, run=run_plan)
        session.pending_model = None
        facts = {**plan_result(plan, result), "method": request["method"], "language": request["language"]}
        return Command(update={**({"current": plan["source"]} if result.get("spec") else {}),
            "messages": [ToolMessage(json.dumps(facts, ensure_ascii=False), tool_call_id=runtime.tool_call_id,
                name="model_and_solve", artifact={"type": "plans", "plans": [facts]})]})

    @wrap_model_call(tools=[model_and_solve, modeling_capabilities])
    async def modeling_context(request: ModelRequest,
                               handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
        tools = [item for item in request.tools if item.name != "model_and_solve" or not session.change_complete]
        prompt = (OPTIMIZATION_TOOLS
            + ("Web search is enabled.\n" if session.choice.search else "Web search is disabled.\n")
            + "Current editable problem and attachments:\n"
            + problem_text(session.state.get("description") or "", session.state.get("data") or {})
            + "\nPinned configuration:\n"
            + json.dumps({"method": session.choice.method, "language": session.choice.language, "solver": session.choice.solver}))
        return await handler(request.override(tools=tools, system_message=SystemMessage(prompt + "\n" + request.system_message.text)))

    @wrap_tool_call
    async def modeling_changes(request: ToolCallRequest,
                               handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        if request.tool_call["name"] == "model_and_solve":
            return await session.change_plan(request, handler)
        return await handler(request)

    return [modeling_context, modeling_changes]
