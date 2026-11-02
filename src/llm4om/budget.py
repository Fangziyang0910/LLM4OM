"""Daily token accounting shared by the runs of one service."""

import datetime
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from llm4om.runtime import LimitExceeded
from llm4om.storage import write_private_json

logger = logging.getLogger(__name__)


class TokenBudget:
    """The tokens each LLM preset may use per day across all runs; 0 means no limit. Usage is counted either way.

    The day's counts live in `<workspace>/.private/token-usage.json`, so they survive restarts; a new day starts at
    zero. A run stops at the first LLM call after its preset's budget is spent, so the last call can overshoot it.
    The counts are read once and kept in memory; a background writer saves them, because LLM callbacks run on the
    server's event loop, where file I/O is not allowed.
    """

    def __init__(self, workspace: Path, daily_limit: int) -> None:
        self.path = workspace / ".private" / "token-usage.json"
        self.daily_limit = daily_limit
        self._condition = threading.Condition()  # held only while the counts or writer state change
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="token-usage")  # writes in order
        self._generation = 0  # the number of the latest count change
        self._persisted = 0  # the latest generation known to be on disk
        self._draining = False  # a drain task is queued or running
        self._failure: Exception | None = None  # the last persistence failure not covered by a saved snapshot
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self._day, self._tokens = saved["date"], dict(saved["tokens"])
        except FileNotFoundError:
            self._day, self._tokens = "", {}

    def used(self) -> dict[str, int]:
        """Tokens used today, by preset id."""
        with self._condition:
            return dict(self._tokens) if self._day == datetime.date.today().isoformat() else {}

    def charge(self, preset: str, tokens: int = 0) -> None:
        """Add `tokens` to the preset's count. With none, check it: raises LimitExceeded once the budget is spent."""
        if not tokens:
            if self.daily_limit and self.used().get(preset, 0) >= self.daily_limit:
                raise LimitExceeded(f"The LLM preset {preset!r} used its daily budget of {self.daily_limit:,} "
                                    "tokens. Choose another preset or try again tomorrow.")
            return
        with self._condition:
            today = datetime.date.today().isoformat()
            if self._day != today:
                self._day, self._tokens = today, {}
            self._tokens[preset] = self._tokens.get(preset, 0) + tokens
            self._generation += 1
            if not self._draining:
                self._schedule()

    def _schedule(self) -> None:
        """Queue the single drain task; the caller holds the lock."""
        self._draining = True
        try:
            self._writer.submit(self._drain)
        except Exception as error:
            self._draining = False
            self._failure = error
            self._condition.notify_all()
            raise

    def _drain(self) -> None:
        """Write the latest counts until they are on disk, then exit."""
        while True:
            with self._condition:
                if self._persisted == self._generation:
                    self._draining = False
                    self._condition.notify_all()
                    return
                saved = {"date": self._day, "tokens": dict(self._tokens)}
                generation = self._generation
            try:
                write_private_json(self.path, saved)
            except Exception as error:
                logger.exception("Could not save token usage to %s", self.path)
                with self._condition:
                    self._failure = error
                    if generation == self._generation:
                        # No newer counts are waiting; keep them dirty and report the failure.
                        self._draining = False
                        self._condition.notify_all()
                        return
            else:
                with self._condition:
                    self._persisted = generation
                    self._failure = None
                    self._condition.notify_all()

    def flush(self) -> None:
        """Wait until every count charged before this call is written."""
        with self._condition:
            target = self._generation
            while self._persisted < target:
                if not self._draining:
                    if self._failure is not None:
                        raise self._failure
                    raise RuntimeError("The token usage writer stopped before saving the latest counts")
                self._condition.wait()
