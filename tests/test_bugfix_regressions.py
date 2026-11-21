"""Regression tests for platform-wide bugs fixed across core, agent, server, sandbox, and methods."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from simpleeval import InvalidExpression
from starlette.testclient import TestClient

from llm4om.agent import _build_tools_and_middleware
from llm4om.budget import TokenBudget
from llm4om.host.records import open_records
from llm4om.languages import CodeTarget
from llm4om.llm import LLMSettings
from llm4om.methods.autoformulation.search import extract_best_solution
from llm4om.methods.coe.parsing import extract_code_from_string
from llm4om.methods.optitree.graph import extract_code as optitree_extract_code
from llm4om.model_code import ModelCode
from llm4om.problem import validate_data_files, validate_description
from llm4om.runtime import Limits, Recorder, _LLMEvents
from llm4om.sandbox import worker
from llm4om.server.middleware import JsonOnlyWrites, RunRateLimit
from llm4om.web_search import SearchResult


def test_llm_settings_blocks_alias_overrides_and_hides_api_key() -> None:
    secret = "sk-super-secret-value-12345"
    settings = LLMSettings(provider="openai", model="gpt-4o", api_key=secret)
    assert secret not in repr(settings)
    assert secret not in settings.redact(f"auth failed for {secret}")
    assert "[REDACTED]" in settings.redact(f"auth failed for {secret}")

    with pytest.raises(ValueError, match="finite"):
        LLMSettings(provider="openai", model="gpt-4o", api_key=secret, temperature=float("nan")).validate()

    with pytest.raises(ValueError, match="JSON object"):
        LLMSettings(provider="openai", model="gpt-4o", api_key=secret, extra_body=["bad"]).validate()  # type: ignore[arg-type]

    for alias in ("openai_api_key", "anthropic_api_url", "api_base", "http_client", "stream"):
        with pytest.raises(ValueError, match="cannot replace"):
            LLMSettings(provider="openai", model="gpt-4o", api_key=secret, extra_body={alias: "x"}).validate()


def test_budget_rejects_negative_limit_and_tokens(tmp_path: Any) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        TokenBudget(tmp_path, -1)
    budget = TokenBudget(tmp_path, 100)
    with pytest.raises(ValueError, match="non-negative"):
        budget.charge("p1", -5)


def test_recorder_handles_empty_generations_zero_tokens_at_limit_and_redacts_errors(tmp_path: Any) -> None:
    secret = "sk-leak-check-999"
    budget = TokenBudget(tmp_path, 10)
    recorder = Recorder(Limits(), charge=lambda n: budget.charge("p1", n), redact=lambda s: s.replace(secret, "[REDACTED]"))
    events = _LLMEvents(recorder)

    run_id = "00000000-0000-0000-0000-000000000001"
    events.on_chat_model_start({}, [], run_id=run_id)  # type: ignore[arg-type]
    budget.charge("p1", 10)  # concurrent run exhausts budget while this call is in flight
    # Empty generations + 0 tokens must not raise IndexError or LimitExceeded.
    events.on_llm_end(SimpleNamespace(generations=[], llm_output=None), run_id=run_id)  # type: ignore[arg-type]
    assert recorder.steps[run_id]["running"] is False

    recorder2 = Recorder(Limits(), redact=lambda s: s.replace(secret, "[REDACTED]"))
    events2 = _LLMEvents(recorder2)
    run_id2 = "00000000-0000-0000-0000-000000000002"
    events2.on_chat_model_start({}, [], run_id=run_id2)  # type: ignore[arg-type]
    events2.on_llm_error(RuntimeError(f"upstream rejected {secret}"), run_id=run_id2)  # type: ignore[arg-type]
    assert recorder2.steps[run_id2]["failed"] is True
    assert secret not in recorder2.steps[run_id2]["content"]
    assert "seconds" in recorder2.steps[run_id2]


def test_problem_validators_reject_wrong_types() -> None:
    with pytest.raises(ValueError):
        validate_description(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        validate_data_files(["not-a-mapping"])  # type: ignore[arg-type]


def test_model_code_validates_sense_and_cp_sat_bounds() -> None:
    mc = ModelCode(CodeTarget("ortools", "CP_SAT"))
    with pytest.raises(ValueError, match="sense"):
        mc.objective("median", "x")
    bad_nan = mc.assemble([mc.variables("x", [], "INTEGER", lb="float('nan')")])
    assert worker.run({"code": bad_nan, "data": {}, "language": "ortools", "solver": "CP_SAT", "timeout": 5})["status"] == "error"
    bad_frac = mc.assemble([mc.variables("y", [], "INTEGER", lb="1.5")])
    assert worker.run({"code": bad_frac, "data": {}, "language": "ortools", "solver": "CP_SAT", "timeout": 5})["status"] == "error"


def test_agent_calculator_blocks_dos_expressions() -> None:
    session = SimpleNamespace(
        recorder=Recorder(Limits()),
        optimization=False,
        turn="t1",
        completed=[],
        pending=None,
        pending_model=None,
        change_started=False,
        load=lambda _s: {},
        selected_source=lambda _pid, _cur: None,
    )
    tools, _ = _build_tools_and_middleware(session, None, LLMSettings(provider="openai", model="m", api_key="k"))  # type: ignore[arg-type]
    calc = next(tool for tool in tools if tool.name == "calculate")
    rt = SimpleNamespace(state={"current": None}, tool_call_id="c1", config={"configurable": {"thread_id": "th"}})

    content, _ = asyncio.run(calc.coroutine(expression="2 ** 10", runtime=rt))
    assert "1024" in content
    for bad in ("2 ** 100000", "1 << 100000", "f'{1}'"):
        with pytest.raises((ValueError, OverflowError, InvalidExpression)):
            asyncio.run(calc.coroutine(expression=bad, runtime=rt))


def test_search_result_coerces_none_fields() -> None:
    result = SearchResult(title="Doc", url="https://example.org", summary=None, snippet=None)  # type: ignore[arg-type]
    assert result.summary == ""
    assert result.snippet == ""


def test_host_records_wraps_sqlite_errors(tmp_path: Any) -> None:
    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "records.sqlite").write_bytes(b"not a sqlite database")
    with pytest.raises(ValueError):
        with open_records(corrupt_dir):
            pass


def test_json_only_writes_blocks_cross_origin_websocket_and_spoofed_content_type() -> None:
    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1000})
        else:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

    app = JsonOnlyWrites(inner)
    client = TestClient(app)

    resp = client.post("/threads", content=b"{}", headers={"content-type": "application/json-evil"})
    assert resp.status_code == 415

    with pytest.raises(Exception):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example", "host": "localhost"}):
            pass


def test_rate_limit_covers_crons_and_commands_and_evicts_expired_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    with pytest.raises(ValueError):
        RunRateLimit(ok, per_hour=-1)

    now = [1000.0]
    monkeypatch.setattr("llm4om.server.middleware.time.monotonic", lambda: now[0])
    limiter = RunRateLimit(ok, per_hour=1)
    client = TestClient(limiter)
    assert client.post("/crons", json={}).status_code == 200
    assert client.post("/threads/t1/commands", json={"method": "run.start"}).status_code == 429
    now[0] += 3700.0
    assert client.post("/threads/t1/commands", json={"method": "run.start"}).status_code == 200
    assert len(limiter.starts) == 1


def test_worker_handles_non_finite_vars_and_complex_cvxpy() -> None:
    pyomo_no_obj = "import pyomo.environ as pyo\ndef build_model(data):\n    return pyo.ConcreteModel()\n"
    out = worker.run({"code": pyomo_no_obj, "data": {}, "language": "pyomo", "solver": "AUTO", "timeout": 5})
    assert out["status"] == "error"
    assert "objective" in (out["error"] or "").lower()

    code = (
        "import cvxpy as cp\n"
        "def build_model(data):\n"
        "    z = cp.Variable(complex=True, name='z')\n"
        "    return cp.Problem(cp.Minimize(cp.real(z) + cp.imag(z)), [cp.real(z) >= 1, cp.imag(z) >= 2])\n"
    )
    solved = worker.run({"code": code, "data": {}, "language": "cvxpy", "solver": "AUTO", "timeout": 10})
    assert solved["status"] in ("optimal", "feasible")
    assert solved["objective"] == pytest.approx(3.0, abs=1e-4)
    assert "z.real" in solved["variables"] and "z.imag" in solved["variables"]
    # Output must always be strict RFC JSON (no NaN/Infinity).
    json.dumps(solved, allow_nan=False)


def test_optitree_and_autoformulation_extractors() -> None:
    reply = "```text\nnot code\n```\n```python\nline1 = 1\nline2 = 2\n```"
    assert optitree_extract_code(reply) == "line1 = 1\nline2 = 2\n"
    assert extract_code_from_string("```python\npip install gurobipy\n```\n```python\nx = 1\ny = 2\n```") == "x = 1\ny = 2"
    assert extract_best_solution('best_solution = {"0": "solution_A", "1": "solution_B"}') == {"0": "solution_A", "1": "solution_B"}


def test_api_models_validates_scheme_and_redacts_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from llm4om.server.app import app

    monkeypatch.setenv("LLM4OM_WORKSPACE", str(tmp_path))
    client = TestClient(app)

    bad_scheme = client.post("/api/models", json={
        "provider": "openai", "model": "m", "api_key": "sk-test", "base_url": "file:///etc/passwd",
    })
    assert bad_scheme.status_code == 400

    empty_key = client.post("/api/models", json={
        "provider": "openai", "model": "m", "api_key": "   ", "base_url": "https://api.example.com/v1",
    })
    assert empty_key.status_code == 400

    secret = "sk-do-not-leak-me"
    monkeypatch.setattr("llm4om.server.app.list_models", lambda _s: (_ for _ in ()).throw(httpx.ConnectError(f"failed with {secret}")))
    failed = client.post("/api/models", json={
        "provider": "openai", "model": "m", "api_key": secret, "base_url": "https://api.example.com/v1",
    })
    assert failed.status_code == 502
    assert secret not in failed.text
