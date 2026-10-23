"""Save visible progress while a method's private graph is still running."""

import asyncio
import time
from contextlib import asynccontextmanager, suppress
from typing import Any, AsyncIterator

from langgraph.store.base import BaseStore

from llm4om.runtime import Recorder

NAMESPACE = ("llm4om", "progress")
SAVE_INTERVAL = 1.0


def timing(started_at: float, *, finished: bool = False) -> dict[str, float]:
    now = time.time()
    return {"started_at": started_at, "elapsed": max(0, now - started_at),
            **({"finished_at": now} if finished else {})}


@asynccontextmanager
async def save_progress(store: BaseStore | None, thread_id: str | None, state: dict[str, Any],
                        recorder: Recorder) -> AsyncIterator[None]:
    """Coalesce step updates in the native Store; flush partial work on cancellation as well as failure.

    Only public artifacts are saved, not method search trees or model credentials. The platform checkpoint owns
    the completed result; this entry supplies progress before that checkpoint exists.
    """
    if store is None or thread_id is None:
        yield
        return
    emit = recorder.emit
    changed = asyncio.Event()
    loop = asyncio.get_running_loop()

    def record(event: dict[str, Any]) -> None:
        emit(event)
        if "step" in event:
            loop.call_soon_threadsafe(changed.set)

    async def save(*, finished: bool = False) -> None:
        steps = {step["id"]: step for step in state.get("steps", [])}
        steps.update(recorder.steps)
        artifacts = {key: step[key] for step in steps.values() for key in ("formulation", "code")
                     if step.get("type") == "artifact" and isinstance(step.get(key), str)}
        snapshot = {key: state[key] for key in ("description", "data", "spec", "formulation", "code", "solve",
                                               "revision", "explanation", "explanation_error") if key in state}
        snapshot.update(artifacts, steps=list(steps.values()), usage=dict(recorder.usage),
                        timing=timing(state["timing"]["started_at"], finished=finished))
        await store.aput(NAMESPACE, thread_id, snapshot, index=False)

    async def write() -> None:
        while True:
            await changed.wait()
            changed.clear()
            await save()
            await asyncio.sleep(SAVE_INTERVAL)

    recorder.emit = record
    writer = asyncio.create_task(write())
    interrupted = False
    try:
        yield
    except BaseException:
        interrupted = True
        raise
    finally:
        recorder.emit = emit
        writer.cancel()
        with suppress(asyncio.CancelledError):
            await writer
        await asyncio.shield(save(finished=interrupted))
