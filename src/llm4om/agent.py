"""Conversational access to complete modeling workflows and frozen solver results."""

import ast
import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from itertools import islice
from typing import Annotated, Any, Literal, TypedDict
from uuid import NAMESPACE_URL, uuid5

from httpx import HTTPStatusError
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
    wrap_model_call,
    wrap_tool_call,
)
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.runtime import Runtime
from langgraph.types import Command
from langgraph_sdk import get_client
from pydantic import BaseModel, ConfigDict, Field
from simpleeval import InvalidExpression, simple_eval

from llm4om.chat_prompts import CONVERSATION_STYLE, OPTIMIZATION_TOOLS, PLAN_TOOLS
from llm4om.graph import get_resources, problem_text, run
from llm4om.languages import LANGUAGES, CodeTarget
from llm4om.methods import methods
from llm4om.runtime import Recorder
from llm4om.web_search import search_tool

CALCULATION_TOOLS = {"model_and_solve", "solve_scenarios"}
PLAN_CHANGE_TOOLS = CALCULATION_TOOLS | {"select_plan"}
PLAN_READ_TOOLS = {"lookup_variables", "select_plan"}
READ_TOOLS = PLAN_READ_TOOLS | {"calculate"}


class SourceRun(TypedDict):
    thread_id: str
    checkpoint_id: str


class Plan(TypedDict):
    name: str
    instruction: str
    source: SourceRun
    group: str | None
    turn_id: str


class PendingBatch(TypedDict):
    base: SourceRun
    scenarios: list[dict[str, str]]
    turn_id: str


class ConversationInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    source: SourceRun
    description: str
    data: dict[str, str]


class ConversationState(ConversationInput, total=False):
    current: SourceRun | None
    plans: list[Plan]
    usage: dict[str, int]
    failure: str | None
    pending: PendingBatch | None
    pending_model: dict[str, Any] | None


@dataclass
class AgentContext:
    preset: str | None = None
    locale: Literal["zh", "en"] = "zh"
    search: bool = False
    method: str | None = None
    language: str | None = None
    solver: str | None = None
    thinking: bool | None = None


class AgentPlanState(AgentState):
    current: SourceRun | None


class Scenario(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100, description="A short business name for this scenario")
    instruction: str = Field(min_length=1, description="The user's complete, explicit changes; preserve all other requirements")


def configuration(values: dict[str, Any]) -> dict[str, Any]:
    spec = values.get("spec") or {}
    return {key: spec.get(key) for key in ("method", "language", "solver", "preset_name")} | {
        "actual_solver": (values.get("solve") or {}).get("solver"),
        "model": spec.get("llm", {}).get("model"),
    }


def plan_result(plan: Plan, values: dict[str, Any]) -> dict[str, Any]:
    solved = values.get("solve") or {}
    variables = solved.get("variables") or {}
    return {**plan, "description": values["description"], "configuration": configuration(values),
            "status": solved.get("status"), "objective": solved.get("objective"),
            "variables": dict(islice(variables.items(), 100)), "total_variables": len(variables),
            "failure": values.get("failure"), "explanation": values.get("explanation"),
            "infeasibility": values.get("infeasibility")}


