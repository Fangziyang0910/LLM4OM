"""Display translations are ordered, cached per label and never replace saved source data."""

import asyncio
import json
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

URL = "/api/display-translations"


def reply(content: str) -> AIMessage:
    return AIMessage(content, usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: Any) -> Any:
    invoke = AsyncMock(return_value=reply('["最大利润", "CNY/包"]'))
    monkeypatch.setattr("llm4om.llm.chat_model", lambda *args, **kwargs: SimpleNamespace(ainvoke=invoke))
    store = LLMPresetStore(tmp_path)
    preset = store.add(LLM)
    budget = TokenBudget(tmp_path, daily_limit=0)
    yield SimpleNamespace(store=store, preset=preset, budget=budget, invoke=invoke, path=tmp_path)
    budget.flush()


def cache_files(setup: Any) -> list[Path]:
    return list((setup.path / ".private" / "translations").glob("*.json"))


def test_batch_deduplicates_and_returns_ordered_source_and_cache_flags(setup: Any) -> None:
    texts = ["Maximum profit", "CNY/package", "Maximum profit"]
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json={"texts": texts, "locale": "zh"})
    assert response.status_code == 200
    assert response.json() == {"locale": "zh", "items": [
        {"original": texts[0], "translation": "最大利润", "cached": False},
        {"original": texts[1], "translation": "CNY/包", "cached": False},
        {"original": texts[2], "translation": "最大利润", "cached": False},
    ]}
    assert setup.invoke.await_count == 1
    system, human = setup.invoke.await_args.args[0]
    assert json.loads(human.text) == texts[:2]
    assert "identifiers" in system.text and "numerical" in system.text and "abbreviations" in system.text
    assert "JSON" in system.text and "Simplified Chinese" in system.text
    assert setup.budget.used() == {setup.preset.id: 15}
    assert len(cache_files(setup)) == 2
    assert LLM.api_key not in str(response.json()) + str([system, human])
    assert all(LLM.api_key not in path.read_text(encoding="utf-8") for path in cache_files(setup))


def test_cached_labels_survive_restart_and_do_not_spend_a_used_budget(setup: Any) -> None:
    body = {"texts": ["Maximum profit", "CNY/package"], "locale": "zh"}
    with TestClient(create_app(setup.store, setup.budget)) as api:
        assert api.post(URL, json=body).status_code == 200
    setup.budget.daily_limit = 15
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json={**body, "texts": list(reversed(body["texts"]))})
    assert response.status_code == 200
    assert [item["translation"] for item in response.json()["items"]] == ["CNY/包", "最大利润"]
    assert all(item["cached"] for item in response.json()["items"])
    assert setup.invoke.await_count == 1 and setup.budget.used() == {setup.preset.id: 15}


def test_mixed_batch_requests_only_new_unique_labels(setup: Any) -> None:
    with TestClient(create_app(setup.store, setup.budget)) as api:
        assert api.post(URL, json={"texts": ["Maximum profit", "CNY/package"], "locale": "zh"}).status_code == 200
        setup.invoke.return_value = reply('["运输费用"]')
        response = api.post(URL, json={"texts": ["Maximum profit", "Shipping cost", "Shipping cost"], "locale": "zh"})
    assert response.status_code == 200
    assert [item["cached"] for item in response.json()["items"]] == [True, False, False]
    assert [item["translation"] for item in response.json()["items"]] == ["最大利润", "运输费用", "运输费用"]
    assert json.loads(setup.invoke.await_args.args[0][-1].text) == ["Shipping cost"]
    assert setup.invoke.await_count == 2 and setup.budget.used() == {setup.preset.id: 30}


@pytest.mark.parametrize("content", [
    "not JSON", '{"translations":["甲","乙"]}', '["甲"]', '["甲", "乙", "丙"]',
    '["甲", " "]', '["甲", null]', '["甲", 2]', '```json\n["甲", "乙"]\n```',
])
def test_invalid_batch_response_does_not_cache_any_label(setup: Any, content: str) -> None:
    setup.invoke.return_value = reply(content)
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json={"texts": ["First title", "Second title"], "locale": "zh"})
    assert response.status_code == 502
    assert setup.invoke.await_count == 1
    assert setup.budget.used() == {setup.preset.id: 15}
    assert not cache_files(setup)


