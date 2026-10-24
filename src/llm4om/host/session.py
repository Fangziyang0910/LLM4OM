"""Run the existing method graphs with persistent, host-supplied model answers."""

import asyncio
import math
import time
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.func import task
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime, get_runtime
from langgraph.types import Command

from llm4om.graph import RECURSION_LIMIT, problem_text
from llm4om.host.model import HostChatModel, validate_responses
from llm4om.host.records import Records, open_records
from llm4om.languages import CodeTarget
from llm4om.method_steps import NodeSteps
from llm4om.methods import Method, methods
from llm4om.runtime import Context, Limits, ModelingState
from llm4om.sandbox import Sandbox, SolveResult
from llm4om.storage import write_private_json

CHECKPOINT_TYPES = [("llm4om.sandbox", "SolveResult"),
                    ("llm4om.methods.autoformulation.search", "Node"),
                    ("llm4om.methods.autoformulation.search", "Search")]


@task
async def solve_code(code: str, title: str) -> SolveResult:
    context = get_runtime().context
    return await context.records.execute(context, code, title)


@task
async def run_script(script: str) -> SolveResult:
    context = get_runtime().context
    id, cached = context.records.begin("script", {"script": script})
    if cached is not None:
        return SolveResult(**cached)
    result = await context.sandbox.run_script(script, context.recorder.limits.solve_time_limit)
    context.records.complete(id, asdict(result))
    return result


class HostContext(Context):
    def __init__(self, records: Records, spec: dict[str, Any]) -> None:
        self.records = records
        super().__init__(records.restore(Limits(**spec["limits"])), Sandbox(spec["sandbox"]),
                         lambda role: HostChatModel(role=role), CodeTarget(spec["language"], spec["solver"]), spec["data"])
        self.solved.update(records.solved())

    async def solve(self, code: str, *, title: str = "Solve") -> SolveResult:
        result = await solve_code(code, title)
        self.solved[code] = result
        return result

    async def run_script(self, script: str) -> SolveResult:
        return await run_script(script)


def host_graph(method: Method) -> Any:
    async def finish(state: ModelingState, runtime: Runtime[Context]) -> dict[str, Any]:
        code = state.get("code")
        result = runtime.context.solved.get(code) if code else None
        failure = state.get("failure") or (None if code else f"{method.name} finished without code.")
        if not failure and result is None:
            result = await runtime.context.solve(code, title="Solve final code")
        return {"solve": result, "failure": failure}

    graph = StateGraph(ModelingState, context_schema=Context)
    graph.add_node("method", method.graph())
    graph.add_node("finish", finish)
    graph.add_edge(START, "method")
    graph.add_edge("method", "finish")
    graph.add_edge("finish", END)
    return graph.compile(name=f"host_{method.id}")


def pending_requests(snapshot: Any) -> list[dict[str, Any]]:
    # Nested graphs may surface the same interrupt at more than one level.
    return list({item.id: {"id": item.id, **item.value} for item in snapshot.interrupts}.values())


def result_document(records: Records, snapshot: Any) -> dict[str, Any]:
    spec = records.get("spec")
    values = snapshot.values or {}
    failure = records.get("failure") or values.get("failure")
    pending = [] if failure else pending_requests(snapshot)
    steps = records.recorder.steps.values()
    artifacts = {key: step[key] for step in steps for key in ("formulation", "code")
                 if step.get("type") == "artifact" and isinstance(step.get(key), str)}
    code = values.get("code") or artifacts.get("code")
    solved = records.solved().get(code) if code else None
    state = "failed" if failure else "waiting" if pending else "interrupted" if snapshot.next else "completed"
    public_spec = {key: value for key, value in spec.items() if key != "data"}
    public_spec["data_files"] = list(spec["data"])
    return {"session": str(records.directory), "status": state, "spec": public_spec,
            "pending": pending, "formulation": values.get("formulation") or artifacts.get("formulation"),
            "code": code, "solve": asdict(solved) if solved else None, "failure": failure,
            "steps": list(steps), "usage": {**records.recorder.usage, "input_tokens": None, "output_tokens": None},
            "active_seconds": records.get("active_seconds", 0)}


