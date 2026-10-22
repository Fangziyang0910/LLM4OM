"""Daily token accounting shared by the runs of one service."""

import datetime
import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from llm4om.runtime import LimitExceeded
from llm4om.storage import write_private_json

logger = logging.getLogger(__name__)


class TokenBudget:
    """The tokens each LLM preset may use per day across all runs; 0 means no limit. Usage is counted either way.

    The day's counts live in `<workspace>/.private/token-usage.json`, so they survive restarts; a new day starts at
    zero. A run stops at the first LLM call after its preset's budget is spent, so the last call can overshoot it.
    The counts are read once and kept in memory; a background thread writes them, because LLM callbacks run on the
    server's event loop, where file I/O is not allowed.
    """

    def __init__(self, workspace: Path, daily_limit: int) -> None:
        self.path = workspace / ".private" / "token-usage.json"
        self.daily_limit = daily_limit
        self._lock = threading.Lock()  # held only while the counts change, never during file I/O
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="token-usage")  # writes in order
        self._pending: Future[None] | None = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self._day, self._tokens = saved["date"], dict(saved["tokens"])
        except FileNotFoundError:
            self._day, self._tokens = "", {}

    def used(self) -> dict[str, int]:
        """Tokens used today, by preset id."""
        with self._lock:
            return dict(self._tokens) if self._day == datetime.date.today().isoformat() else {}

    def charge(self, preset: str, tokens: int = 0) -> None:
        """Add `tokens` to the preset's count. With none, check it: raises LimitExceeded once the budget is spent."""
        if not tokens:
            if self.daily_limit and self.used().get(preset, 0) >= self.daily_limit:
                raise LimitExceeded(f"The LLM preset {preset!r} used its daily budget of {self.daily_limit:,} "
                                    "tokens. Choose another preset or try again tomorrow.")
            return
        today = datetime.date.today().isoformat()
        with self._lock:
            if self._day != today:
                self._day, self._tokens = today, {}
            self._tokens[preset] = self._tokens.get(preset, 0) + tokens
            saved = {"date": today, "tokens": dict(self._tokens)}
            self._pending = self._writer.submit(self._write, saved)

    def _write(self, saved: dict) -> None:
        try:
            write_private_json(self.path, saved)
        except OSError:
            logger.exception("Could not save token usage to %s", self.path)
            raise

    def flush(self) -> None:
        """Wait until every count is written."""
        with self._lock:
            pending = self._pending
        if pending:
            pending.result()
