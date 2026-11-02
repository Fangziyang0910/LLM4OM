"""Concurrent preset edits, immutable run settings and progress after cancellation."""

import asyncio
import datetime
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore

from llm4om.budget import TokenBudget
from llm4om.graph import RunContext, platform_graph, run
from llm4om.llm_presets import LLMPresetStore
from llm4om.methods import Method, methods
from llm4om.progress import NAMESPACE
from llm4om.runtime import LimitExceeded, ModelingState
from llm4om.storage import write_private_json
from tests.conftest import ACCEPT_REVIEW, LLM, PRODUCTION_CODE, TWO_PART_REPLY


def test_concurrent_preset_edits_keep_every_successful_write(tmp_path: Path) -> None:
    def add(_: int) -> str:
        return LLMPresetStore(tmp_path).add(LLM).id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(add, range(24)))
    store = LLMPresetStore(tmp_path)
    assert len(set(ids)) == 24
    assert {preset.id for preset in store.presets()} == set(ids)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(store.delete, ids[::2]))
    assert {preset.id for preset in store.presets()} == set(ids[1::2])


def test_deleted_presets_cannot_be_rebound_by_recreating_the_model(tmp_path: Path) -> None:
    store = LLMPresetStore(tmp_path)
    old = store.add(LLM)
    store.delete(old.id)
    new = LLMPresetStore(tmp_path).add(replace(LLM, temperature=0.9))
    assert new.id != old.id
    with pytest.raises(ValueError, match="No LLM preset"):
        store.find(old.id)
    assert store.find(new.id).settings.temperature == 0.9


def test_corrupt_usage_is_reported_instead_of_resetting_the_budget(tmp_path: Path) -> None:
    path = tmp_path / ".private/token-usage.json"
    path.parent.mkdir()
    path.write_text("{unfinished")
    with pytest.raises(json.JSONDecodeError):
        TokenBudget(tmp_path, daily_limit=100)
    assert path.read_text() == "{unfinished"


def test_failed_atomic_write_keeps_the_previous_file(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / ".private" / "settings.json"
    write_private_json(path, {"value": "before"})

    def fail(*_: Any) -> None:
        raise OSError("disk write failed")

    monkeypatch.setattr("llm4om.storage.os.replace", fail)
    with pytest.raises(OSError, match="disk write failed"):
        write_private_json(path, {"value": "after"})
    assert json.loads(path.read_text()) == {"value": "before"}
    assert list(path.parent.iterdir()) == [path]


def test_concurrent_token_charges_are_persisted_in_count_order(tmp_path: Path) -> None:
    budget = TokenBudget(tmp_path, daily_limit=0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: budget.charge("preset", 10), range(30)))
    budget.flush()
    assert budget.used() == TokenBudget(tmp_path, daily_limit=0).used() == {"preset": 300}


