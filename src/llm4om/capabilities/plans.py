"""Saved-plan inspection, selection and scenarios, with their model instructions."""

import json
from collections.abc import Awaitable, Callable
from itertools import islice
from typing import Annotated, Any
from uuid import NAMESPACE_URL, uuid5

from httpx import HTTPStatusError
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
from pydantic import Field

from llm4om.graph import problem_text

from .session import (
    TOOL_INPUT_ERRORS,
    AgentContext,
    Conversation,
    Plan,
    Scenario,
    SourceRun,
    configuration,
    plan_result,
)

PLAN_TOOLS = """Use the current frozen plan as the source of truth: the problem, attached data, formulation, code and ACTUAL result.
Describe what the saved decisions mean. Read exact variable identities and units from the problem and model.
Use lookup_variables for omitted decision values or another available plan. Follow next_offset if more values are needed.
Use calculate to check derived totals, costs, utilization, remaining capacity, percentages and numerical comparisons
before reporting them. v contains exact saved variable names and values; values includes every match, not just the displayed page.
Constants in an expression must come from the user's problem or actual data. A derived quantity describes this saved solution;
it does not solve a changed problem or establish a variable's feasible upper or lower bound.
Ground each numerical statement in a returned value or checked calculation. Explain the trade-off supported by those facts.
Check any additional numerical claims too, including resource usage and remaining capacity. Prefer a direct, checked answer
to extra analysis the user did not request. A cost breakdown needs its actual components and total, not a story about how the solver worked.
Do not replace a computed explanation with an invented greedy story, solver search narrative or optimality proof.
Respect the actual status: optimal establishes optimality for the computed model; feasible and locally_optimal mean something else.
Explain failure or infeasibility plainly and help identify a concrete next step using the available evidence.
Saved explanations are interpretations; suggested adjustments are untested candidates, not solver-verified fixes.
Removing one reported conflict does not establish feasibility for the whole problem. Check other requirements before
suggesting a change, and let an actual new solve establish whether it works. Do not promise that a proposed relaxation is sufficient.

For explicit changed conditions, call solve_scenarios once with the user's complete changes; preserve unrelated conditions.
A new requirement changes the problem even if the current solution happens to satisfy it already; save the revised problem.
If undoing changes exactly restores a saved problem with the same data, you may select that saved plan and say you are
reusing its actual result. Run a fresh calculation when the user specifically asks to rerun or verify the modeling workflow.
Several alternatives belong in one call and start from a common frozen baseline. Do not predict a new numerical solution.
A single computed alternative becomes current. Several alternatives leave current unchanged until the user chooses one.
When the user chooses a saved alternative or returns to the original without new conditions, use select_plan to make that
choice persist. If selection and changes are requested together, use solve_scenarios with that base_plan_id directly.
Inspecting or comparing a saved plan alone does not change current. Available plans are ordered and identify original and current.
Use their actual IDs for plan_id or base_plan_id. If a reference genuinely matches several alternatives, ask which one.
Before comparing plans, read their actual conditions, status and objective using lookup_variables. Compare objective values
only when their meaning and units match. A changed number alone is not evidence of an improvement.
Ordinary explanation, looking up values and choosing a saved plan do not require another modeling run.

If already_computed_scenarios is supplied after a reply failure, explain those saved results without repeating the calculation.
If unfinished_modeling or unfinished_scenarios is supplied, finish that exact request on retry; completed work will be reused.
Original plans and attachments remain intact. Delegate modeling to the supplied tools instead of generating substitute solver code.
"""


