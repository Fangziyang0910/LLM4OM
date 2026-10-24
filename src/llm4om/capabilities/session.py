"""Per-turn plan references and recovery, backed by the existing LangGraph state."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from itertools import islice
from typing import Annotated, Any, Literal, TypedDict

from langchain.agents import AgentState
from langchain.agents.middleware import ToolCallRequest
from langchain.tools import ToolRuntime
from langchain_core.messages import AnyMessage, ToolMessage
from langgraph.graph import add_messages
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field
from simpleeval import InvalidExpression

from llm4om.graph import Resources

TOOL_INPUT_ERRORS = (InvalidExpression, ArithmeticError, ValueError, KeyError, TypeError, SyntaxError)


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
class Conversation:
    def __init__(self, state: ConversationState, choice: AgentContext, resources: Resources, client: Any,
                 execute: Callable[..., Awaitable[dict[str, Any]]], *, optimization: bool):
        self.state, self.choice, self.resources = state, choice, resources
        self.client, self.execute, self.optimization = client, execute, optimization
        self.messages = state["messages"]
        self.cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.completed: list[Plan] = []
        turn = self.messages[-1].id
        self.recovered = [plan for plan in state.get("plans", []) if plan["turn_id"] == turn]
        self.pending = state.get("pending")
        if self.pending and self.pending["turn_id"] != turn:
            self.pending = None
        self.pending_model = state.get("pending_model")
        if self.pending_model and self.pending_model["turn_id"] != turn:
            self.pending_model = None
        self.change_started = False
        self.selected_plan: SourceRun | None = None

    @property
    def change_complete(self) -> bool:
        return self.change_started or (bool(self.recovered) and self.pending is None)

    async def change_plan(self, request: ToolCallRequest,
                          handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        if self.change_started:
            return ToolMessage("A plan change is already being applied this turn. Use its result. "
                               "For selection and changes together, call solve_scenarios with base_plan_id; "
                               "send multiple scenarios in one call.",
                               name=request.tool_call["name"], tool_call_id=request.tool_call["id"], status="error")
        self.change_started = True
        return await handler(request)

    async def load(self, source: SourceRun) -> dict[str, Any]:
        key = (source["thread_id"], source["checkpoint_id"])
        if key not in self.cache:
            snapshot = await self.client.threads.get_state(source["thread_id"], checkpoint={"checkpoint_id": source["checkpoint_id"]})
            self.cache[key] = snapshot["values"]
        return self.cache[key]

    def selected_source(self, plan_id: str | None, active: SourceRun | None) -> SourceRun:
        sources = [self.state.get("source"), active,
                   *(plan["source"] for plan in [*self.state.get("plans", []), *self.completed])]
        if plan_id is None and active:
            return active
        for source in sources:
            if source and source["thread_id"] == plan_id:
                return source
        raise ValueError("Choose a plan from this conversation.")

    def stream_step(self, step: dict[str, Any], tool_runtime: ToolRuntime, name: str, method: str, language: str) -> None:
        if self.optimization:
            # Keep method output in the workspace, separate from the agent's message stream.
            visible = {**step, "content": ""} if step["type"] == "llm" else step
            tool_runtime.stream_writer({"type": "modeling_step", "tool_call_id": tool_runtime.tool_call_id,
                "name": name, "method": method, "language": language, "step": visible})
