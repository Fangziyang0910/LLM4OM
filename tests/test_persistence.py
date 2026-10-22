"""Concurrent preset edits, immutable run settings and progress after cancellation."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
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
from llm4om.runtime import ModelingState
from llm4om.storage import write_private_json
from tests.conftest import LLM, PRODUCTION_CODE, TWO_PART_REPLY


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


def test_every_role_keeps_the_llm_selected_before_modeling(make_resources: Any) -> None:
    broken = TWO_PART_REPLY.replace("return m", "return m.missing")

    def script(role: str, *_: Any) -> str:
        if role == "generate":
            resources.presets.delete(selected.id)
            resources.presets.add(replace(LLM, provider="deepseek", api_key="replacement-key"))
            return broken
        return TWO_PART_REPLY

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
    assert len(seen) == 2 and all(settings == LLM for settings in seen)
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