def plans(session: Conversation) -> list[AgentMiddleware]:
    @tool
    async def lookup_variables(query: str, runtime: ToolRuntime[AgentContext], plan_id: str | None = None,
                               offset: Annotated[int, Field(ge=0)] = 0) -> dict[str, Any]:
        """Inspect a saved plan's problem, solver status, objective and actual decision values.

        Use plan_id to inspect the original or another known plan before comparing results.
        Query matches original variable names (empty means all). Use next_offset to read further pages of 100 values.
        """
        source = session.selected_source(plan_id, runtime.state["current"])
        values = await session.load(source)
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

    @tool
    async def select_plan(plan_id: str, runtime: ToolRuntime[AgentContext]) -> Command:
        """Continue the conversation from an explicitly chosen saved plan, without recalculating it.

        Use an available_plans ID when the user chooses a saved alternative or returns to the original.
        For choosing a plan AND changing its conditions in one request, use solve_scenarios with base_plan_id instead.
        """
        source = session.selected_source(plan_id, runtime.state["current"])
        values = await session.load(source)
        if not values.get("spec"):
            raise ValueError("This attempt has no saved modeling configuration. Choose a saved modeling plan.")
        session.selected_plan = source
        name = next((plan["name"] for plan in [*session.state.get("plans", []), *session.completed]
                     if plan["source"]["thread_id"] == plan_id), "原方案" if session.choice.locale == "zh" else "Original plan")
        facts = {"source": source, "name": name, "status": (values.get("solve") or {}).get("status"),
                 "objective": (values.get("solve") or {}).get("objective")}
        return Command(update={"current": source, "messages": [ToolMessage(json.dumps(facts, ensure_ascii=False),
            tool_call_id=runtime.tool_call_id, name="select_plan", artifact={"type": "selected_plan", "selected_plan": facts})]})

    @tool
    async def solve_scenarios(scenarios: Annotated[list[Scenario], Field(min_length=1, max_length=6)],
                              runtime: ToolRuntime[AgentContext], base_plan_id: str | None = None) -> Command:
        """Actually model and solve the user's explicit changed conditions, then read the computed results.

        Call once per turn for all requested scenarios. Do not call for ordinary explanations or vague ideas.
        Every scenario starts from the current frozen plan, or the specified known base_plan_id,
        with the same method, preset, library and attachments.
        A single new plan becomes current; multiple alternatives keep the original current plan.
        """
        # Rephrasing a retry's tool call must not change the saved batch's IDs or baseline.
        base = session.pending["base"] if session.pending else session.selected_source(base_plan_id, runtime.state["current"])
        if session.pending:
            scenarios = [Scenario.model_validate(item) for item in session.pending["scenarios"]]
        values = await session.load(base)
        spec = values["spec"]
        if session.optimization and ((session.choice.method and session.choice.method != spec["method"])
                             or (session.choice.language and session.choice.language != spec["language"])
                             or (session.choice.solver and session.choice.solver != spec["solver"])):
            raise ValueError("Pinned configuration changed; use model_and_solve with the complete revised problem.")
        turn = next(message.id for message in reversed(runtime.state["messages"]) if message.type == "human")
        session.pending = {"base": base, "scenarios": [item.model_dump() for item in scenarios], "turn_id": turn}
        identity = json.dumps({"base": base, "turn": turn, "scenarios": [item.model_dump() for item in scenarios]}, sort_keys=True, ensure_ascii=False)
        group = uuid5(NAMESPACE_URL, identity).hex if len(scenarios) > 1 else None
        results = []
        for index, scenario in enumerate(scenarios):
            stage = None

            def progress(step: dict[str, Any]) -> None:
                nonlocal stage
                session.stream_step(step, runtime, scenario.name, spec["method"], spec["language"])
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
                existing = await session.client.threads.get(identifier)
            except HTTPStatusError as error:
                if error.response.status_code != 404:
                    raise
                existing = None
            if existing is None:
                calculated = await session.execute(values["description"], method=spec["method"], language=spec["language"],
                    solver=spec["solver"], preset=spec.get("preset"), data=values.get("data"),
                    change=scenario.instruction, explain=True, locale=session.choice.locale, resources=session.resources, on_step=progress)
                await session.client.threads.create(thread_id=identifier, graph_id=spec["method"], metadata={
                    "title": scenario.name, "method": spec["method"], "language": spec["language"],
                    "solver": spec["solver"], "preset": spec.get("preset"), "provider": spec["llm"]["provider"],
                    "model": spec.get("preset_name") or spec["llm"]["model"], "parent": base,
                    "scenario": scenario.model_dump(), "conversation": runtime.config["configurable"]["thread_id"],
                    **({"group": group} if group else {}),
                }, supersteps=[{"updates": [{"as_node": "finish", "values": calculated}]}])
            snapshot = await session.client.threads.get_state(identifier)
            result = snapshot["values"]
            source: SourceRun = {"thread_id": identifier, "checkpoint_id": snapshot["checkpoint"]["checkpoint_id"]}
            session.cache[(source["thread_id"], source["checkpoint_id"])] = result
            plan: Plan = {"name": scenario.name, "instruction": scenario.instruction, "source": source, "group": group, "turn_id": turn}
            session.completed.append(plan)
            results.append(plan_result(plan, result))
        session.pending = None
        update = {"messages": [ToolMessage(json.dumps(results, ensure_ascii=False), tool_call_id=runtime.tool_call_id,
                                            name="solve_scenarios", artifact={"type": "plans", "plans": results})]}
        if len(session.completed) == 1 and result.get("spec"):
            update["current"] = session.completed[0]["source"]
        return Command(update=update)

    @wrap_model_call(tools=[lookup_variables, select_plan, solve_scenarios])
    async def actual_plan(request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
        values = await session.load(request.state["current"]) if request.state["current"] else {}
        solved = values.get("solve") or {}
        tools = [item for item in request.tools
                 if not (session.change_complete and item.name in {"select_plan", "solve_scenarios"})
                 and not (item.name in {"lookup_variables", "select_plan", "solve_scenarios"} and not request.state["current"])]
        facts = {key: values.get(key) for key in ("description", "formulation", "code", "explanation", "infeasibility", "failure")}
        facts["description"] = problem_text(values.get("description") or "", values.get("data") or {})
        facts["configuration"] = configuration(values)
        available = {plan["id"]: plan for plan in [
            *([{"name": "Original plan", "id": session.state["source"]["thread_id"]}] if session.state.get("source") else []),
            *({"name": plan["name"], "id": plan["source"]["thread_id"]} for plan in [*session.state.get("plans", []), *session.completed])]}
        facts["source"] = request.state["current"]
        facts["available_plans"] = [{**plan, "current": plan["id"] == (request.state["current"] or {}).get("thread_id"),
            "original": plan["id"] == (session.state.get("source") or {}).get("thread_id")} for plan in available.values()]
        facts["solve"] = {**{key: solved.get(key) for key in ("status", "objective", "diagnosis", "error")},
                          "variables": dict(islice((solved.get("variables") or {}).items(), 100)),
                          "total_variables": len(solved.get("variables") or {})}
        if session.pending:
            facts["unfinished_scenarios"] = session.pending
        if session.pending_model:
            facts["unfinished_modeling"] = {key: value for key, value in session.pending_model.items() if key != "data"}
        if session.recovered and not session.pending and not session.pending_model:
            facts["already_computed_scenarios"] = []
            for plan in session.recovered:
                saved = await session.load(plan["source"])
                result = saved.get("solve") or {}
                facts["already_computed_scenarios"].append({"name": plan["name"], "instruction": plan["instruction"],
                    "status": result.get("status"), "objective": result.get("objective"), "failure": saved.get("failure"),
                    "variables": dict(islice((result.get("variables") or {}).items(), 100))})
        prompt = PLAN_TOOLS if request.state["current"] or session.pending or session.pending_model or session.recovered else ""
        prompt += "\nCurrent frozen plan:\n" + json.dumps(facts, ensure_ascii=False)
        prompt += "\n" + request.system_message.text
        return await handler(request.override(tools=tools, system_message=SystemMessage(prompt)))

    @wrap_tool_call
    async def plan_tools(request: ToolCallRequest,
                         handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        name = request.tool_call["name"]
        if name not in {"lookup_variables", "select_plan", "solve_scenarios"}:
            return await handler(request)
        try:
            if name in {"select_plan", "solve_scenarios"}:
                return await session.change_plan(request, handler)
            return await handler(request)
        except TOOL_INPUT_ERRORS as error:
            if name == "solve_scenarios":
                raise
            if name == "select_plan":
                session.change_started = False
            return ToolMessage(str(error), name=name, tool_call_id=request.tool_call["id"], status="error")

    return [actual_plan, plan_tools]