async def drive(directory: Path, *, initial: bool = False, responses: dict[str, Any] | None = None) -> dict[str, Any]:
    with open_records(directory) as records:
        spec = records.get("spec")
        available = methods()
        if spec["method"] not in available:
            raise ValueError(f"The saved method {spec['method']!r} is not installed.")
        method = available[spec["method"]]
        if spec["version"] != version("llm4om") or spec["parameters"] != method.parameters():
            raise ValueError("The installed version or method parameters changed. Start a new host session.")
        context = HostContext(records, spec)
        graph = host_graph(method)
        async with AsyncSqliteSaver.from_conn_string(str(directory / "checkpoints.sqlite")) as saver:
            saver.serde = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
            graph.checkpointer = saver
            config = {"configurable": {"thread_id": "host"}, "recursion_limit": RECURSION_LIMIT,
                      "callbacks": [NodeSteps(method, context.recorder)]}
            snapshot = await graph.aget_state(config)
            if initial:
                inputs: Any = {"problem": problem_text(spec["description"], spec["data"]),
                               "description": spec["description"]}
            elif responses is not None:
                if records.get("failure") or not snapshot.next:
                    raise ValueError("This host session has ended. Start a new session for a new attempt.")
                validated = validate_responses(pending_requests(snapshot), responses)
                inputs = Command(resume=validated) if validated else None
            if initial or responses is not None:
                started = time.monotonic()
                active = records.get("active_seconds", 0)
                try:
                    remaining = context.recorder.limits.run_timeout - active
                    await asyncio.wait_for(graph.ainvoke(inputs, config, context=context), timeout=max(0, remaining))
                except Exception as error:
                    message = "The run exceeded its active execution time limit." if isinstance(error, TimeoutError) else f"{type(error).__name__}: {error}"
                    records.put("failure", message)
                    context.recorder.step("error", "Host run failed", message)
                finally:
                    records.put("active_seconds", active + time.monotonic() - started)
                snapshot = await graph.aget_state(config)
                if records.get("failure") or (snapshot.values or {}).get("failure"):
                    for step in list(context.recorder.steps.values()):
                        if step.get("running"):
                            context.recorder.step(step["type"], step["title"], step["content"], id=step["id"],
                                                  running=False, failed=True)
            result = result_document(records, snapshot)
            if initial or responses is not None:
                write_private_json(directory / "result.json", result)
                for key, filename in (("formulation", "formulation.md"), ("code", "model.py")):
                    if result.get(key):
                        (directory / filename).write_text(result[key], encoding="utf-8")
            return result


async def start(directory: str | Path, description: str, *, method: str = "direct", language: str = "pyomo",
                solver: str | None = None, data: dict[str, str] | None = None, sandbox: str = "docker",
                max_calls: int | None = None, max_solves: int | None = None,
                time_limit: float | None = None) -> dict[str, Any]:
    """Start a local method graph; return its pending host tasks or final result."""
    available = methods()
    if method not in available:
        raise ValueError(f"Unknown method {method!r}; choose one of {sorted(available)}.")
    if not description.strip():
        raise ValueError("Describe the optimization problem first.")
    selected = available[method]
    target = CodeTarget(language, solver)
    if selected.languages is not None and target.language not in selected.languages:
        raise ValueError(f"{selected.name} does not support {target.language}.")
    Sandbox(sandbox)
    for name in data or {}:
        if not name.strip() or name in {".", ".."} or any(c in name for c in "/\\\0\r\n"):
            raise ValueError(f"Invalid data file name {name!r}.")
    overrides = {key: value for key, value in {"max_llm_calls": max_calls, "max_solves": max_solves,
                                             "solve_time_limit": time_limit}.items() if value is not None}
    if any(not math.isfinite(value) or value <= 0 for value in overrides.values()):
        raise ValueError("Execution limits must be finite and positive.")
    limits = replace(selected.limits or Limits(), **overrides)
    directory = Path(directory).resolve()
    try:
        directory.mkdir(mode=0o700, parents=True)
    except FileExistsError as error:
        raise ValueError(f"Session directory already exists: {directory}. Choose a new directory.") from error
    records = Records(directory)
    try:
        records.put("spec", {"version": version("llm4om"), "model": "host", "method": method,
                             "source": selected.source, "parameters": selected.parameters(), "limits": asdict(limits),
                             "description": description, "data": data or {}, "language": target.language,
                             "solver": target.solver, "sandbox": sandbox, "worker_image": Sandbox(sandbox).image
                             if sandbox == "docker" else None})
    finally:
        records.db.close()
    return await drive(directory, initial=True)


async def resume(directory: str | Path, responses: dict[str, Any]) -> dict[str, Any]:
    """Validate host answers and continue the original method, including its tools and repair paths."""
    if not isinstance(responses, dict):
        raise ValueError("The response file must contain a JSON object mapping pending IDs to answers.")
    return await drive(Path(directory).resolve(), responses=responses)


async def status(directory: str | Path) -> dict[str, Any]:
    """Read the checkpoint, pending requests and actual results without advancing the method."""
    return await drive(Path(directory).resolve())