def test_provider_failure_is_generic_and_retry_keeps_original_input(setup: Any) -> None:
    setup.invoke.side_effect = RuntimeError("provider failed with " + LLM.api_key)
    body = {"texts": ["Maximum profit", "CNY/package"], "locale": "zh"}
    with TestClient(create_app(setup.store, setup.budget)) as api:
        failed = api.post(URL, json=body)
        assert failed.status_code == 502 and LLM.api_key not in failed.text
        assert not cache_files(setup)
        setup.invoke.side_effect = None
        retry = api.post(URL, json=body)
    assert retry.status_code == 200
    assert [item["original"] for item in retry.json()["items"]] == body["texts"]
    assert setup.invoke.await_count == 2


def test_uncached_display_batch_obeys_budget_before_calling_model(setup: Any) -> None:
    setup.budget.daily_limit = 15
    setup.budget.charge(setup.preset.id, 15)
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json={"texts": ["Title"], "locale": "en"})
    assert response.status_code == 429
    setup.invoke.assert_not_awaited()


@pytest.mark.parametrize("body", [
    {"texts": ["x"] * 21, "locale": "zh"}, {"texts": [""], "locale": "zh"},
    {"texts": [" "], "locale": "zh"}, {"texts": ["x" * 1001], "locale": "zh"},
    {"texts": [2], "locale": "zh"}, {"texts": ["Title"], "locale": "fr"},
])
def test_invalid_input_never_calls_model(setup: Any, body: dict[str, Any]) -> None:
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json=body)
    assert response.status_code in {400, 422}
    setup.invoke.assert_not_awaited()


def test_empty_batch_is_free_and_does_not_require_a_preset(tmp_path: Path) -> None:
    with TestClient(create_app(LLMPresetStore(tmp_path))) as api:
        response = api.post(URL, json={"texts": [], "locale": "en"})
    assert response.status_code == 200 and response.json() == {"locale": "en", "items": []}


def test_display_cache_is_separate_from_reading_locale_and_rule_changes(setup: Any, monkeypatch: Any) -> None:
    from llm4om.server import translations

    with TestClient(create_app(setup.store, setup.budget)) as api:
        setup.invoke.return_value = reply("正文译文")
        assert api.post("/api/translations", json={"text": "Title", "locale": "zh"}).status_code == 200
        setup.invoke.return_value = reply('["标题"]')
        first = api.post(URL, json={"texts": ["Title"], "locale": "zh"})
        setup.invoke.return_value = reply('["Title"]')
        english = api.post(URL, json={"texts": ["Title"], "locale": "en"})
        monkeypatch.setattr(translations, "DISPLAY_INSTRUCTIONS", translations.DISPLAY_INSTRUCTIONS + "\nKeep short labels.")
        changed = api.post(URL, json={"texts": ["Title"], "locale": "en"})
    assert all(response.status_code == 200 for response in [first, english, changed])
    assert all(not response.json()["items"][0]["cached"] for response in [first, english, changed])
    assert setup.invoke.await_count == 4


def test_concurrent_duplicate_batches_share_one_paid_call(setup: Any) -> None:
    async def check() -> list[dict[str, Any]]:
        translations = ExampleTranslations(setup.store, setup.budget)
        return await asyncio.gather(translations.translate_display(["Maximum profit", "CNY/package"], "zh"),
                                    translations.translate_display(["Maximum profit"], "zh"))

    first, second = asyncio.run(check())
    assert first["items"][0]["cached"] is False and second["items"][0]["cached"] is True
    assert setup.invoke.await_count == 1


def test_maximum_valid_batch_preserves_exact_input_strings(setup: Any) -> None:
    texts = [str(index) + "x" * (1000 - len(str(index))) for index in range(20)]
    setup.invoke.return_value = reply(json.dumps([f"标题 {index}" for index in range(20)]))
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json={"texts": texts, "locale": "zh"})
    assert response.status_code == 200
    assert [item["original"] for item in response.json()["items"]] == texts
    assert setup.invoke.await_count == 1


@pytest.mark.parametrize("operation", ["read", "write"])
def test_cache_io_failure_does_not_expose_private_details(setup: Any, monkeypatch: Any, operation: str) -> None:
    def fail(*args: Any) -> None:
        raise OSError("private-path/" + LLM.api_key)

    if operation == "read":
        monkeypatch.setattr(ExampleTranslations, "_read", fail)
    else:
        monkeypatch.setattr("llm4om.server.translations.write_private_json", fail)
    with TestClient(create_app(setup.store, setup.budget)) as api:
        response = api.post(URL, json={"texts": ["Maximum profit", "CNY/package"], "locale": "zh"})
    assert response.status_code == 503
    assert LLM.api_key not in response.text and "private-path" not in response.text
    assert not cache_files(setup)
