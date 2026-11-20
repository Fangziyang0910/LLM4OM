"""Save visible progress while a method's private graph is still running."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from langgraph.store.base import BaseStore

from llm4om.method_steps import latest_artifacts
from llm4om.runtime import Recorder

logger = logging.getLogger(__name__)
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
        snapshot = {key: state[key] for key in ("description", "data", "spec", "formulation", "code", "solve",
                                               "revision", "explanation", "infeasibility", "explanation_error") if key in state}
        snapshot.update(latest_artifacts(steps.values()), steps=list(steps.values()), usage=dict(recorder.usage),
                        timing=timing(state["timing"]["started_at"], finished=finished))
        await store.aput(NAMESPACE, thread_id, snapshot, index=False)

    async def write() -> None:
        while True:
            await changed.wait()
            changed.clear()
            try:
                await save()
            except Exception:
                logger.exception("Could not save intermediate progress for thread %s", thread_id)
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
        cancelled = False
        while not writer.done():
            try:
                await writer
            except asyncio.CancelledError:
                if not writer.done():
                    cancelled = True
            except Exception:
                logger.exception("Progress writer failed for thread %s", thread_id)
                break
        final_save = asyncio.create_task(save(finished=interrupted))
        while not final_save.done():
            try:
                await asyncio.shield(final_save)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                logger.exception("Could not flush final progress for thread %s", thread_id)
                break
        if cancelled and not interrupted:
            raise asyncio.CancelledError
