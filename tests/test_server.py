"""The routes beside the LangGraph API, and the graphs the server registers."""

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from llm4om.graph import run
from llm4om.llm import SettingsStore
from llm4om.methods import methods
from llm4om.server.app import create_app
from tests.conftest import LLM, PRODUCTION_PROBLEM, TWO_PART_REPLY


def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(SettingsStore(tmp_path)))


def save_llm(api: TestClient) -> None:
    body = {"provider": LLM.provider, "model": LLM.model, "api_key": LLM.api_key, "base_url": LLM.base_url}
    assert api.post("/api/settings", json=body).status_code == 200


def test_options_list_methods_languages_and_providers(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        options = api.get("/api/options").json()
    assert {"direct", "trival", "optimus", "coe", "optitree", "or_llm_agent", "autoformulation"} <= {m["id"] for m in options["methods"]}
    assert {item["id"] for item in options["languages"]} == {"pyomo", "gurobipy", "pywraplp", "cpmpy"}
    optimus = next(m for m in options["methods"] if m["id"] == "optimus")
    assert optimus["languages"] == ["gurobipy", "pyomo", "pywraplp"]


def test_settings_hide_the_key_and_keep_it_when_left_empty(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        save_llm(api)
        body = {"provider": LLM.provider, "model": "other-model", "base_url": LLM.base_url}
        settings = api.post("/api/settings", json=body).json()
    profile = settings["profiles"][LLM.provider]
    assert "api_key" not in profile and LLM.api_key not in str(settings)
    assert profile["api_key_preview"] and profile["model"] == "other-model"


def test_a_saved_profile_can_be_deleted(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        save_llm(api)
        deleted = api.delete(f"/api/settings/{LLM.provider}")
        missing = api.delete("/api/settings/kimi")
    assert deleted.status_code == 200 and not deleted.json()["profiles"].get(LLM.provider, {}).get("saved")
    assert missing.status_code == 400


def test_posts_must_be_json(tmp_path: Path) -> None:
    with client(tmp_path) as api:
        form = api.post("/api/settings", content="provider=x", headers={"content-type": "application/x-www-form-urlencoded"})
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


def test_the_environment_profile_is_listed_beside_saved_ones(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("LLM4OM_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM4OM_LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM4OM_LLM_API_KEY", "env-key-123456")
    store = SettingsStore(tmp_path)
    assert store.public()["selected"] == "deepseek"
    with client(tmp_path) as api:
        save_llm(api)
    public = store.public()
    assert public["selected"] == LLM.provider and set(public["profiles"]) == {LLM.provider, "deepseek"}
    assert store.resolve().model == LLM.model
    assert (store.resolve("deepseek").model, store.resolve("deepseek", "other").model) == ("env-model", "other")


def test_a_run_streams_each_step_before_it_ends(make_resources: Any) -> None:
    seen: list[dict[str, Any]] = []
    state = asyncio.run(run(PRODUCTION_PROBLEM, resources=make_resources(lambda *_: TWO_PART_REPLY),
                            on_step=lambda step: seen.append(dict(step))))
    assert [(step["type"], step.get("running")) for step in seen if step["type"] != "artifact"] == [
        ("llm", True), ("llm", False), ("solve", True), ("solve", False)]
    assert [step["id"] for step in state["steps"]] == list(dict.fromkeys(step["id"] for step in seen))
    assert state["usage"] == {"llm_calls": 1, "solves": 1, "input_tokens": 10, "output_tokens": 5}