def _conversation_graph(*, optimization: bool) -> Any:
    async def discuss(state: ConversationState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
        messages = state.get("messages") or []
        if not messages or messages[-1].type != "human" or not messages[-1].text.strip():
            raise ValueError("Ask about the plan or describe the changes you want to calculate.")
        choice = runtime.context or AgentContext()
        resources = get_resources()
        client = get_client(url=None)
        cache: dict[tuple[str, str], dict[str, Any]] = {}
        completed: list[Plan] = []
        current = state.get("current") or state.get("source")
        recovered = [plan for plan in state.get("plans", []) if plan["turn_id"] == messages[-1].id]
        pending = state.get("pending")
        if pending and pending["turn_id"] != messages[-1].id:
            pending = None
        pending_model = state.get("pending_model")
        if pending_model and pending_model["turn_id"] != messages[-1].id:
            pending_model = None
        plan_change_started = False
        selected_plan: SourceRun | None = None

        @wrap_tool_call
        async def plan_tools(request: ToolCallRequest,
                                  handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
            nonlocal plan_change_started
            name = request.tool_call["name"]
            if name in PLAN_CHANGE_TOOLS:
                if plan_change_started:
                    return ToolMessage("A plan change is already being applied this turn. Use its result. "
                                       "For selection and changes together, call solve_scenarios with base_plan_id; "
                                       "send multiple scenarios in one call.",
                                       name=name, tool_call_id=request.tool_call["id"], status="error")
                plan_change_started = True
            try:
                return await handler(request)
            except (InvalidExpression, ArithmeticError, ValueError, KeyError, TypeError, SyntaxError) as error:
                if name not in READ_TOOLS:
                    raise
                if name == "select_plan":
                    plan_change_started = False
                return ToolMessage(str(error), name=name, tool_call_id=request.tool_call["id"], status="error")

        async def load(source: SourceRun) -> dict[str, Any]:
            key = (source["thread_id"], source["checkpoint_id"])
            if key not in cache:
                snapshot = await client.threads.get_state(source["thread_id"], checkpoint={"checkpoint_id": source["checkpoint_id"]})
                cache[key] = snapshot["values"]
            return cache[key]

        original = await load(current) if current else {}
        if not optimization and (not original.get("spec") or not original.get("description")):
            raise ValueError("The source must be a saved modeling run.")
        preset, settings, _ = await asyncio.to_thread(resources.resolve, choice.preset or original.get("spec", {}).get("preset"))
        settings = settings.with_thinking(choice.thinking)
        recorder = Recorder(resources.limits, charge=resources.charge(preset))
        kind = "optimization" if optimization else "solution_chat"
        model = resources.model_factory(settings, callbacks=[recorder.callback], metadata={"llm4om_role": kind})

        def selected_source(plan_id: str | None, active: SourceRun | None) -> SourceRun:
            sources = [state.get("source"), active, *(plan["source"] for plan in [*state.get("plans", []), *completed])]
            if plan_id is None and active:
                return active
            for source in sources:
                if source and source["thread_id"] == plan_id:
                    return source
            raise ValueError("Choose a plan from this conversation.")

        def stream_step(step: dict[str, Any], tool_runtime: ToolRuntime, name: str, method: str, language: str) -> None:
            if optimization:
                # Keep method output in the workspace, separate from the agent's message stream.
                visible = {**step, "content": ""} if step["type"] == "llm" else step
                tool_runtime.stream_writer({"type": "modeling_step", "tool_call_id": tool_runtime.tool_call_id,
                    "name": name, "method": method, "language": language, "step": visible})

        @tool
        async def modeling_capabilities() -> dict[str, Any]:
            """Read registered methods, problem scopes, modeling libraries and actual solver-backend availability.

            Consult this before choosing a non-default method, library or explicit backend. A library is not a backend.
            """
            return {"methods": [{"id": item.id, "name": item.name, "description": item.description,
                "linear_only": item.linear_only, "languages": sorted(item.languages) if item.languages else None}
                for item in methods().values()],
                "libraries": [{"id": key, "name": item.name} for key, item in LANGUAGES.items()],
                "backends": await resources.sandbox.catalog()}

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
            nonlocal pending_model
            if not description.strip() or not name.strip():
                raise ValueError("Supply the complete problem and a short name.")
            request = pending_model or {"turn_id": messages[-1].id, "description": description.strip(), "name": name.strip(),
                "method": choice.method or method or "direct", "language": choice.language or language or "pyomo",
                "solver": choice.solver or solver, "preset": preset, "data": state.get("data") or {}}
            selected = next((item for item in methods().values()
                             if request["method"].strip().casefold() in (item.id, item.name.casefold())), None)
            if selected is None:
                raise ValueError("Choose a registered method from modeling_capabilities.")
            library = next((item.id for item in LANGUAGES.values()
                            if request["language"].strip().casefold() in (item.id, item.name.casefold())), request["language"])
            target = CodeTarget(library, request["solver"])
            if selected.languages is not None and target.language not in selected.languages:
                raise ValueError(f"{selected.name} does not support {target.language}.")
            request = {**request, "method": selected.id, "language": target.language}
            pending_model = request
            identity = json.dumps(request, sort_keys=True, ensure_ascii=False)
            identifier = str(uuid5(NAMESPACE_URL, f"{runtime.config['configurable']['thread_id']}:{identity}"))
            try:
                await client.threads.get(identifier)
            except HTTPStatusError as error:
                if error.response.status_code != 404:
                    raise
                def progress(step: dict[str, Any]) -> None:
                    stream_step(step, runtime, request["name"], request["method"], request["language"])

                calculated = await run(request["description"], method=request["method"], language=request["language"],
                    solver=request["solver"], preset=request["preset"], data=request["data"],
                    explain=True, locale=choice.locale, resources=resources, on_step=progress)
                spec = calculated.get("spec") or {}
                await client.threads.create(thread_id=identifier, graph_id=request["method"], metadata={
                    "title": request["name"], "method": request["method"], "language": request["language"],
                    "solver": request["solver"], "preset": request["preset"],
                    "provider": spec.get("llm", {}).get("provider"), "model": spec.get("preset_name") or spec.get("llm", {}).get("model"),
                    "origin": runtime.config["configurable"]["thread_id"], "conversation": runtime.config["configurable"]["thread_id"],
                }, supersteps=[{"updates": [{"as_node": "finish", "values": calculated}]}])
            snapshot = await client.threads.get_state(identifier)
            result = snapshot["values"]
            source: SourceRun = {"thread_id": identifier, "checkpoint_id": snapshot["checkpoint"]["checkpoint_id"]}
            cache[(source["thread_id"], source["checkpoint_id"])] = result
            plan: Plan = {"name": request["name"], "instruction": request["description"], "source": source,
                          "group": None, "turn_id": messages[-1].id}
            completed.append(plan)
            pending_model = None
            facts = {**plan_result(plan, result), "method": request["method"], "language": request["language"]}
            return Command(update={**({"current": source} if result.get("spec") else {}),
                "messages": [ToolMessage(json.dumps(facts, ensure_ascii=False), tool_call_id=runtime.tool_call_id,
                    name="model_and_solve", artifact={"plans": [facts]})]})

        @tool
        async def lookup_variables(query: str, runtime: ToolRuntime[AgentContext], plan_id: str | None = None,
                                   offset: Annotated[int, Field(ge=0)] = 0) -> dict[str, Any]:
            """Inspect a saved plan's problem, solver status, objective and actual decision values.

            Use plan_id to inspect the original or another known plan before comparing results.
            Query matches original variable names (empty means all). Use next_offset to read further pages of 100 values.
            """
            source = selected_source(plan_id, runtime.state["current"])
            values = await load(source)
            solved = values.get("solve") or {}
            variables = solved.get("variables") or {}
            found = {name: value for name, value in variables.items() if query.casefold() in name.casefold()}
            return {"source": source, "description": values["description"], "configuration": configuration(values),
                    "formulation": values.get("formulation"), "code": values.get("code"),
                    "status": solved.get("status"), "objective": solved.get("objective"),
                    "variables": dict(islice(found.items(), offset, offset + 100)), "total_matches": len(found),
                    "next_offset": offset + 100 if offset + 100 < len(found) else None,
                    "explanation": values.get("explanation"), "infeasibility": values.get("infeasibility"),
                    "failure": values.get("failure")}

        @tool(response_format="content_and_artifact")
        async def calculate(expression: str, runtime: ToolRuntime[AgentContext], query: str = "",
                                 plan_id: str | None = None) -> tuple[str, dict[str, Any]]:
            """Evaluate arithmetic, totals, costs or ratios. A saved optimization plan is optional.

            With a saved plan, v maps exact variable names to actual values; values contains ALL values matching query
            (empty means all); objective is its actual objective. Without a plan, use ordinary numeric expressions.
            Each expression returns one number. Use arithmetic and sum, min, max, abs, round, len, sqrt.
            Examples: sum(values); v['x[A]'] * 2 + v['x[B]']; 8 - (2 * v['x[A]'] + v['x[B]']).
            Constants must come from the supplied problem or data. This evaluates expressions, not Python scripts.
            """
            parsed = ast.parse(expression, mode="eval")
            uses_plan = any(isinstance(node, ast.Name) and node.id in {"v", "values", "objective"}
                            for node in ast.walk(parsed))
            source = (selected_source(plan_id, runtime.state["current"])
                      if plan_id or ((uses_plan or query) and runtime.state["current"]) else None)
            values = await load(source) if source else {}
            solved = values.get("solve") or {}
            variables = solved.get("variables") or {}
            matched = {name: value for name, value in variables.items() if query.casefold() in name.casefold()}
            if query and not matched:
                raise ValueError("No matching decision values. Use lookup_variables to find their exact names.")
            names = {"v": dict(variables), "values": list(matched.values())} if variables else {}
            if solved.get("objective") is not None:
                names["objective"] = solved["objective"]
            result = simple_eval(expression, names=names, functions={"sum": sum, "min": min, "max": max,
                "abs": abs, "round": round, "len": len, "sqrt": math.sqrt}, allowed_attrs={})
            if type(result) not in (int, float) or not math.isfinite(result):
                raise ValueError("The expression must return a finite number.")
            facts = {"source": source, "expression": expression, "query": query,
                     "matched_variables": len(matched), "result": result}
            return json.dumps(facts, ensure_ascii=False), {"calculation": facts}

        @tool
        async def select_plan(plan_id: str, runtime: ToolRuntime[AgentContext]) -> Command:
            """Continue the conversation from an explicitly chosen saved plan, without recalculating it.

            Use an available_plans ID when the user chooses a saved alternative or returns to the original.
            For choosing a plan AND changing its conditions in one request, use solve_scenarios with base_plan_id instead.
            """
            nonlocal selected_plan
            source = selected_source(plan_id, runtime.state["current"])
            values = await load(source)
            if not values.get("spec"):
                raise ValueError("This attempt has no saved modeling configuration. Choose a saved modeling plan.")
            selected_plan = source
            name = next((plan["name"] for plan in [*state.get("plans", []), *completed]
                         if plan["source"]["thread_id"] == plan_id), "原方案" if choice.locale == "zh" else "Original plan")
            facts = {"source": source, "name": name, "status": (values.get("solve") or {}).get("status"),
                     "objective": (values.get("solve") or {}).get("objective")}
            return Command(update={"current": source, "messages": [ToolMessage(json.dumps(facts, ensure_ascii=False),
                tool_call_id=runtime.tool_call_id, name="select_plan", artifact={"selected_plan": facts})]})

        @tool
        async def solve_scenarios(scenarios: Annotated[list[Scenario], Field(min_length=1, max_length=6)],
                                  runtime: ToolRuntime[AgentContext], base_plan_id: str | None = None) -> Command:
            """Actually model and solve the user's explicit changed conditions, then read the computed results.

            Call once per turn for all requested scenarios. Do not call for ordinary explanations or vague ideas.
            Every scenario starts from the current frozen plan, or the specified known base_plan_id,
            with the same method, preset, library and attachments.
            A single new plan becomes current; multiple alternatives keep the original current plan.
            """
            nonlocal pending
            # Rephrasing a retry's tool call must not change the saved batch's IDs or baseline.
            base = pending["base"] if pending else selected_source(base_plan_id, runtime.state["current"])
            if pending:
                scenarios = [Scenario.model_validate(item) for item in pending["scenarios"]]
            values = await load(base)
            spec = values["spec"]
            if optimization and ((choice.method and choice.method != spec["method"])
                                 or (choice.language and choice.language != spec["language"])
                                 or (choice.solver and choice.solver != spec["solver"])):
                raise ValueError("Pinned configuration changed; use model_and_solve with the complete revised problem.")
            turn = next(message.id for message in reversed(runtime.state["messages"]) if message.type == "human")
            pending = {"base": base, "scenarios": [item.model_dump() for item in scenarios], "turn_id": turn}
            identity = json.dumps({"base": base, "turn": turn, "scenarios": [item.model_dump() for item in scenarios]}, sort_keys=True, ensure_ascii=False)
            group = uuid5(NAMESPACE_URL, identity).hex if len(scenarios) > 1 else None
            results = []
            for index, scenario in enumerate(scenarios):
                stage = None

                def progress(step: dict[str, Any]) -> None:
                    nonlocal stage
                    stream_step(step, runtime, scenario.name, spec["method"], spec["language"])
                    current_stage = ("revise" if step["title"] == "revise_problem" else
                                     "explain" if step["title"] in ("explain_result", "explain_infeasibility") else
                                     "solve" if step["type"] == "solve" else "model")
                    if step["type"] not in ("llm", "solve") or current_stage == stage:
                        return
                    stage = current_stage
                    runtime.stream_writer({"type": "scenario_progress", "tool_call_id": runtime.tool_call_id,
                        "name": scenario.name, "index": index + 1, "total": len(scenarios), "stage": stage})

                identifier = str(uuid5(NAMESPACE_URL, f"{identity}:{index}"))
                # Stable IDs let a replay reuse completed calculations without running them again.
                try:
                    existing = await client.threads.get(identifier)
                except HTTPStatusError as error:
                    if error.response.status_code != 404:
                        raise
                    existing = None
                if existing is None:
                    calculated = await run(values["description"], method=spec["method"], language=spec["language"],
                        solver=spec["solver"], preset=spec.get("preset"), data=values.get("data"),
                        change=scenario.instruction, explain=True, locale=choice.locale, resources=resources, on_step=progress)
                    await client.threads.create(thread_id=identifier, graph_id=spec["method"], metadata={
                        "title": scenario.name, "method": spec["method"], "language": spec["language"],
                        "solver": spec["solver"], "preset": spec.get("preset"), "provider": spec["llm"]["provider"],
                        "model": spec.get("preset_name") or spec["llm"]["model"], "parent": base,
                        "scenario": scenario.model_dump(), "conversation": runtime.config["configurable"]["thread_id"],
                        **({"group": group} if group else {}),
                    }, supersteps=[{"updates": [{"as_node": "finish", "values": calculated}]}])
                snapshot = await client.threads.get_state(identifier)
                result = snapshot["values"]
                source: SourceRun = {"thread_id": identifier, "checkpoint_id": snapshot["checkpoint"]["checkpoint_id"]}
                cache[(source["thread_id"], source["checkpoint_id"])] = result
                plan: Plan = {"name": scenario.name, "instruction": scenario.instruction, "source": source, "group": group, "turn_id": turn}
                completed.append(plan)
                results.append(plan_result(plan, result))
            pending = None
            update = {"messages": [ToolMessage(json.dumps(results, ensure_ascii=False), tool_call_id=runtime.tool_call_id,
                                                name="solve_scenarios", artifact={"plans": results})]}
            if len(completed) == 1 and result.get("spec"):
                update["current"] = completed[0]["source"]
            return Command(update=update)

        language = "Simplified Chinese" if choice.locale == "zh" else "English"

        @wrap_model_call
        async def actual_plan(request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
            values = await load(request.state["current"]) if request.state["current"] else {}
            solved = values.get("solve") or {}
            recent = []
            for message in reversed(request.state["messages"]):
                if message.type == "human":
                    break
                recent.append(message)
            calculated = (bool(recovered) and pending is None) or any(message.type == "tool" and message.name == "solve_scenarios" for message in recent)
            calculated = calculated or any(message.type == "tool" and message.name == "model_and_solve" for message in recent)
            selected = any(message.type == "tool" and message.name == "select_plan" and message.status == "success" for message in recent)
            tools = [item for item in request.tools if not ((calculated or selected) and item.name in PLAN_CHANGE_TOOLS)
                     and not (item.name in PLAN_READ_TOOLS | {"solve_scenarios"} and not request.state["current"])]
            facts = {key: values.get(key) for key in ("description", "formulation", "code", "explanation", "infeasibility", "failure")}
            facts["description"] = problem_text(values.get("description") or "", values.get("data") or {})
            facts["configuration"] = configuration(values)
            available = {plan["id"]: plan for plan in [
                *([{"name": "Original plan", "id": state["source"]["thread_id"]}] if state.get("source") else []),
                *({"name": plan["name"], "id": plan["source"]["thread_id"]} for plan in [*state.get("plans", []), *completed])]}
            facts["source"] = request.state["current"]
            facts["available_plans"] = [{**plan, "current": plan["id"] == (request.state["current"] or {}).get("thread_id"),
                "original": plan["id"] == (state.get("source") or {}).get("thread_id")} for plan in available.values()]
            facts["solve"] = {**{key: solved.get(key) for key in ("status", "objective", "diagnosis", "error")},
                              "variables": dict(islice((solved.get("variables") or {}).items(), 100)),
                              "total_variables": len(solved.get("variables") or {})}
            if pending:
                facts["unfinished_scenarios"] = pending
            if pending_model:
                facts["unfinished_modeling"] = {key: value for key, value in pending_model.items() if key != "data"}
            if recovered and not pending and not pending_model:
                facts["already_computed_scenarios"] = []
                for plan in recovered:
                    saved = await load(plan["source"])
                    result = saved.get("solve") or {}
                    facts["already_computed_scenarios"].append({"name": plan["name"], "instruction": plan["instruction"],
                        "status": result.get("status"), "objective": result.get("objective"), "failure": saved.get("failure"),
                        "variables": dict(islice((result.get("variables") or {}).items(), 100))})
            prompt = PLAN_TOOLS if request.state["current"] or pending or pending_model or recovered else ""
            if optimization:
                prompt += (OPTIMIZATION_TOOLS
                    + ("Web search is enabled.\n" if choice.search else "Web search is disabled.\n")
                    + "Current editable problem and attachments:\n" + problem_text(state.get("description") or "", state.get("data") or {})
                    + "\nPinned configuration:\n" + json.dumps({"method": choice.method, "language": choice.language, "solver": choice.solver}))
            prompt += "\nCurrent frozen plan:\n" + json.dumps(facts, ensure_ascii=False)
            prompt += "\n" + CONVERSATION_STYLE.format(language=language)
            return await handler(request.override(tools=tools, system_message=SystemMessage(prompt)))

        try:
            tools = [lookup_variables, calculate, select_plan, solve_scenarios]
            if optimization:
                tools += [model_and_solve, modeling_capabilities, *([search_tool(settings)] if choice.search else [])]
            agent = create_agent(model, tools, middleware=[actual_plan, plan_tools, ContextEditingMiddleware(
                edits=[ClearToolUsesEdit(trigger=16_000, keep=3, clear_tool_inputs=True)])],
                state_schema=AgentPlanState, context_schema=AgentContext, checkpointer=False, name=f"{kind}_agent")
            async with asyncio.timeout(resources.limits.run_timeout):
                result = await agent.ainvoke({"messages": messages, "current": current})
            if not result["messages"][-1].text.strip():
                raise ValueError("The assistant did not return a reply.")
            update = {"messages": result["messages"], "current": result["current"], "failure": None}
        except Exception as error:
            advanced = completed[0]["source"] if len(completed) == 1 and pending is None else selected_plan
            update = {"current": advanced if advanced and cache[(advanced["thread_id"], advanced["checkpoint_id"])].get("spec") else current,
                      "failure": f"{type(error).__name__}: {error}"}
        plans = {item["source"]["thread_id"]: item for item in [*(state.get("plans") or []), *completed]}
        usage = {key: state.get("usage", {}).get(key, 0) + value for key, value in recorder.usage.items()}
        first = completed[0]["source"] if completed else None
        initial = first if first and cache[(first["thread_id"], first["checkpoint_id"])].get("spec") else None
        return {**update, "plans": list(plans.values()), "pending": pending, "pending_model": pending_model,
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
