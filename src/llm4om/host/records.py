"""Local execution evidence next to LangGraph's checkpoints; no model credentials or server."""

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from langgraph.runtime import get_runtime

from llm4om.runtime import LimitExceeded, Limits, Recorder
from llm4om.sandbox import SolveResult


class Records:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        # Synchronous progress callbacks must not wait on the async checkpointer's transaction.
        self.db = sqlite3.connect(directory / "records.sqlite", isolation_level=None, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS host_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS host_operations
                (id TEXT PRIMARY KEY, kind TEXT NOT NULL, request TEXT NOT NULL, result TEXT);
            CREATE TABLE IF NOT EXISTS host_steps (id TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.recorder: Recorder

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM host_meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value: Any) -> None:
        self.db.execute("INSERT INTO host_meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)))

    def restore(self, limits: Limits) -> Recorder:
        usage = dict(self.db.execute("SELECT kind, count(*) FROM host_operations GROUP BY kind"))
        self.recorder = Recorder(limits, {"llm_calls": usage.get("llm", 0), "solves": usage.get("solve", 0)},
                                 emit=self.event)
        self.recorder.steps = {id: json.loads(value) for id, value in self.db.execute(
            "SELECT id, value FROM host_steps ORDER BY rowid")}
        return self.recorder

    def event(self, event: dict[str, Any]) -> None:
        if step := event.get("step"):
            self.db.execute("INSERT INTO host_steps VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                            (step["id"], json.dumps(step, ensure_ascii=False)))

    def begin(self, kind: str, request: dict[str, Any]) -> tuple[str, Any]:
        info = get_runtime().execution_info
        if info is None:
            raise RuntimeError("Host operations must run inside a LangGraph task.")
        id = info.task_id
        row = self.db.execute("SELECT result FROM host_operations WHERE id = ?", (id,)).fetchone()
        if row:
            return id, json.loads(row[0]) if row[0] is not None else None
        if kind in {"llm", "solve"}:
            try:
                self.recorder.count("llm_calls" if kind == "llm" else "solves")
            except LimitExceeded as error:
                # A sibling interrupt can otherwise hide an exhausted parallel batch's exception.
                self.put("failure", str(error))
                raise
        summary = {key: request[key] for key in ("code", "title", "role") if key in request}
        self.db.execute("INSERT INTO host_operations VALUES (?, ?, ?, NULL)",
                        (id, kind, json.dumps(summary, ensure_ascii=False)))
        if kind == "llm":
            self.recorder.step("llm", request["role"], id=id, running=True)
        elif kind == "solve":
            self.recorder.step("solve", request["title"], id=id, code=request["code"], running=True)
        return id, None

    def complete(self, id: str, value: Any) -> None:
        self.db.execute("UPDATE host_operations SET result = ? WHERE id = ?",
                        (json.dumps(value, ensure_ascii=False), id))

    def solved(self) -> dict[str, SolveResult]:
        return {json.loads(request)["code"]: SolveResult(**json.loads(result))
                for request, result in self.db.execute(
                    "SELECT request, result FROM host_operations WHERE kind = 'solve' AND result IS NOT NULL ORDER BY rowid")}

    async def execute(self, context: Any, code: str, title: str) -> SolveResult:
        id, cached = self.begin("solve", {"code": code, "title": title})
        if cached is not None:
            return SolveResult(**cached)
        started = time.monotonic()
        try:
            result = await context.sandbox.solve(code, context.data, context.target.language,
                                                 self.recorder.limits.solve_time_limit, solver=context.target.solver)
        except BaseException as error:
            self.recorder.step("solve", title, f"{type(error).__name__}: {error}", id=id, running=False, failed=True)
            raise
        self.complete(id, asdict(result))
        self.recorder.step("solve", title, result.feedback(), id=id, running=False,
                           seconds=round(time.monotonic() - started, 1), status=result.status, objective=result.objective)
        return result


@contextmanager
def open_records(directory: Path) -> Iterator[Records]:
    """SQLite releases this cross-platform session lock even after a killed CLI process."""
    if not (directory / "records.sqlite").is_file():
        raise ValueError(f"No host session at {directory}.")
    lock = sqlite3.connect(directory / ".lock.sqlite", timeout=0)
    try:
        try:
            lock.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            raise ValueError("This host session is already in use. Wait for its current command to finish.") from error
        records = Records(directory)
        try:
            yield records
        finally:
            records.db.close()
    finally:
        lock.close()
