"""Cooperative cancellation; only owned resource children are terminated."""

import asyncio
from pathlib import Path
from threading import Event
from typing import Any, Coroutine, TypeVar

from llm4om.contracts import RunError, parse_json


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()
        self._path: Path | None = None
        self._identity: dict[str, Any] | None = None

    def bind(self, path: Path, identity: dict[str, Any]) -> None:
        if self._path is not None:
            raise RunError("control_incompatible", "control", "A cancellation token belongs to only one run owner.")
        self._path, self._identity = path, identity

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        if self._event.is_set():
            return True
        if self._path is not None and self._path.exists():
            value = parse_json(self._path.read_bytes())
            if value != self._identity:
                raise RunError("control_incompatible", "control", "Cancellation identity differs from the active owner.")
            return True
        return False

    def check(self) -> None:
        if self.cancelled:
            raise RunError("run_cancelled", "control", "The run was cancelled.")


_Result = TypeVar("_Result")


async def _supervise(work: Coroutine[Any, Any, _Result], cancellation: CancellationToken) -> _Result:
    pending = asyncio.create_task(work)
    try:
        while not pending.done():
            cancellation.check()
            await asyncio.sleep(0.05)
        return await pending
    finally:
        if not pending.done():
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
