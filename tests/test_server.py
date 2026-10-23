"""The routes beside the LangGraph API, and the graphs the server registers."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from llm4om.budget import TokenBudget
from llm4om.graph import run
from llm4om.llm_presets import LLMPresetStore
from llm4om.methods import methods
from llm4om.server.app import create_app
from tests.conftest import LLM, PRODUCTION_PROBLEM, TWO_PART_REPLY


def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(LLMPresetStore(tmp_path)))


PRESET = {"provider": LLM.provider, "model": LLM.model, "api_key": LLM.api_key, "base_url": LLM.base_url}


def add_preset(api: TestClient) -> dict[str, Any]:
    response = api.post("/api/presets", json=PRESET)
    assert response.status_code == 200
    return response.json()


def test_options_list_methods_languages_and_providers(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        options = api.get("/api/options").json()
    assert {"direct", "trival", "optimus", "coe", "optitree", "or_llm_agent", "autoformulation"} <= {m["id"] for m in options["methods"]}
    assert {item["id"] for item in options["languages"]} == {
        "pyomo", "gurobipy", "ortools", "cpmpy", "pulp", "cvxpy", "pyscipopt", "casadi", "coptpy",
    }
    optimus = next(m for m in options["methods"] if m["id"] == "optimus")
    assert optimus["languages"] is None and optimus["linear_only"]
    assert all(item["languages"] is None for item in options["methods"])
    assert all('interfaces' not in item and item['solver'] == 'AUTO' for item in options['languages'])


def test_presets_never_return_their_keys_and_cannot_be_changed(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        add_preset(api)
        listed = add_preset(api)  # the same settings again become a second preset, not an update
        changes = [api.put("/api/presets/scripted", json=PRESET).status_code,
                   api.patch("/api/presets/scripted", json=PRESET).status_code]
    assert len({item["id"] for item in listed["presets"]}) == 2
    assert LLM.api_key not in str(listed) and all("api_key" not in item for item in listed["presets"])
    assert changes == [405, 405]
    private = tmp_path / ".private"
    assert (private.stat().st_mode & 0o777, (private / "llm-presets.json").stat().st_mode & 0o777) == (0o700, 0o600)


def test_saved_presets_can_be_deleted_but_not_the_environment_one(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("LLM4OM_LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM4OM_LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM4OM_LLM_BASE_URL", "http://localhost:9")
    with client(tmp_path) as api:
        preset_id = add_preset(api)["presets"][-1]["id"]
        deleted = api.delete(f"/api/presets/{preset_id}")
        environment = api.delete("/api/presets/env")
        missing = api.delete(f"/api/presets/{preset_id}")
    assert [item["id"] for item in deleted.json()["presets"]] == ["env"]
    assert environment.status_code == 400 and missing.status_code == 400


def test_the_model_list_never_sends_a_saved_key(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        add_preset(api)
        response = api.post("/api/models", json={**PRESET, "api_key": "", "base_url": "http://attacker.invalid/v1"})
    assert response.status_code == 400 and "API key" in response.json()["detail"]


@pytest.mark.parametrize("provider,url", [("unknown", ""), ("openai_compatible", "")])
def test_model_catalog_settings_are_validated_before_contacting_a_provider(tmp_path: Path, provider: str, url: str) -> None:
    with client(tmp_path) as api:
        response = api.post("/api/models", json={"provider": provider, "base_url": url, "api_key": "dummy"})
    assert response.status_code == 400


def test_runs_choose_a_preset_by_id_and_the_first_is_the_default(tmp_path: Path, monkeypatch: Any) -> None:
    store = LLMPresetStore(tmp_path)
    with pytest.raises(ValueError, match="Add an LLM preset first"):
        store.get()
    selected = store.add(LLM)
    monkeypatch.setenv("LLM4OM_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM4OM_LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM4OM_LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM4OM_LLM_NAME", "deepseek-v4.1 flash-1017")
    assert [preset.id for preset in store.presets()] == ["env", selected.id]
    assert store.public()["presets"][0]["name"] == "deepseek-v4.1 flash-1017"
    assert (store.get().model, store.get(selected.id).model) == ("env-model", LLM.model)
    with pytest.raises(ValueError, match="No LLM preset 'nosuch'"):
        store.get("nosuch")


def test_v038_settings_become_presets(tmp_path: Path) -> None:
    old = tmp_path / ".private" / "llm-settings.json"
    old.parent.mkdir()
    old.write_text(json.dumps({"selected": "deepseek", "profiles": {"deepseek": {"model": "deepseek-chat", "api_key": "k"}}}))
    store = LLMPresetStore(tmp_path)
    assert [(preset.id, preset.settings.model) for preset in store.presets()] == [("deepseek", "deepseek-chat")]
    assert not old.exists() and store.path.exists()


def test_posts_must_be_json(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        form = api.post("/api/presets", content="provider=x", headers={"content-type": "application/x-www-form-urlencoded"})
        runs = api.post("/threads", content="{}", headers={"content-type": "text/plain"})
        untyped = api.post("/threads", content="{}", headers={"content-type": ""})
        empty = api.post("/api/datasets/nl4opt")  # no body, like cancelling a run: passes the check, then 405
    assert form.status_code == 415 and runs.status_code == 415 and untyped.status_code == 415
    assert empty.status_code == 405


def test_examples_are_paged(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        page = api.get("/api/datasets/nl4opt", params={"offset": 5, "limit": 3}).json()
    assert page["total"] == 205 and len(page["cases"]) == 3 and page["cases"][0]["description"]


@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_invalid_example_pages_are_rejected(tmp_path: Path, params: dict[str, int]) -> None:
    with client(tmp_path) as api:
        assert api.get("/api/datasets/nl4opt", params=params).status_code == 422


def test_thread_deletion_retries_progress_cleanup_after_the_thread_is_gone(tmp_path: Path, monkeypatch: Any) -> None:
    from llm4om.progress import NAMESPACE

    thread_id = str(uuid4())
    sdk = SimpleNamespace(runs=SimpleNamespace(list=AsyncMock(return_value=[])),
                          store=SimpleNamespace(delete_item=AsyncMock(side_effect=[RuntimeError("store unavailable"), None])))
    monkeypatch.setattr("llm4om.server.middleware.get_client", lambda **_: sdk)
    app = create_app(LLMPresetStore(tmp_path))
    deleted = False

    @app.delete("/threads/{thread}")
    def delete(thread: str) -> Response:
        nonlocal deleted
        status = 404 if deleted else 204
        deleted = True
        return Response(status_code=status)

    with TestClient(app, raise_server_exceptions=False) as api:
        assert api.delete(f"/threads/{thread_id}").status_code == 500
        assert deleted
        assert api.delete(f"/threads/{thread_id}").status_code == 404
    assert sdk.store.delete_item.await_count == 2
    sdk.store.delete_item.assert_awaited_with(NAMESPACE, key=thread_id)


def test_thread_deletion_waits_for_running_writers_before_removing_records(tmp_path: Path, monkeypatch: Any) -> None:
    sdk = SimpleNamespace(runs=SimpleNamespace(list=AsyncMock(return_value=[{"run_id": "running"}]),
                                              cancel=AsyncMock(side_effect=RuntimeError("cannot stop writer"))))
    monkeypatch.setattr("llm4om.server.middleware.get_client", lambda **_: sdk)
    app = create_app(LLMPresetStore(tmp_path))
    deleted = False

    @app.delete("/threads/{thread}")
    def delete(thread: str) -> Response:
        nonlocal deleted
        deleted = True
        return Response(status_code=204)

    thread_id = str(uuid4())
    with TestClient(app, raise_server_exceptions=False) as api:
        assert api.delete(f"/threads/{thread_id}").status_code == 500
    assert not deleted
    sdk.runs.cancel.assert_awaited_once_with(thread_id, "running", wait=True)


def test_the_server_registers_one_graph_per_method() -> None:
    from llm4om.server import graphs

    for method in methods():
        assert getattr(graphs, method).name == method
    # `langgraph dev` reads the graphs from langgraph.json; `llm4om serve` builds the same list from methods().
    config = json.loads((Path(__file__).parents[1] / "langgraph.json").read_text(encoding="utf-8"))
    assert config["graphs"] == {method: f"llm4om.server.graphs:{method}" for method in methods()}


def test_a_run_streams_each_step_before_it_ends(make_resources: Any) -> None:
    seen: list[dict[str, Any]] = []
    state = asyncio.run(run(PRODUCTION_PROBLEM, resources=make_resources(lambda *_: TWO_PART_REPLY),
                            on_step=lambda step: seen.append(dict(step))))
    assert [(step["type"], step.get("running")) for step in seen if step["type"] != "artifact"] == [
        ("llm", True), ("llm", False), ("solve", True), ("solve", False)]
    assert [step["id"] for step in state["steps"]] == list(dict.fromkeys(step["id"] for step in seen))
    assert state["usage"] == {"llm_calls": 1, "solves": 1, "input_tokens": 10, "output_tokens": 5}


def test_a_run_uses_the_chosen_preset(make_resources: Any) -> None:
    resources = make_resources(lambda *_: TWO_PART_REPLY, llm=None)
    selected = resources.presets.add(LLM, "deepseek-v4.1 flash-1017")
    chosen = asyncio.run(run(PRODUCTION_PROBLEM, preset=selected.id, resources=resources))
    unknown = asyncio.run(run(PRODUCTION_PROBLEM, preset="nosuch", resources=resources))
    assert chosen["solve"]["objective"] == 13
    assert chosen["spec"]["preset_name"] == "deepseek-v4.1 flash-1017"
    assert chosen["spec"]["llm"]["model"] == LLM.model
    assert unknown["failure"].startswith("No LLM preset 'nosuch'")


def test_preset_names_are_display_metadata_and_older_presets_still_load(tmp_path: Path) -> None:
    store = LLMPresetStore(tmp_path)
    with client(tmp_path) as api:
        named = api.post("/api/presets", json={**PRESET, "name": " deepseek-v4.1 flash-1017 "}).json()["presets"][0]
        assert named["name"] == "deepseek-v4.1 flash-1017" and named["model"] == LLM.model
        assert store.get(named["id"]) == LLM
    content = json.loads(store.path.read_text())
    del content["presets"][0]["name"]
    store.path.write_text(json.dumps(content))
    assert store.public()["presets"][0]["name"] == LLM.model


def test_a_request_config_cannot_replace_the_server_resources(monkeypatch: Any) -> None:
    from llm4om import graph

    seen: list[Any] = []
    monkeypatch.setattr(graph, "default_resources", lambda: seen.append("default") or graph.Resources(None, None))  # type: ignore[arg-type]
    monkeypatch.setattr(graph, "get_config", lambda: {"configurable": {"llm4om_resources": {"sandbox": "local"}}})
    assert isinstance(graph._resources(), graph.Resources) and seen == ["default"]


def test_a_preset_stops_once_its_daily_token_budget_is_spent(make_resources: Any, tmp_path: Path) -> None:
    broken = "### Formulation\nx\n\n```python\ndef build_model(data):\n    raise ValueError('broken')\n```"
    resources = replace(make_resources(lambda *_: broken, llm=None), budget=TokenBudget(tmp_path, daily_limit=20))
    selected = resources.presets.add(LLM)
    # Each call uses 15 tokens: the second call starts at 15, the third finds the budget spent and stops the run.
    stopped = asyncio.run(run(PRODUCTION_PROBLEM, method="feedback_repair", resources=resources))
    refused = asyncio.run(run(PRODUCTION_PROBLEM, resources=resources))
    assert stopped["usage"]["llm_calls"] == 2 and "daily budget of 20 tokens" in stopped["failure"]
    assert "daily budget" in refused["failure"] and not refused.get("steps")
    assert resources.budget is not None and resources.budget.used() == {selected.id: 30}
    resources.budget.flush()
    assert TokenBudget(tmp_path, daily_limit=20).used() == {selected.id: 30}  # the counts survive a restart
    with TestClient(create_app(resources.presets, resources.budget)) as api:
        listed = api.get("/api/presets").json()
    assert listed["daily_tokens"] == 20 and listed["presets"][0]["tokens_today"] == 30


def test_each_address_may_start_a_limited_number_of_runs_per_hour(tmp_path: Path) -> None:
    def starts(api: TestClient, **headers: str) -> list[int]:
        return [api.post(path, json={}, headers=headers).status_code
                for path in ("/threads/t1/runs", "/threads/t1/runs/stream", "/runs/wait")]

    with TestClient(create_app(LLMPresetStore(tmp_path), runs_per_hour=2)) as api:
        direct = starts(api)
        other = api.post("/threads", json={}).status_code  # creating a thread is not a run
    with TestClient(create_app(LLMPresetStore(tmp_path), runs_per_hour=2, trust_proxy=True)) as api:
        proxied = starts(api, **{"x-forwarded-for": "10.0.0.9, 203.0.113.5"})
        second = starts(api, **{"x-forwarded-for": "203.0.113.6"})
    assert direct[2] == proxied[2] == second[2] == 429 and 429 not in direct[:2] + proxied[:2] + second[:2]
    assert other != 429


def test_batch_rate_limit_counts_runs_and_preserves_the_request_body(tmp_path: Path) -> None:
    app = create_app(LLMPresetStore(tmp_path), runs_per_hour=3)

    @app.post("/runs/batch")
    def batch(runs: list[dict]) -> dict:
        return {"received": runs}

    with TestClient(app) as api:
        assert api.post("/runs/batch", json=[{}] * 4).status_code == 429
        payload = [{"assistant_id": "direct"}, {"assistant_id": "coe"}]
        assert api.post("/runs/batch", json=payload).json() == {"received": payload}
        assert api.post("/runs/batch", json={}).status_code == 400
        assert api.post("/runs/batch", json=[{}] * 2).status_code == 429
        assert api.post("/runs", json={}).status_code != 429
        assert api.post("/runs", json={}).status_code == 429
