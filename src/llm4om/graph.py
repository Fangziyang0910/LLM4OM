"""The platform graph of a method: prepare → model (the method's own graph) → solve.

The LangGraph server registers one platform graph per method (`server/graphs.py`); `run()` executes one in process.
A run's input is the problem description and its data files; its context names the code language and the LLM.
Method parameters are fixed in `llm4om.methods.presets`. The final state holds the formulation, the code, the solve result and every recorded step.
"""

import asyncio
import json
import operator
import os
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.languages import CodeTarget
from llm4om.llm import LLMPresetStore, LLMSettings, chat_model
from llm4om.methods import Method, methods
from llm4om.runtime import Context, Limits, Recorder
from llm4om.sandbox import Sandbox

RECURSION_LIMIT = 1_000_000  # loops are bounded by each method and by Limits, not by LangGraph's step count
DATA_NAME = r"[\w\-][\w\-. ]*"
MAX_DATA_CHARS = 20000
HIDDEN_KEYS = {"problem", "solve", "messages", "failure"}  # and keys starting with "_": never shown in a step


class RunState(TypedDict, total=False):
    description: str  # input: the problem description
    data: dict[str, str]  # input: data file name -> text; the code reads them as build_model(data)
    problem: str  # the description followed by the data files, as the method sees it
    formulation: str | None
    code: str | None
    solve: dict[str, Any] | None  # SolveResult as a dict
    failure: str | None  # why the run ended without code
    steps: Annotated[list[dict[str, Any]], operator.add]  # every recorded step, in order
    usage: dict[str, int]  # LLM calls, solves and tokens
    _deadline: float  # wall-clock deadline survives checkpoints between modeling and final solving


@dataclass
class RunContext:
    """The run's choices. Keys stay with the server: the context names an LLM preset, never a key or a model."""

    language: str = "pyomo"  # code language, which decides the solver
    preset: str | None = None  # LLM preset id; None means the default preset


@dataclass
class Resources:
    """What runs use besides their request: LLM presets, the sandbox, limits and the chat-model factory.

    The server reads them from LLM4OM_WORKSPACE and LLM4OM_SANDBOX. In-process callers pass their own through
    `config["configurable"]["llm4om_resources"]`; `llm` then replaces the presets.
    """

    presets: LLMPresetStore
    sandbox: Sandbox
    limits: Limits = field(default_factory=Limits)
    model_factory: Callable[..., BaseChatModel] = chat_model
    llm: LLMSettings | None = None

    def llm_settings(self, preset: str | None = None) -> LLMSettings:
        """The settings for one run: `llm` when given, otherwise the preset."""
        settings = self.llm or self.presets.get(preset)
        settings.validate()
        return settings


@cache
def default_resources() -> Resources:
    workspace = Path(os.environ.get("LLM4OM_WORKSPACE", "runs/web"))
    return Resources(LLMPresetStore(workspace), Sandbox(os.environ.get("LLM4OM_SANDBOX", "docker")))


def _resources() -> Resources:
    # Only in-process callers can pass Resources; a server request's JSON config cannot replace them.
    resources = (get_config().get("configurable") or {}).get("llm4om_resources")
    return resources if isinstance(resources, Resources) else default_resources()


def problem_text(description: str, data: dict[str, str]) -> str:
    """The problem description followed by every attached data file."""
    parts = ["## Problem description\n" + description.strip()]
    for name, content in data.items():
        shown = content if len(content) <= MAX_DATA_CHARS else content[:MAX_DATA_CHARS] + "\n... (truncated)"
        parts.append(f"## Data file `{name}`\n```\n{shown}\n```")
    return "\n\n".join(parts)


def render_update(update: dict[str, Any], hidden: frozenset[str] = frozenset()) -> str:
    """A node update as Markdown: text as is, code in a Python block, flags and numbers on one line, anything else
    as JSON. Several keys get a heading each, named after the key."""
    shown = {key: value for key, value in update.items() if key not in HIDDEN_KEYS and key not in hidden
             and not key.startswith("_") and value not in (None, "", [], {})}
    parts = []
    for key, value in shown.items():
        name = key.replace("_", " ").capitalize()
        if isinstance(value, bool):
            parts.append(f"{'✅' if value else '❌'} **{name}**")
            continue
        if isinstance(value, (int, float)):
            parts.append(f"**{name}**: {value}")
            continue
        if isinstance(value, str):
            body = f"```python\n{value.rstrip()}\n```" if key == "code" or key.endswith("_code") else value
        else:
            body = "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n```"
        parts.append(body if len(shown) == 1 else f"#### {name}\n\n{body}")
    return "\n\n".join(parts)


