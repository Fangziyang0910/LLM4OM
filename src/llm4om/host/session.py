"""Run the existing method graphs with persistent, host-supplied model answers."""

import asyncio
import json
import math
import shutil
import time
from collections import defaultdict, deque
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

from llm4om.host.model import HostChatModel, validate_responses
from llm4om.host.records import Records, finish_pending_migration, open_records
from llm4om.languages import CodeTarget
from llm4om.method_steps import NodeSteps, latest_artifacts
from llm4om.methods import Method, methods
from llm4om.problem import problem_text, validate_data_files, validate_description
from llm4om.runtime import RECURSION_LIMIT, Context, LimitExceeded, Limits, ModelingState
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
    def __init__(self, records: Records, spec: dict[str, Any], *,
                 replays: dict[str, deque[dict[str, Any]]] | None = None,
                 solve_replays: dict[str, deque[tuple[SolveResult, float]]] | None = None) -> None:
        self.records = records
        self._replays = replays or {}
        self._solve_replays = solve_replays or {}
        super().__init__(records.restore(Limits(**spec["limits"])), Sandbox(spec["sandbox"]),
                         lambda role: HostChatModel(role=role), CodeTarget(spec["language"], spec["solver"]), spec["data"])
        self.solved.update(records.solved())

    def pop_replay(self, role: str) -> dict[str, Any] | None:
        queue = self._replays.get(role)
        return queue.popleft() if queue else None

    def pop_solve_replay(self, code: str) -> tuple[SolveResult, float] | None:
        queue = self._solve_replays.get(code)
        return queue.popleft() if queue else None

    @property
    def has_unconsumed_replays(self) -> bool:
        return any(self._replays.values()) or any(self._solve_replays.values())

    async def solve(self, code: str, *, title: str = "Solve") -> SolveResult:
        result = await solve_code(code, title)
        self.solved[code] = result
        return result

    async def run_script(self, script: str) -> SolveResult:
        return await run_script(script)


def _collect_legacy_replay(records: Records, pending: list[dict[str, Any]],
                           validated: dict[str, dict[str, Any]]) -> tuple[
    dict[str, deque[dict[str, Any]]], dict[str, deque[tuple[SolveResult, float]]]
]:
    """Extract recorded host answers and solver outputs (with measured durations) in operation order."""
    from pydantic import ValidationError

    from llm4om.methods.trival.graph import (
        CodeValidationOutput,
        FormulationValidationOutput,
        SemanticValidationOutput,
    )

    validator_models = {
        "trival.semantic_validator": SemanticValidationOutput,
        "trival.formulation_validator": FormulationValidationOutput,
        "trival.code_validator": CodeValidationOutput,
    }
    replays: dict[str, deque[dict[str, Any]]] = defaultdict(deque)

    def is_valid_verdict(model_cls: Any, call: dict[str, Any]) -> bool:
        if call.get("name") != model_cls.__name__:
            return False
        try:
            model_cls.model_validate(call.get("args"))
            return True
        except ValidationError:
            return False

    def push_llm(role: str, reply: dict[str, Any], *, historic: bool) -> None:
        model_cls = validator_models.get(role)
        if historic and model_cls is not None:
            calls = reply.get("tool_calls", [])
            valid_calls = [call for call in calls if is_valid_verdict(model_cls, call)]
            if len(valid_calls) == 1 and len(calls) > 1:
                # Legacy return_direct validator accepted any batch with exactly one valid schema call.
                reply = {**reply, "tool_calls": valid_calls}
        replays[role].append(reply)

    step_durations = {
        step_id: float(json.loads(raw_step).get("seconds", 0.0))
        for step_id, raw_step in records.db.execute("SELECT id, value FROM host_steps")
    }
    saved_ids: set[str] = set()
    solve_replays: dict[str, deque[tuple[SolveResult, float]]] = defaultdict(deque)
    for op_id, kind, raw_request, raw_result in records.db.execute(
        "SELECT id, kind, request, result FROM host_operations WHERE result IS NOT NULL ORDER BY rowid"
    ):
        request = json.loads(raw_request)
        result = json.loads(raw_result)
        saved_ids.add(op_id)
        if kind == "llm":
            if isinstance(result.get("id"), str):
                saved_ids.add(result["id"])
            push_llm(request["role"], result, historic=True)
        elif kind == "solve":
            solve_replays[request["code"]].append((SolveResult(**result), step_durations.get(op_id, 0.0)))

    for item in pending:
        if item["id"] in saved_ids or f"host_{item['id']}" in saved_ids:
            continue
        push_llm(item["role"], validated[item["id"]], historic=False)
    return replays, solve_replays


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


def result_document(records: Records, snapshot: Any, *, session_dir: Path | None = None) -> dict[str, Any]:
    spec = records.get("spec")
    values = snapshot.values or {}
    failure = records.get("failure") or values.get("failure")
    pending = [] if failure else pending_requests(snapshot)
    steps = records.recorder.steps.values()
    artifacts = latest_artifacts(steps)
    code = values.get("code") or artifacts.get("code")
    solved = records.solved().get(code) if code else None
    state = "failed" if failure else "waiting" if pending else "interrupted" if snapshot.next else "completed"
    public_spec = {key: value for key, value in spec.items() if key != "data"}
    public_spec["data_files"] = list(spec["data"])
    return {"session": str(session_dir or records.directory), "status": state, "spec": public_spec,
            "pending": pending, "formulation": values.get("formulation") or artifacts.get("formulation"),
            "code": code, "solve": asdict(solved) if solved else None, "failure": failure,
            "steps": list(steps), "usage": {**records.recorder.usage, "input_tokens": None, "output_tokens": None},
            "active_seconds": records.get("active_seconds", 0)}


