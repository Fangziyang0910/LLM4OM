"""Optional conflict diagnosis must preserve the solver result, even when timer setup or cleanup fails."""

import asyncio
import os
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from llm4om.sandbox import Sandbox, SolveResult, worker
from tests.conftest import PRODUCTION_CODE


def diagnostic_run(monkeypatch: pytest.MonkeyPatch, *, missing: str | None = None,
                   failure: str | None = None) -> tuple[dict[str, Any], list[str]]:
    events: list[str] = []
    previous = object()

    def event(name: str) -> None:
        events.append(name)
        if failure == name:
            raise RuntimeError(f"{name} failed")

    def handler(signum: int, callback: Any) -> Any:
        assert signum == 14
        event("restore" if callback is previous else "install")
        return previous

    def alarm(seconds: int) -> None:
        assert seconds in (0, worker.IIS_TIME_LIMIT + 5)
        event("cancel" if seconds == 0 else "start")

    def conflict(model: object) -> list[str]:
        event("find")
        return ["cutting <= 8", "needA >= 9"]

    signals = SimpleNamespace(SIGALRM=14, signal=handler, alarm=alarm)
    if missing:
        delattr(signals, missing)
    monkeypatch.setitem(sys.modules, "signal", signals)

    selection = worker.Selection(object(), "test-solver", lambda _: ("infeasible", None, None),
                                 ("test conflicts", conflict))
    library = SimpleNamespace(recognize=lambda model, backend: selection)
    monkeypatch.setitem(worker.LIBRARIES, "test-library", library)
    result = worker.run({"language": "test-library", "solver": "AUTO", "time_limit": 1,
                         "code": "def build_model(data):\n    return object()\n", "data": {}})
    return result, events


def assert_infeasible(result: dict[str, Any]) -> None:
    assert result["status"] == "infeasible"
    assert result["error"] is None
    assert result["objective"] is None and result["variables"] == {}
    assert result["solver"] == "test-solver"
    assert SolveResult(**result).executed
    assert "test conflicts" not in SolveResult(**result).feedback()


@pytest.mark.parametrize("missing", ["SIGALRM", "alarm"])
def test_missing_timer_api_preserves_infeasibility(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    result, events = diagnostic_run(monkeypatch, missing=missing)

    assert_infeasible(result)
    assert result["diagnosis"]["items"] == [] and result["diagnosis"]["total"] == 0
    assert missing in result["diagnosis"]["error"]
    assert events == ([] if missing == "SIGALRM" else ["install", "restore"])


@pytest.mark.parametrize("failure,events", [
    ("install", ["install"]),
    ("start", ["install", "start", "restore"]),
    ("find", ["install", "start", "find", "cancel", "restore"]),
    ("cancel", ["install", "start", "find", "cancel", "restore"]),
    ("restore", ["install", "start", "find", "cancel", "restore"]),
])
def test_diagnostic_failures_preserve_infeasibility_and_restore_resources(
    monkeypatch: pytest.MonkeyPatch, failure: str, events: list[str],
) -> None:
    result, actual = diagnostic_run(monkeypatch, failure=failure)

    assert_infeasible(result)
    assert result["diagnosis"] == {"tool": "test conflicts", "items": [], "total": 0, "error": f"{failure} failed"}
    assert actual == events


def test_supported_diagnosis_keeps_conflicts_and_clears_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    result, events = diagnostic_run(monkeypatch)

    assert_infeasible(result)
    assert result["diagnosis"] == {"tool": "test conflicts", "items": ["cutting <= 8", "needA >= 9"],
                                   "total": 2, "error": None}
    assert events == ["install", "start", "find", "cancel", "restore"]


@pytest.mark.skipif(os.environ.get("LLM4OM_TEST_DOCKER") != "1", reason="set LLM4OM_TEST_DOCKER=1 to run Docker")
def test_docker_infeasible_model_retains_conflict_diagnosis() -> None:
    result = asyncio.run(Sandbox("docker").solve(PRODUCTION_CODE.replace("<= 8)", "<= -8)", 1),
                                               {}, "pyomo", 10, solver="highs"))

    assert result.status == "infeasible" and result.error is None, result.error
    assert result.diagnosis is not None
    assert result.diagnosis["error"] is None, result.diagnosis
    assert result.diagnosis["total"] == len(result.diagnosis["items"]) >= 1
