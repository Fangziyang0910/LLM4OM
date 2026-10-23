"""Discuss frozen solver results and delegate requested changes to the existing platform graphs."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict
from uuid import NAMESPACE_URL, uuid5

from httpx import HTTPStatusError
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
from langgraph_sdk import get_client
from pydantic import BaseModel, ConfigDict, Field

from llm4om.graph import get_resources, problem_text, run
from llm4om.runtime import Recorder


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


class SolutionInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    source: SourceRun


class SolutionState(SolutionInput, total=False):
    current: SourceRun
    plans: list[Plan]
    usage: dict[str, int]
    failure: str | None
    pending: PendingBatch | None


@dataclass
class SolutionContext:
    preset: str | None = None
    locale: Literal["zh", "en"] = "zh"


class AgentPlanState(AgentState):
    current: SourceRun


class Scenario(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100, description="A short business name for this scenario")
    instruction: str = Field(min_length=1, description="The user's complete, explicit changes; preserve all other requirements")


def solution_graph() -> Any:
    async def discuss(state: SolutionState, runtime: Runtime[SolutionContext]) -> dict[str, Any]:
        messages = state.get("messages") or []
        if not messages or messages[-1].type != "human" or not messages[-1].text.strip():
            raise ValueError("Ask about the plan or describe the changes you want to calculate.")
        choice = runtime.context or SolutionContext()
        resources = get_resources()
        client = get_client(url=None)
        cache: dict[tuple[str, str], dict[str, Any]] = {}
        completed: list[Plan] = []
        current = state.get("current") or state["source"]
        recovered = [plan for plan in state.get("plans", []) if plan["turn_id"] == messages[-1].id]
        pending = state.get("pending")
        if pending and pending["turn_id"] != messages[-1].id:
            pending = None

        async def load(source: SourceRun) -> dict[str, Any]:
            key = (source["thread_id"], source["checkpoint_id"])
            if key not in cache:
                snapshot = await client.threads.get_state(source["thread_id"], checkpoint={"checkpoint_id": source["checkpoint_id"]})
                cache[key] = snapshot["values"]
            return cache[key]

        original = await load(current)
        if not original.get("spec") or not original.get("description"):
            raise ValueError("The source must be a saved modeling run.")
        preset, settings, _ = await asyncio.to_thread(resources.resolve, choice.preset or original["spec"].get("preset"))
        recorder = Recorder(resources.limits, charge=resources.charge(preset))
        model = resources.model_factory(settings, callbacks=[recorder.callback], metadata={"llm4om_role": "solution_chat"})

        def selected_source(plan_id: str | None, active: SourceRun) -> SourceRun:
            sources = [state["source"], active, *(plan["source"] for plan in [*state.get("plans", []), *completed])]
            if plan_id is None:
                return active
            for source in sources:
                if source["thread_id"] == plan_id:
                    return source
            raise ValueError("Choose a plan from this conversation.")

        @tool
        async def lookup_variables(query: str, runtime: ToolRuntime[SolutionContext], plan_id: str | None = None) -> dict[str, Any]:
            """Inspect a saved plan's problem, solver status, objective and actual decision values.

            Use plan_id to inspect the original or another known plan before comparing results.
            Query matches original variable names (empty means all), returning up to 100 values and the matched count.
            """
            source = selected_source(plan_id, runtime.state["current"])
            values = await load(source)
            solved = values.get("solve") or {}
            variables = solved.get("variables") or {}
            found = {name: value for name, value in variables.items() if query.casefold() in name.casefold()}
            return {"source": source, "description": values["description"],
                    "formulation": values.get("formulation"), "code": values.get("code"),
                    "status": solved.get("status"), "objective": solved.get("objective"),
                    "variables": dict(list(found.items())[:100]), "total_matches": len(found),
                    "explanation": values.get("explanation"), "infeasibility": values.get("infeasibility"),
                    "failure": values.get("failure")}

        @tool
        async def solve_scenarios(scenarios: Annotated[list[Scenario], Field(min_length=1, max_length=6)],
                                  runtime: ToolRuntime[SolutionContext], base_plan_id: str | None = None) -> Command:
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
            turn = next(message.id for message in reversed(runtime.state["messages"]) if message.type == "human")
            pending = {"base": base, "scenarios": [item.model_dump() for item in scenarios], "turn_id": turn}
            identity = json.dumps({"base": base, "turn": turn, "scenarios": [item.model_dump() for item in scenarios]}, sort_keys=True, ensure_ascii=False)
            group = uuid5(NAMESPACE_URL, identity).hex if len(scenarios) > 1 else None
            results = []
            for index, scenario in enumerate(scenarios):
                stage = None

                def progress(step: dict[str, Any]) -> None:
                    nonlocal stage
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
                solved = result.get("solve") or {}
                results.append({**plan, "description": result["description"], "status": solved.get("status"),
                    "objective": solved.get("objective"), "variables": dict(list((solved.get("variables") or {}).items())[:100]),
                    "total_variables": len(solved.get("variables") or {}), "failure": result.get("failure"),
                    "explanation": result.get("explanation"), "infeasibility": result.get("infeasibility")})
            pending = None
            update = {"messages": [ToolMessage(json.dumps(results, ensure_ascii=False), tool_call_id=runtime.tool_call_id,
                                                name="solve_scenarios", artifact={"plans": results})]}
            if len(completed) == 1 and result.get("spec"):
                update["current"] = completed[0]["source"]
            return Command(update=update)

        language = "简体中文" if choice.locale == "zh" else "English"

        @wrap_model_call
        async def actual_plan(request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
            values = await load(request.state["current"])
            solved = values.get("solve") or {}
            recent = []
            for message in reversed(request.state["messages"]):
                if message.type == "human":
                    break
                recent.append(message)
            calculated = (bool(recovered) and pending is None) or any(message.type == "tool" and message.name == "solve_scenarios" for message in recent)
            tools = [item for item in request.tools if not (calculated and item.name == "solve_scenarios")]
            facts = {key: values.get(key) for key in ("description", "formulation", "code", "explanation", "infeasibility", "failure")}
            facts["description"] = problem_text(values["description"], values.get("data") or {})
            facts["available_plans"] = [{"name": "Original plan", "id": state["source"]["thread_id"]},
                *({"name": plan["name"], "id": plan["source"]["thread_id"]} for plan in [*state.get("plans", []), *completed])]
            facts["solve"] = {**{key: solved.get(key) for key in ("status", "objective", "diagnosis", "error")},
                              "variables": dict(list((solved.get("variables") or {}).items())[:100]),
                              "total_variables": len(solved.get("variables") or {})}
            if pending:
                facts["unfinished_scenarios"] = pending
            elif recovered:
                facts["already_computed_scenarios"] = []
                for plan in recovered:
                    saved = await load(plan["source"])
                    result = saved.get("solve") or {}
                    facts["already_computed_scenarios"].append({"name": plan["name"], "instruction": plan["instruction"],
                        "status": result.get("status"), "objective": result.get("objective"), "failure": saved.get("failure"),
                        "variables": dict(list((result.get("variables") or {}).items())[:100])})
            prompt = (f"Discuss an optimization plan with an ordinary user in {language}. Reply naturally and concisely. "
                "Use only the supplied problem, mathematical model, code and ACTUAL solver results. "
                "Use lookup_variables for decision values omitted from the snapshot. Preserve exact variable identities. "
                "To compare with the original or another saved plan, use lookup_variables with that plan's ID "
                "to read its actual objective, status and conditions first. Compare objective values only when "
                "their meaning and units match; do not infer improvement from a number alone. "
                "Explain what the computed numbers mean. Do not invent missing values, utilization, constraints, causes "
                "or optimality proofs. Distinguish what the model expresses from what the solver actually established. "
                "If the user explicitly asks what happens under concrete new conditions, call solve_scenarios once "
                "for those alternatives before stating any changed outcome. Never predict a new numerical solution. "
                "Do not recompute for explanations or invent missing scenario values; ask one short question if needed. "
                "After the tool returns, answer from its computed results, including failures or infeasibility. "
                "A single calculated alternative is now the current plan; further changes apply to it. "
                "For multiple alternatives, the current plan remains unchanged; ask which one if a later request is ambiguous. "
                "When the user explicitly refers to the original or another saved plan, use its available_plans ID "
                "as base_plan_id for calculations or plan_id for value lookups. Never use an unknown ID. "
                "If already_computed_scenarios is supplied, these changes were calculated before a reply failure: explain "
                "their actual results now without repeating the calculations. Treat truncated file excerpts as partial data. "
                "If unfinished_scenarios is supplied, call solve_scenarios to finish that saved batch from its fixed "
                "base and exact scenarios. Completed calculations will be reused; do not treat a partial batch as finished. "
                "Original plans and attachments remain intact. Do not generate or execute substitute solver code yourself.\n"
                "Current frozen plan:\n" + json.dumps(facts, ensure_ascii=False))
            return await handler(request.override(tools=tools, system_message=SystemMessage(prompt)))

        try:
            agent = create_agent(model, [lookup_variables, solve_scenarios], middleware=[actual_plan, ContextEditingMiddleware(
                edits=[ClearToolUsesEdit(trigger=16_000, keep=3, clear_tool_inputs=True)])],
                state_schema=AgentPlanState, context_schema=SolutionContext, checkpointer=False, name="solution_agent")
            async with asyncio.timeout(resources.limits.run_timeout):
                result = await agent.ainvoke({"messages": messages, "current": current})
            if not result["messages"][-1].text.strip():
                raise ValueError("The assistant did not return a reply.")
            update = {"messages": result["messages"], "current": result["current"], "failure": None}
        except Exception as error:
            advanced = completed[0]["source"] if len(completed) == 1 and pending is None else None
            update = {"current": advanced if advanced and cache[(advanced["thread_id"], advanced["checkpoint_id"])].get("spec") else current,
                      "failure": f"{type(error).__name__}: {error}"}
        plans = {item["source"]["thread_id"]: item for item in [*(state.get("plans") or []), *completed]}
        usage = {key: state.get("usage", {}).get(key, 0) + value for key, value in recorder.usage.items()}
        return {**update, "plans": list(plans.values()), "pending": pending, "usage": usage}

    graph = StateGraph(SolutionState, input_schema=SolutionInput, context_schema=SolutionContext)
    graph.add_node("discuss", discuss)
    graph.add_edge(START, "discuss")
    graph.add_edge("discuss", END)
    return graph.compile(name="solution_chat")
