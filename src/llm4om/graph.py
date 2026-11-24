"""The platform graph: prepare → optional revision → method → solve → optional explanation → finish.

The LangGraph server registers one platform graph per method (`server/graphs.py`); `run()` executes one in process.
A run's input is the problem description and its data files; its context names the code language and the LLM.
Method parameters are fixed in `llm4om.methods.presets`. The final state holds the formulation, the code, the solve result and every recorded step.
"""

import asyncio
import operator
import os
import time
import traceback
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field, replace
from functools import cache, partial
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Overwrite

from llm4om.budget import TokenBudget
from llm4om.followups import explain_infeasibility, explain_result, revise_problem
from llm4om.llm import LLMSettings, chat_model
from llm4om.llm_presets import LLMPresetStore
from llm4om.method_steps import NodeSteps
from llm4om.methods import Method, methods
from llm4om.problem import problem_text, validate_data_files, validate_description
from llm4om.progress import NAMESPACE, save_progress, timing
from llm4om.runtime import RECURSION_LIMIT, Context, LimitExceeded, Limits, Recorder
from llm4om.sandbox import Sandbox, SolveResult


class RunInput(TypedDict, total=False):
    description: str  # input: the problem description
    data: dict[str, str]  # input: data file name -> text; the code reads them as build_model(data)
    change: str | None  # optional instruction to revise this problem before modeling


class RunState(RunInput, total=False):
    problem: str  # the description followed by the data files, as the method sees it
    formulation: str | None
    code: str | None
    solve: dict[str, Any] | None  # SolveResult as a dict
    failure: str | None  # why the run failed, possibly after producing code
    revision: dict[str, str] | None  # original description and the user's change request
    explanation: dict[str, Any] | None
    infeasibility: dict[str, Any] | None
    explanation_error: str | None  # presentation failure does not invalidate a solved model
    steps: Annotated[list[dict[str, Any]], operator.add]  # every recorded step, in order
    usage: dict[str, int]  # LLM calls, solves and tokens
    spec: dict[str, Any] | None  # fixed method, LLM and solver settings; never credentials
    timing: dict[str, float]  # execution time, independent of edits to thread metadata
    _deadline: float  # wall-clock deadline survives checkpoints between modeling and final solving


@dataclass
class RunContext:
    """The run's choices. Keys stay with the server: the context names an LLM preset, never a key or a model."""

    language: str = "pyomo"  # code language, which decides the solver
    preset: str | None = None  # LLM preset id; None means the default preset
    solver: str | None = None
    explain: bool = False  # the workbench explains solutions and diagnosed infeasible models
    locale: Literal["zh", "en"] = "zh"
    time_limit: float | None = None  # optional per-solve time limit override in seconds (5..300)


@dataclass
class Resources:
    """What runs use besides their request: LLM presets, the sandbox, limits and the chat-model factory.

    The server reads them from LLM4OM_WORKSPACE, LLM4OM_SANDBOX and LLM4OM_DAILY_TOKENS. In-process callers pass
    their own through `config["configurable"]["llm4om_resources"]`; `llm` then replaces the presets and the budget.
    """

    presets: LLMPresetStore
    sandbox: Sandbox
    limits: Limits = field(default_factory=Limits)
    model_factory: Callable[..., BaseChatModel] = chat_model
    llm: LLMSettings | None = None
    budget: TokenBudget | None = None  # each preset's daily tokens

    def resolve(self, preset: str | None = None) -> tuple[str | None, LLMSettings, str]:
        """Resolve the preset's identity, private settings and display name together."""
        selected = self.presets.find(preset) if self.llm is None else None
        settings = self.llm if self.llm is not None else selected.settings
        settings.validate()
        return selected.id if selected else None, settings, (selected.name if selected else "") or settings.model

    def charge(self, preset: str | None) -> Callable[[int], None] | None:
        if self.llm or not self.budget or preset is None:
            return None
        return lambda tokens: self.budget.charge(preset, tokens)


def _resources(workspace: str | Path | None = None, sandbox: str | None = None,
               llm: LLMSettings | None = None) -> Resources:
    path = Path(os.environ.get("LLM4OM_WORKSPACE", "runs/web") if workspace is None else workspace)
    kind = os.environ.get("LLM4OM_SANDBOX", "docker") if sandbox is None else sandbox
    return Resources(LLMPresetStore(path), Sandbox(kind, max_jobs=int(os.environ.get("LLM4OM_SANDBOX_JOBS") or 4)),
                     llm=llm, budget=TokenBudget(path, int(os.environ.get("LLM4OM_DAILY_TOKENS") or 0)) if llm is None else None)


@cache
def default_resources() -> Resources:
    return _resources()


def get_resources() -> Resources:
    # Only in-process callers can pass Resources; a server request's JSON config cannot replace them.
    resources = (get_config().get("configurable") or {}).get("llm4om_resources")
    return resources if isinstance(resources, Resources) else default_resources()