def test_background_budget_write_failures_are_visible(tmp_path: Path, monkeypatch: Any, caplog: Any) -> None:
    def fail(*_: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("llm4om.budget.write_private_json", fail)
    budget = TokenBudget(tmp_path, daily_limit=100)
    budget.charge("preset", 10)
    with pytest.raises(OSError, match="disk full"):
        budget.flush()
    assert "Could not save token usage" in caplog.text and "disk full" in caplog.text
    assert budget.used() == {"preset": 10}
    monkeypatch.setattr("llm4om.budget.write_private_json", write_private_json)
    budget.charge("preset", 5)
    budget.flush()
    assert TokenBudget(tmp_path, daily_limit=100).used() == {"preset": 15}


def test_token_burst_coalesces_and_flush_waits_for_the_latest_snapshot(tmp_path: Path, monkeypatch: Any) -> None:
    entered = [Event(), Event()]
    release = [Event(), Event()]
    snapshots = []

    def write(path: Path, saved: Any) -> None:
        index = len(snapshots)
        snapshots.append(saved)
        entered[index].set()
        assert release[index].wait(5)
        write_private_json(path, saved)

    monkeypatch.setattr("llm4om.budget.write_private_json", write)
    budget = TokenBudget(tmp_path, daily_limit=20)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            budget.charge("preset", 1)
            assert entered[0].wait(5)
            for _ in range(19):
                budget.charge("preset", 1)
            assert budget.used() == {"preset": 20}
            with pytest.raises(LimitExceeded):
                budget.charge("preset")
            waiting = pool.submit(budget.flush)
            release[0].set()
            assert entered[1].wait(5)
            assert json.loads(budget.path.read_text())["tokens"] == {"preset": 1}
            assert not waiting.done()
            release[1].set()
            waiting.result(timeout=5)
        finally:
            for event in release:
                event.set()
    assert [saved["tokens"] for saved in snapshots] == [{"preset": 1}, {"preset": 20}]
    assert TokenBudget(tmp_path, daily_limit=20).used() == {"preset": 20}
    assert budget.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("error", [OSError("disk full"), ValueError("invalid snapshot")])
def test_updates_during_a_failed_write_are_saved_without_another_charge(
    tmp_path: Path, monkeypatch: Any, error: Exception,
) -> None:
    entered, release = Event(), Event()
    snapshots = []

    def write(path: Path, saved: Any) -> None:
        snapshots.append(saved)
        if len(snapshots) == 1:
            entered.set()
            assert release.wait(5)
            raise error
        write_private_json(path, saved)

    monkeypatch.setattr("llm4om.budget.write_private_json", write)
    budget = TokenBudget(tmp_path, daily_limit=0)
    try:
        budget.charge("preset", 1)
        assert entered.wait(5)
        budget.charge("preset", 19)
    finally:
        release.set()
    budget.flush()
    assert [saved["tokens"] for saved in snapshots] == [{"preset": 1}, {"preset": 20}]
    assert TokenBudget(tmp_path, daily_limit=0).used() == {"preset": 20}


def test_new_day_replaces_an_inflight_previous_day_snapshot(tmp_path: Path, monkeypatch: Any) -> None:
    today = datetime.date(2026, 11, 2)

    class Clock:
        @staticmethod
        def today() -> datetime.date:
            return today

    monkeypatch.setattr("llm4om.budget.datetime", SimpleNamespace(date=Clock))
    entered, release = Event(), Event()
    snapshots = []

    def write(path: Path, saved: Any) -> None:
        snapshots.append(saved)
        if len(snapshots) == 1:
            entered.set()
            assert release.wait(5)
        write_private_json(path, saved)

    monkeypatch.setattr("llm4om.budget.write_private_json", write)
    budget = TokenBudget(tmp_path, daily_limit=20)
    try:
        budget.charge("old-preset", 20)
        assert entered.wait(5)
        today += datetime.timedelta(days=1)
        assert budget.used() == {}
        budget.charge("old-preset")
        budget.charge("new-preset", 3)
    finally:
        release.set()
    budget.flush()
    assert [saved["date"] for saved in snapshots] == ["2026-11-02", "2026-11-03"]
    assert json.loads(budget.path.read_text()) == {"date": "2026-11-03", "tokens": {"new-preset": 3}}
    assert TokenBudget(tmp_path, daily_limit=20).used() == {"new-preset": 3}


def test_budget_writer_finishes_on_normal_process_exit(tmp_path: Path) -> None:
    subprocess.run([
        sys.executable, "-c",
        "import sys; from pathlib import Path; from llm4om.budget import TokenBudget; "
        "budget = TokenBudget(Path(sys.argv[1]), 0); "
        "[budget.charge('preset', 1) for _ in range(20)]",
        str(tmp_path),
    ], check=True, timeout=10, capture_output=True, text=True)
    assert TokenBudget(tmp_path, daily_limit=0).used() == {"preset": 20}


def test_every_role_keeps_the_llm_selected_before_modeling(make_resources: Any) -> None:
    broken = TWO_PART_REPLY.replace("return m", "return m.missing")

    def script(role: str, *_: Any) -> str:
        if role == "generate":
            resources.presets.delete(selected.id)
            resources.presets.add(replace(LLM, provider="deepseek", api_key="replacement-key"))
            return broken
        return ACCEPT_REVIEW if role == "review" else TWO_PART_REPLY

    resources = make_resources(script, llm=None)
    selected = resources.presets.add(LLM)
    factory = resources.model_factory
    seen = []

    def model(settings: Any, **kwargs: Any) -> Any:
        seen.append(settings)
        return factory(settings, **kwargs)

    resources.model_factory = model
    result = asyncio.run(run("test", method="feedback_repair", resources=resources))
    assert result["solve"]["objective"] == 13
    assert len(seen) == 3 and all(settings == LLM for settings in seen)
    assert result["spec"]["llm"] == LLM.public()
    assert result["spec"]["parameters"] == {"max_repairs": 3}
    assert LLM.api_key not in json.dumps(result) and "api_key" not in result["spec"]["llm"]


def test_cancelled_model_keeps_completed_artifacts_in_the_store(make_resources: Any) -> None:
    async def check() -> None:
        waiting = asyncio.Event()

        async def pause(_: ModelingState) -> None:
            waiting.set()
            await asyncio.Event().wait()

        def method_graph() -> Any:
            builder = StateGraph(ModelingState)
            builder.add_node("draft", lambda _: {"formulation": "partial model", "code": PRODUCTION_CODE})
            builder.add_node("pause", pause)
            builder.add_edge(START, "draft")
            builder.add_edge("draft", "pause")
            builder.add_edge("pause", END)
            return builder.compile()

        graph = platform_graph(Method("test", "test", "test", method_graph, titles={"draft": "Draft"}))
        graph.checkpointer, graph.store = InMemorySaver(), InMemoryStore()
        config = {"configurable": {"thread_id": "cancelled", "llm4om_resources": make_resources(lambda *_: TWO_PART_REPLY)}}
        task = asyncio.create_task(graph.ainvoke({"description": "test"}, config, context=RunContext()))
        await asyncio.wait_for(waiting.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        saved = await graph.store.aget(NAMESPACE, "cancelled")
        assert saved is not None
        assert saved.value["formulation"] == "partial model" and saved.value["code"] == PRODUCTION_CODE
        assert saved.value["steps"][0]["title"] == "Draft" and saved.value["timing"]["finished_at"]
        assert LLM.api_key not in json.dumps(saved.value)

    asyncio.run(check())


def test_completed_run_owns_its_timing_and_clears_temporary_progress(make_resources: Any) -> None:
    async def check() -> None:
        graph = platform_graph(methods()["direct"])
        graph.checkpointer, graph.store = InMemorySaver(), InMemoryStore()
        config = {"configurable": {"thread_id": "complete", "llm4om_resources": make_resources(lambda *_: TWO_PART_REPLY)}}
        result = await graph.ainvoke({"description": "test"}, config, context=RunContext())
        assert result["solve"]["objective"] == 13
        timing = result["timing"]
        assert timing["elapsed"] == pytest.approx(timing["finished_at"] - timing["started_at"])
        assert timing["elapsed"] > 0 and await graph.store.aget(NAMESPACE, "complete") is None

    asyncio.run(check())