class _NodeSteps(BaseCallbackHandler):
    """Records the update of each titled method node as an artifact step the moment the node ends.

    A node's end callback runs before the next node starts, so the step lands between the LLM calls and solves
    that produced it and those that follow; a consumer of the graph's update stream would see it late.
    """

    run_inline = True

    def __init__(self, method: Method, recorder: Recorder) -> None:
        self.method, self.recorder = method, recorder
        self.nodes: dict[UUID, str] = {}  # run id -> node name, for the runs of titled nodes

    def on_chain_start(self, serialized: dict[str, Any] | None, inputs: Any, *, run_id: UUID,
                       tags: list[str] | None = None, metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        node = (metadata or {}).get("langgraph_node")
        # A node's own run carries its name and a graph-step tag; runnables inside it inherit only the metadata.
        if node in self.method.titles and kwargs.get("name") == node and any(
                tag.startswith("graph:step:") for tag in tags or []):
            self.nodes[run_id] = node

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        node = self.nodes.pop(run_id, None)
        if node and isinstance(outputs, dict) and (text := render_update(outputs, self.method.hidden)):
            produced = {key: outputs[key] for key in ("formulation", "code") if isinstance(outputs.get(key), str)}
            self.recorder.step("artifact", self.method.titles[node], text, node=node, **produced)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self.nodes.pop(run_id, None)


def platform_graph(method: Method) -> Any:
    """The compiled platform graph that runs `method` and solves its final code."""

    def context(state: RunState, runtime: Runtime[RunContext]) -> Context:
        """The method context of one node; its recorder continues the run's counts."""
        resources = _resources()
        choice = runtime.context or RunContext()
        recorder = Recorder(method.limits or resources.limits, state.get("usage"), runtime.stream_writer)

        def model(role: str) -> BaseChatModel:
            return resources.model_factory(resources.llm_settings(choice.preset),
                                           callbacks=[recorder.callback], metadata={"llm4om_role": role})

        return Context(recorder, resources.sandbox, model, CodeTarget(choice.language), state.get("data") or {})

    async def prepare(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        """Reject unusable requests before any LLM call; the reason becomes the run's failure."""
        choice = runtime.context or RunContext()
        data = state.get("data") or {}
        deadline = time.time() + (method.limits or _resources().limits).run_timeout
        try:
            if not (state.get("description") or "").strip():
                raise ValueError("Describe the optimization problem first.")
            CodeTarget(choice.language)  # raises for an unknown language
            if method.languages is not None and choice.language not in method.languages:
                raise ValueError(f"{method.name} does not support the code language {choice.language!r}; "
                                 f"choose one of {sorted(method.languages)}.")
            for name in data:
                if not re.fullmatch(DATA_NAME, name):
                    raise ValueError(f"Invalid data file name {name!r}; use letters, digits, '-', '_', '.' and spaces.")
            _resources().llm_settings(choice.preset)
        except ValueError as error:
            return {"failure": str(error)}
        return {"problem": problem_text(state.get("description", ""), data), "failure": None, "_deadline": deadline}

    def failure(error: Exception, recorder: Recorder) -> dict[str, Any]:
        message = "The run exceeded its time limit." if isinstance(error, TimeoutError) else f"{type(error).__name__}: {error}"
        recorder.step("error", "运行失败", traceback.format_exc(limit=-8))
        return {"failure": message}

    async def model(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        """Run the method's graph; each titled node update becomes a step."""
        run = context(state, runtime)
        recorder = run.recorder
        graph = method.graph()
        graph.checkpointer = False  # the method's inner states are not checkpointed; the platform state is
        final: dict[str, Any] = {}

        async def drive() -> None:
            config: RunnableConfig = {"recursion_limit": RECURSION_LIMIT, "callbacks": [_NodeSteps(method, recorder)]}
            async for values in graph.astream({"problem": state.get("problem", "")}, config, context=run,
                                              stream_mode="values"):
                final.update(values)

        try:
            await asyncio.wait_for(drive(), state["_deadline"] - time.time())
            code = final.get("code")
            solved = final.get("solve") or (run.solved.get(code) if code else None)
            result = {"formulation": final.get("formulation"), "code": code, "solve": asdict(solved) if solved else None,
                      "failure": None if code else final.get("failure") or f"{method.name} finished without code."}
        except Exception as error:  # any method failure ends the run with a visible reason
            result = failure(error, recorder)
        return {**result, **recorder.update()}

    async def solve(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        """Solve the final code in the sandbox when the method did not."""
        run = context(state, runtime)
        try:
            solved = await asyncio.wait_for(run.solve(state.get("code") or "", title="求解最终代码"),
                                            state["_deadline"] - time.time())
            result = {"solve": asdict(solved)}
        except Exception as error:
            result = failure(error, run.recorder)
        return {**result, **run.recorder.update()}

    builder = StateGraph(RunState, context_schema=RunContext)
    builder.add_node("prepare", prepare)
    builder.add_node("model", model)
    builder.add_node("solve", solve)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", lambda state: END if state.get("failure") else "model", ["model", END])
    builder.add_conditional_edges("model", lambda state: "solve" if state.get("code") and not state.get("solve") else END,
                                  ["solve", END])
    builder.add_edge("solve", END)
    return builder.compile(name=method.id)


async def run(description: str, *, method: str = "direct", language: str = "pyomo", data: dict[str, str] | None = None,
              preset: str | None = None, resources: Resources | None = None,
              on_step: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Run one method in process and return the final state. `on_step` receives each step as it is recorded."""
    available = methods()
    if method not in available:
        raise ValueError(f"Unknown method {method!r}; choose one of {sorted(available)}.")
    final: dict[str, Any] = {}
    config: RunnableConfig = {"configurable": {"llm4om_resources": resources}} if resources else {}
    async for mode, chunk in platform_graph(available[method]).astream(
            {"description": description, "data": data or {}}, config,
            context=RunContext(language, preset), stream_mode=["custom", "values"]):
        if mode == "values":
            final = chunk
        elif on_step and "step" in chunk:
            on_step(chunk["step"])
    return final