def platform_graph(method: Method) -> Any:
    """The compiled platform graph that runs `method` and solves its final code."""

    def thread_id() -> str | None:
        return get_config().get("configurable", {}).get("thread_id")

    async def prepare(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        """Reject unusable requests before any LLM call; the reason becomes the run's failure."""
        choice = runtime.context or RunContext()
        description = state.get("description", "")
        change = state.get("change")
        data = {} if state.get("data") is None else state["data"]
        started = time.time()
        resources = get_resources()
        limits = method.limits or resources.limits
        fresh = {"formulation": None, "code": None, "solve": None, "spec": None, "usage": {},
                 "steps": Overwrite([]), "timing": timing(started), "problem": "", "change": None,
                 "revision": None, "explanation": None, "infeasibility": None, "explanation_error": None}
        if runtime.store and (thread := thread_id()):
            await runtime.store.adelete(NAMESPACE, thread)
        try:
            validate_description(description)
            if change is not None and (not isinstance(change, str) or not change.strip()):
                raise ValueError("Describe how you want to change the problem.")
            target = method.code_target(choice.language, choice.solver)
            if (seconds := choice.time_limit) is not None:
                if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 5 <= seconds <= 300:
                    raise ValueError("The solve time limit must be between 5 and 300 seconds.")
                limits = replace(limits, solve_time_limit=float(seconds))
            validate_data_files(data)
            preset, settings, preset_name = await asyncio.to_thread(resources.resolve, choice.preset)
            if charge := resources.charge(preset):
                charge(0)  # raises when the preset's daily budget is spent
        except (ValueError, LimitExceeded) as error:
            return {**fresh, "failure": str(error)}
        spec = {"version": version("llm4om"), "method": method.id, "source": method.source,
                "parameters": method.parameters(), "limits": asdict(limits),
                "language": target.language if target is not None else method.id,
                "solver": target.solver if target is not None else "AUTO",
                "preset": preset, "preset_name": preset_name,
                "llm": settings.public(),
                # Limited CVXPY results from this platform require a checked iterate from the worker.
                **({"cvxpy_limit_checked": True} if target and target.language == "cvxpy" else {}),
                "explain": choice.explain,
                "locale": choice.locale,
                "sandbox": resources.sandbox.kind, "worker_image": resources.sandbox.image if resources.sandbox.kind == "docker" else None}
        return {**fresh, "problem": problem_text(description, data), "failure": None, "_deadline": started + limits.run_timeout,
                "revision": {"description": description, "instruction": change.strip()} if change else None,
                "spec": spec, "timing": timing(started)}

    async def execute(state: RunState, runtime: Runtime[RunContext], *,
                      work: Callable[[RunState, Context, dict[str, Any]], Awaitable[None]],
                      uses_llm: bool = True, explanation: bool = False) -> dict[str, Any]:
        resources = get_resources()
        spec = state["spec"]
        recorder = Recorder(Limits(**spec["limits"]), state["usage"], runtime.stream_writer, resources.charge(spec.get("preset")))
        settings = None
        result: dict[str, Any] = {}

        def chat(role: str) -> BaseChatModel:
            if settings is None:
                raise RuntimeError("This platform node has no LLM.")
            return resources.model_factory(settings, callbacks=[recorder.callback], metadata={"llm4om_role": role})

        async with save_progress(runtime.store, thread_id(), state, recorder):
            try:
                if uses_llm:
                    _, settings, _ = await asyncio.to_thread(resources.resolve, spec["preset"])
                    recorder.redact = settings.redact
                    if settings.public() != spec["llm"]:
                        raise ValueError("The LLM preset changed before the next platform step. Start a new run with the intended preset.")
                target = method.code_target(spec["language"], spec.get("solver"))
                run = Context(recorder, resources.sandbox, chat, target, state.get("data") or {},
                              locale=spec.get("locale", (runtime.context or RunContext()).locale))
                async with asyncio.timeout(state["_deadline"] - time.time()):
                    await work(state, run, result)
            except Exception as error:
                if explanation:
                    message = recorder.redact(str(error) or type(error).__name__)
                    recorder.step("error", "结果解读未完成", message)
                    result["explanation_error"] = message
                else:
                    recorder.step("error", "运行失败", recorder.redact(traceback.format_exc(limit=-8)))
                    result["failure"] = ("The run exceeded its time limit." if isinstance(error, TimeoutError)
                                         else recorder.redact(f"{type(error).__name__}: {error}"))
        return {**result, **recorder.update()}

    async def revise(state: RunState, run: Context, result: dict[str, Any]) -> None:
        description = await revise_problem(run, state["description"], state["revision"]["instruction"])
        run.recorder.step("artifact", "整理调整后的问题", description)
        result.update(description=description, problem=problem_text(description, run.data))

    async def model(state: RunState, run: Context, result: dict[str, Any]) -> None:
        """Run the method's graph; each titled node update becomes a step."""
        graph = method.graph()
        graph.checkpointer = False  # the method's inner states are not checkpointed; the platform state is
        final: dict[str, Any] = {}

        try:
            config = {"recursion_limit": RECURSION_LIMIT, "callbacks": [NodeSteps(method, run.recorder)]}
            async for final in graph.astream({"problem": state["problem"], "description": state["description"]},
                                            config, context=run, stream_mode="values"):
                pass
        finally:
            code = final.get("code")
            # Keep the completed artifacts on failure and associate a result only with its exact code.
            solved = run.solved.get(code) if code else None
            result.update(formulation=final.get("formulation"), code=code, solve=asdict(solved) if solved else None)
        result["failure"] = final.get("failure") or (None if code else f"{method.name} finished without code.")

    async def solve(state: RunState, run: Context, result: dict[str, Any]) -> None:
        """Solve the final code in the sandbox when the method did not."""
        spec = state["spec"]
        solved = await run.solve(state["code"], title="求解最终代码",
                                 language=None if run.target is not None else spec["language"],
                                 solver=None if run.target is not None else spec.get("solver"))
        result["solve"] = asdict(solved)

    async def explain(state: RunState, run: Context, result: dict[str, Any]) -> None:
        infeasible = state["solve"]["status"] == "infeasible"
        interpret = explain_infeasibility if infeasible else explain_result
        explanation = await interpret(run, state["problem"], state.get("formulation"), state.get("code"), state["solve"], state["spec"]["locale"])
        run.recorder.step("artifact", "解释无解原因" if infeasible else "解读求解结果", explanation["summary"])
        result["explanation_error"] = None
        result["infeasibility" if infeasible else "explanation"] = explanation

    async def finish(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        if runtime.store and (thread := thread_id()):
            await runtime.store.adelete(NAMESPACE, thread)
        return {"timing": timing(state["timing"]["started_at"], finished=True)}

    def after_prepare(state: RunState) -> str:
        if state.get("failure"):
            return "finish"
        return "revise" if state.get("revision") else "model"

    def after_model(state: RunState) -> str:
        if state.get("code") and not state.get("solve") and not state.get("failure"):
            return "solve"
        return after_solve(state)

    def after_solve(state: RunState) -> str:
        solved = state.get("solve") or {}
        diagnosis = solved.get("diagnosis") or {}
        diagnosed = solved.get("status") == "infeasible" and diagnosis.get("items") and not diagnosis.get("error")
        interpret = ((state.get("spec") or {}).get("explain") and not state.get("failure") and not solved.get("error")
                     and (SolveResult.from_payload(solved).has_solution or diagnosed))
        return "explain" if interpret else "finish"

    builder = StateGraph(RunState, input_schema=RunInput, context_schema=RunContext)
    builder.add_node("prepare", prepare)
    builder.add_node("revise", partial(execute, work=revise))
    builder.add_node("model", partial(execute, work=model))
    builder.add_node("solve", partial(execute, work=solve, uses_llm=False))
    builder.add_node("explain", partial(execute, work=explain, explanation=True))
    builder.add_node("finish", finish)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", after_prepare, ["model", "revise", "finish"])
    builder.add_conditional_edges("revise", lambda state: "finish" if state.get("failure") else "model", ["model", "finish"])
    builder.add_conditional_edges("model", after_model, ["solve", "explain", "finish"])
    builder.add_conditional_edges("solve", after_solve, ["explain", "finish"])
    builder.add_edge("explain", "finish")
    builder.add_edge("finish", END)
    return builder.compile(name=method.id)


async def run(description: str, *, method: str = "direct", language: str = "pyomo",
              solver: str | None = None, data: dict[str, str] | None = None,
              preset: str | None = None, llm: LLMSettings | None = None,
              workspace: str | Path | None = None, sandbox: str | None = None,
              resources: Resources | None = None, time_limit: float | None = None,
              change: str | None = None, explain: bool = False, locale: Literal["zh", "en"] = "zh",
              on_step: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Run one method in process and return the final state. `on_step` receives each step as it is recorded."""
    available = methods()
    if method not in available:
        raise ValueError(f"Unknown method {method!r}; choose one of {sorted(available)}.")
    if resources is None and (llm is not None or workspace is not None or sandbox is not None):
        resources = _resources(workspace, sandbox, llm)
    final: dict[str, Any] = {}
    # In-process execution must not inherit a calling conversation's checkpoints, progress key or message stream.
    config: RunnableConfig = {"tags": ["nostream"], "configurable": {"thread_id": None, "llm4om_resources": resources}}
    graph = platform_graph(available[method])
    graph.checkpointer = False
    async for mode, chunk in graph.astream(
            {"description": description, "data": data or {}, "change": change}, config,
            context=RunContext(language, preset, solver, explain, locale, time_limit), stream_mode=["custom", "values"]):
        if mode == "values":
            final = chunk
        elif on_step and "step" in chunk:
            on_step(chunk["step"])
    return final
