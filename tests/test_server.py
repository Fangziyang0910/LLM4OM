"""The routes beside the LangGraph API, and the graphs the server registers."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from llm4om.graph import run
from llm4om.llm import LLMPresetStore
from llm4om.methods import methods
from llm4om.runtime import TokenBudget
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
    assert {item["id"] for item in options["languages"]} == {"pyomo", "gurobipy", "pywraplp", "cpmpy", "pulp", "cvxpy"}
    optimus = next(m for m in options["methods"] if m["id"] == "optimus")
    assert optimus["languages"] == ["gurobipy", "pulp", "pyomo", "pywraplp"]


def test_presets_never_return_their_keys_and_cannot_be_changed(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        add_preset(api)
        listed = add_preset(api)  # the same settings again become a second preset, not an update
        changes = [api.put("/api/presets/scripted", json=PRESET).status_code,
                   api.patch("/api/presets/scripted", json=PRESET).status_code]
    assert [item["id"] for item in listed["presets"]] == ["scripted", "scripted-2"]
    assert LLM.api_key not in str(listed) and all("api_key" not in item for item in listed["presets"])
    assert changes == [405, 405]
    private = tmp_path / ".private"
    assert (private.stat().st_mode & 0o777, (private / "llm-presets.json").stat().st_mode & 0o777) == (0o700, 0o600)


def test_saved_presets_can_be_deleted_but_not_the_environment_one(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("LLM4OM_LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM4OM_LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM4OM_LLM_BASE_URL", "http://localhost:9")
    with client(tmp_path) as api:
        add_preset(api)
        deleted = api.delete("/api/presets/scripted")
        environment = api.delete("/api/presets/env")
        missing = api.delete("/api/presets/scripted")
    assert [item["id"] for item in deleted.json()["presets"]] == ["env"]
    assert environment.status_code == 400 and missing.status_code == 400


def test_the_model_list_never_sends_a_saved_key(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        add_preset(api)
        response = api.post("/api/models", json={**PRESET, "api_key": "", "base_url": "http://attacker.invalid/v1"})
    assert response.status_code == 400 and "API key" in response.json()["detail"]


def test_runs_choose_a_preset_by_id_and_the_first_is_the_default(tmp_path: Path, monkeypatch: Any) -> None:
    store = LLMPresetStore(tmp_path)
    with pytest.raises(ValueError, match="Add an LLM preset first"):
        store.get()
    store.add(LLM)
    monkeypatch.setenv("LLM4OM_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM4OM_LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM4OM_LLM_API_KEY", "env-key")
    assert [preset.id for preset in store.presets()] == ["env", "scripted"]
    assert (store.get().model, store.get("scripted").model) == ("env-model", LLM.model)
    with pytest.raises(ValueError, match=r"No LLM preset 'nosuch'; choose one of \['env', 'scripted'\]"):
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
    resources.presets.add(LLM)
    chosen = asyncio.run(run(PRODUCTION_PROBLEM, preset="scripted", resources=resources))
    unknown = asyncio.run(run(PRODUCTION_PROBLEM, preset="nosuch", resources=resources))
    assert chosen["solve"]["objective"] == 13
    assert unknown["failure"].startswith("No LLM preset 'nosuch'")


def test_a_request_config_cannot_replace_the_server_resources(monkeypatch: Any) -> None:
    from llm4om import graph

    seen: list[Any] = []
    monkeypatch.setattr(graph, "default_resources", lambda: seen.append("default") or graph.Resources(None, None))  # type: ignore[arg-type]
    monkeypatch.setattr(graph, "get_config", lambda: {"configurable": {"llm4om_resources": {"sandbox": "local"}}})
    assert isinstance(graph._resources(), graph.Resources) and seen == ["default"]


def test_a_preset_stops_once_its_daily_token_budget_is_spent(make_resources: Any, tmp_path: Path) -> None:
    broken = "### Formulation\nx\n\n```python\ndef build_model(data):\n    raise ValueError('broken')\n```"
    resources = replace(make_resources(lambda *_: broken, llm=None), budget=TokenBudget(tmp_path, daily_limit=20))
    resources.presets.add(LLM)
    # Each call uses 15 tokens: the second call starts at 15, the third finds the budget spent and stops the run.
    stopped = asyncio.run(run(PRODUCTION_PROBLEM, method="feedback_repair", resources=resources))
    refused = asyncio.run(run(PRODUCTION_PROBLEM, resources=resources))
    assert stopped["usage"]["llm_calls"] == 2 and "daily budget of 20 tokens" in stopped["failure"]
    assert "daily budget" in refused["failure"] and not refused.get("steps")
    assert resources.budget is not None and resources.budget.used() == {"scripted": 30}
    resources.budget.flush()
    assert TokenBudget(tmp_path, daily_limit=20).used() == {"scripted": 30}  # the counts survive a restart
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