def _finalize_failed_steps(context: HostContext) -> None:
    for step in list(context.recorder.steps.values()):
        if step.get("running"):
            context.recorder.step(step["type"], step["title"], step["content"], id=step["id"],
                                  running=False, failed=True)


def _write_outputs(directory: Path, result: dict[str, Any]) -> None:
    write_private_json(directory / "result.json", result)
    for key, filename in (("formulation", "formulation.md"), ("code", "model.py")):
        if result.get(key):
            (directory / filename).write_text(result[key], encoding="utf-8")


async def _migrate_legacy_trival(directory: Path, method: Method, spec: dict[str, Any], records: Records,
                                 pending: list[dict[str, Any]], validated: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Replay a legacy nested TriVAL session into staging files; commit via roll-forward marker only when caught up."""
    replays, solve_replays = _collect_legacy_replay(records, pending, validated)
    active = records.get("active_seconds", 0)
    staging = directory / ".migrating"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(mode=0o700)
    committed = False
    try:
        staging_records = Records(staging)
        try:
            staging_records.put("spec", spec)
            staging_records.put("active_seconds", active)
            migrating_context = HostContext(staging_records, spec, replays=replays, solve_replays=solve_replays)
            migrating_graph = host_graph(method)
            async with AsyncSqliteSaver.from_conn_string(str(staging / "checkpoints.sqlite")) as migrating_saver:
                migrating_saver.serde = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
                migrating_graph.checkpointer = migrating_saver
                config = {"configurable": {"thread_id": "host"}, "recursion_limit": RECURSION_LIMIT,
                          "callbacks": [NodeSteps(method, migrating_context.recorder)]}
                inputs = {"problem": problem_text(spec["description"], spec["data"]),
                          "description": spec["description"]}
                started = time.monotonic()
                try:
                    remaining = migrating_context.recorder.limits.run_timeout - active
                    await asyncio.wait_for(migrating_graph.ainvoke(inputs, config, context=migrating_context),
                                           timeout=max(0, remaining))
                except (LimitExceeded, TimeoutError) as error:
                    if migrating_context.has_unconsumed_replays:
                        raise
                    message = "The run exceeded its active execution time limit." if isinstance(error, TimeoutError) else f"{type(error).__name__}: {error}"
                    staging_records.put("failure", message)
                    migrating_context.recorder.step("error", "Host run failed", message)
                finally:
                    staging_records.put("active_seconds", active + time.monotonic() - started)
                if migrating_context.has_unconsumed_replays:
                    raise RuntimeError("Legacy TriVAL session replay diverged before consuming all recorded steps.")
                snapshot = await migrating_graph.aget_state(config)
                if staging_records.get("failure") or (snapshot.values or {}).get("failure"):
                    _finalize_failed_steps(migrating_context)
                durable = bool(staging_records.get("failure") or pending_requests(snapshot) or not snapshot.next)
                if not durable:
                    raise RuntimeError("Legacy TriVAL migration did not reach a durable state.")
                result = result_document(staging_records, snapshot, session_dir=directory)
                _write_outputs(staging, result)
        finally:
            staging_records.db.close()

        (staging / "COMMIT").write_text("1", encoding="utf-8")
        committed = True
        records.db.close()
        finish_pending_migration(directory)
        return result
    finally:
        if not committed:
            shutil.rmtree(staging, ignore_errors=True)


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
        legacy_migration: tuple[list[dict[str, Any]], dict[str, dict[str, Any]]] | None = None
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
                pending = pending_requests(snapshot)
                validated = validate_responses(pending, responses)
                legacy = spec["method"] == "trival" and await (await saver.conn.execute(
                    "SELECT 1 FROM checkpoints WHERE checkpoint_ns LIKE 'method:%|%' LIMIT 1"
                )).fetchone()
                if legacy:
                    legacy_migration = (pending, validated)
                else:
                    inputs = Command(resume=validated) if validated else None
            if (initial or responses is not None) and legacy_migration is None:
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
                    _finalize_failed_steps(context)

        if legacy_migration is not None:
            return await _migrate_legacy_trival(directory, method, spec, records, *legacy_migration)

        result = result_document(records, snapshot)
        if initial or responses is not None:
            _write_outputs(directory, result)
        return result


async def start(directory: str | Path, description: str, *, method: str = "direct", language: str = "pyomo",
                solver: str | None = None, data: dict[str, str] | None = None, sandbox: str = "docker",
                max_calls: int | None = None, max_solves: int | None = None,
                time_limit: float | None = None) -> dict[str, Any]:
    """Start a local method graph; return its pending host tasks or final result."""
    available = methods()
    if method not in available:
        raise ValueError(f"Unknown method {method!r}; choose one of {sorted(available)}.")
    validate_description(description)
    selected = available[method]
    target = selected.code_target(language, solver)
    runner = Sandbox(sandbox)
    validate_data_files(data or {})
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
                             "solver": target.solver, "sandbox": sandbox, "worker_image": runner.image
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
