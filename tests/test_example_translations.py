"""Example translations preserve their source and reuse paid results across app instances."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from llm4om.budget import TokenBudget
from llm4om.llm_presets import LLMPresetStore
from llm4om.server.app import create_app
from llm4om.server.translations import ExampleTranslations
from tests.conftest import LLM

SOURCE = "Ship 10 whole packages from A to B at $2 each. Minimize cost."
TRANSLATION = "从 A 向 B 运输 10 个整包，每包费用为 $2。使成本最小。"
URL = "/api/datasets/nl4opt/translation"
BODY = {"case_id": "sample-1", "locale": "zh"}


def reply(text: str) -> AIMessage:
    return AIMessage(text, usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: Any) -> Any:
    def cases(dataset: str) -> list[dict[str, str]]:
        if dataset != "nl4opt":
            raise KeyError(dataset)
        return [{"case_id": "sample-1", "sample_id": "1", "subset": "nl4opt", "description": SOURCE}]

    monkeypatch.setattr("llm4om.server.examples._cases", cases)
    invoke = AsyncMock(return_value=reply(TRANSLATION))
    monkeypatch.setattr("llm4om.llm.chat_model", lambda *args, **kwargs: SimpleNamespace(ainvoke=invoke))
    store = LLMPresetStore(tmp_path)
    preset = store.add(LLM)
    budget = TokenBudget(tmp_path, daily_limit=15)
    yield SimpleNamespace(store=store, preset=preset, budget=budget, invoke=invoke, path=tmp_path)
    budget.flush()


def test_translation_preserves_source_and_reuses_cache_after_restart(setup: Any) -> None:
    with TestClient(create_app(setup.store, setup.budget)) as api:
        first = api.post(URL, json=BODY)
        original = api.get("/api/datasets/nl4opt").json()["cases"][0]["description"]
    assert first.status_code == 200
    assert first.json()["original"] == original == SOURCE
    assert first.json()["translation"] == TRANSLATION
    assert first.json()["cached"] is False
    assert setup.budget.used() == {setup.preset.id: 15}

    with TestClient(create_app(setup.store, setup.budget)) as api:
        cached = api.post(URL, json=BODY)
    assert cached.status_code == 200 and cached.json()["cached"] is True
    assert cached.json()["translation"] == TRANSLATION
    assert setup.invoke.await_count == 1
    messages = setup.invoke.await_args.args[0]
    assert SOURCE in messages[-1].content
    assert LLM.api_key not in str(messages) + str(first.json()) + str(cached.json())
    cache_files = list((setup.path / ".private" / "translations").glob("*.json"))
    assert cache_files and all(LLM.api_key not in path.read_text(encoding="utf-8") for path in cache_files)


def test_cached_translations_read_through_an_unrelated_paid_call(setup: Any) -> None:
    async def check() -> None:
        translations = ExampleTranslations(setup.store, setup.budget)
        setup.budget.daily_limit = 0
        await translations.translate(SOURCE, "zh")
        started, finish = asyncio.Event(), asyncio.Event()

        async def slow_reply(_: Any) -> AIMessage:
            started.set()
            await finish.wait()
            return reply("第二题")

        setup.invoke.side_effect = slow_reply
        slow = asyncio.create_task(translations.translate("another case", "zh"))
        await asyncio.wait_for(started.wait(), 2)
        duplicate = asyncio.create_task(translations.translate("another case", "zh"))
        try:
            hit = await asyncio.wait_for(translations.translate(SOURCE, "zh"), 1)
            assert hit["cached"] and hit["translation"] == TRANSLATION
        finally:
            finish.set()
            first, second = await asyncio.gather(slow, duplicate)
        assert not first["cached"] and second["cached"]
        assert setup.invoke.await_count == 2 and setup.budget.used() == {setup.preset.id: 30}

    asyncio.run(check())


def test_empty_translation_is_not_cached_but_accounts_for_the_call(setup: Any) -> None:
    setup.invoke.return_value = reply("   ")
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json=BODY)
    assert response.status_code == 502
    assert setup.budget.used() == {setup.preset.id: 15}
    assert not list((setup.path / ".private" / "translations").glob("*.json"))


def test_uncached_translation_respects_the_daily_budget(setup: Any) -> None:
    setup.budget.charge(setup.preset.id, 15)
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json=BODY)
    assert response.status_code == 429
    setup.invoke.assert_not_awaited()


def test_translation_validates_the_case_and_language_before_calling_a_model(setup: Any) -> None:
    with TestClient(create_app(setup.store, setup.budget)) as api:
        missing = api.post(URL, json={**BODY, "case_id": "missing"})
        unknown = api.post("/api/datasets/unknown/translation", json=BODY)
        language = api.post(URL, json={**BODY, "locale": "fr"})
    assert [missing.status_code, unknown.status_code, language.status_code] == [404, 404, 422]
    setup.invoke.assert_not_awaited()


def test_translation_errors_do_not_expose_credentials_or_cache_failures(setup: Any) -> None:
    setup.invoke.side_effect = RuntimeError("provider failed with " + LLM.api_key)
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json=BODY)
    assert response.status_code == 502 and LLM.api_key not in response.text
    assert not list((setup.path / ".private" / "translations").glob("*.json"))


def test_translation_cache_is_invalidated_when_the_source_changes(setup: Any, monkeypatch: Any) -> None:
    setup.budget.daily_limit = 0
    with TestClient(create_app(setup.store, setup.budget)) as api:
        first = api.post(URL, json=BODY)
        changed = SOURCE.replace("10", "12")
        monkeypatch.setattr("llm4om.server.examples._cases", lambda _: [
            {"case_id": "sample-1", "sample_id": "1", "subset": "nl4opt", "description": changed}])
        setup.invoke.return_value = reply(TRANSLATION.replace("10", "12"))
        second = api.post(URL, json=BODY)
    assert first.status_code == second.status_code == 200
    assert second.json()["cached"] is False
    assert second.json()["original"] == changed
    assert first.json()["source_hash"] != second.json()["source_hash"]
    assert setup.invoke.await_count == 2


def test_translation_cache_is_invalidated_when_translation_rules_change(setup: Any, monkeypatch: Any) -> None:
    from llm4om.server import translations

    setup.budget.daily_limit = 0
    with TestClient(create_app(setup.store, setup.budget)) as api:
        first = api.post(URL, json=BODY)
        monkeypatch.setattr(translations, "INSTRUCTIONS", translations.INSTRUCTIONS + "\nPreserve per-item unit bases.")
        second = api.post(URL, json=BODY)
    assert first.status_code == second.status_code == 200
    assert second.json()["cached"] is False
    assert first.json()["source_hash"] == second.json()["source_hash"]
    assert setup.invoke.await_count == 2


def test_translation_only_requests_prose_and_table_text_without_rejecting_number_word_styles(
    setup: Any, monkeypatch: Any,
) -> None:
    original = "Finish in the 8th week with two workers. Formula: $x=10$. Code: `x[0]`.\n\n| Week | Demand |\n|---|---|\n| 8 | 1000 |"
    translated = "在第8周由2名工人完成。公式：$x=10$。代码：`x[0]`。\n\n| 周 | 需求 |\n|---|---|\n| 8 | 1000 |"
    monkeypatch.setattr("llm4om.server.examples._cases", lambda _: [
        {"case_id": "sample-1", "sample_id": "1", "subset": "nl4opt", "description": original}])
    setup.invoke.return_value = reply(translated)
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json=BODY)
    assert response.status_code == 200
    assert response.json()["original"] == original
    assert response.json()["translation"] == translated
    assert setup.invoke.await_count == 1
    instruction, source = setup.invoke.await_args.args[0]
    assert "natural language" in instruction.text and "table" in instruction.text
    assert "formulas" in instruction.text and "code" in instruction.text
    assert source.text == original


def test_reading_translation_reuses_example_cache_and_preserves_source(setup: Any) -> None:
    with TestClient(create_app(setup.store, setup.budget)) as api:
        first = api.post("/api/translations", json={"text": SOURCE, "locale": "zh"})
        cached = api.post(URL, json=BODY)
    assert first.status_code == cached.status_code == 200
    assert first.json()["original"] == SOURCE
    assert first.json()["translation"] == TRANSLATION
    assert cached.json()["cached"] is True
    assert setup.invoke.await_count == 1


@pytest.mark.parametrize("text", ["", " " * 10, "x" * 100001], ids=["empty", "whitespace", "too-long"])
def test_reading_translation_rejects_empty_or_oversized_text(setup: Any, text: str) -> None:
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post("/api/translations", json={"text": text, "locale": "zh"})
    assert response.status_code in {400, 422}
    setup.invoke.assert_not_awaited()
