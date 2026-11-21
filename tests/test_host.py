"""Host-owned modeling across separate CLI invocations, without a platform model or server."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, convert_to_messages

from llm4om.host import resume, start, status
from llm4om.languages import LANGUAGES
from llm4om.methods import methods
from tests.conftest import ACCEPT_REVIEW, PRODUCTION_CODE, PRODUCTION_PROBLEM, TWO_PART_REPLY
from tests.test_method_libraries import method_script
from tests.test_methods import PASS_FORMULATION, autoformulation_script, by_role, trival_script


def drive_host(directory: Path, script: Any, *, method: str = "direct", language: str = "pyomo",
               sandbox: str = "local", **kwargs: Any) -> dict[str, Any]:
    result = asyncio.run(start(directory, PRODUCTION_PROBLEM, method=method, language=language, sandbox=sandbox, **kwargs))
    for _ in range(150):
        if result["status"] != "waiting":
            return result
        responses = {}
        for request in result["pending"]:
            answer = script(request["role"], convert_to_messages(request["messages"]),
                            [tool["function"]["name"] for tool in request["tools"]])
            responses[request["id"]] = {"content": answer.content, "tool_calls": answer.tool_calls} if isinstance(
                answer, AIMessage) else {"content": answer}
        result = asyncio.run(resume(directory, responses))
    pytest.fail("The method did not finish within its bounded test trajectory")


def test_host_repairs_with_real_solver_feedback_across_restarts(tmp_path: Path, monkeypatch: Any) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Host modeling must never resolve a platform LLM")

    monkeypatch.setattr("llm4om.llm.LLMSettings.validate", forbidden)
    monkeypatch.setattr("llm4om.llm_presets.LLMPresetStore.find", forbidden)
    directory = tmp_path / "session"
    result = asyncio.run(start(directory, PRODUCTION_PROBLEM, method="feedback_repair", sandbox="local"))
    assert result["status"] == "waiting"
    assert result["pending"][0]["role"] == "generate"
    assert asyncio.run(status(directory))["pending"] == result["pending"]

    def answer(text: str) -> dict[str, Any]:
        return asyncio.run(resume(directory, {result["pending"][0]["id"]: {"content": text}}))

    result = answer(TWO_PART_REPLY.replace("return m", "return m.missing"))
    assert result["pending"][0]["role"] == "repair"
    assert "missing" in str(result["pending"][0]["messages"])
    result = answer(TWO_PART_REPLY)
    assert result["pending"][0]["role"] == "review"
    result = answer(ACCEPT_REVIEW)
    assert result["status"] == "completed"
    assert result["solve"]["objective"] == 13
    assert result["code"].strip() == PRODUCTION_CODE.strip()
    assert result["usage"]["llm_calls"] == 3
    assert result["usage"]["solves"] == 2
    assert result["usage"]["input_tokens"] is None
    assert asyncio.run(status(directory))["solve"] == result["solve"]
    assert (directory / "model.py").read_text().strip() == PRODUCTION_CODE.strip()


@pytest.mark.parametrize("method", list(methods()))
@pytest.mark.parametrize("language", list(LANGUAGES))
def test_host_runs_every_method_with_every_library(tmp_path: Path, preset: Any, method: str, language: str) -> None:
    preset("AUTOFORMULATION", n_used_gpt=1, n_top=1, n_reward=1, total_rollouts=1)
    result = drive_host(tmp_path / "session", method_script(method, language), method=method, language=language)
    assert result["status"] == "completed", result.get("failure")
    assert result["solve"]["objective"] == pytest.approx(13), result["solve"]
    assert result["formulation"] and result["code"]
    assert {"llm", "artifact", "solve"} <= {step["type"] for step in result["steps"]}
    assert all(not step.get("running") for step in result["steps"])
    assert result["usage"]["solves"] == 1


def test_host_preserves_parallel_search_voting_and_does_not_repeat_solves(tmp_path: Path, preset: Any) -> None:
    preset("AUTOFORMULATION", n_used_gpt=2, n_top=2, n_reward=1, total_rollouts=2)
    calls: list[tuple[str, str]] = []
    result = drive_host(tmp_path / "session", autoformulation_script("pyo.NonNegativeIntegers", calls),
                        method="autoformulation")
    assert result["status"] == "completed", result["failure"]
    assert result["solve"]["objective"] == 13
    assert result["usage"]["solves"] == 2
    assert [role for role, _ in calls].count("compare") == 10
    assert result["usage"]["llm_calls"] == len(calls) == 29
    assert sorted(step["objective"] for step in result["steps"] if step["type"] == "solve") == [13, 16]


def test_host_rejects_invalid_answers_without_consuming_the_pending_request(tmp_path: Path) -> None:
    directory = tmp_path / "session"
    before = asyncio.run(start(directory, PRODUCTION_PROBLEM, sandbox="local"))
    for response in ({"wrong-id": {"content": TWO_PART_REPLY}}, {}, {before["pending"][0]["id"]: {"content": 3}}):
        with pytest.raises(ValueError):
            asyncio.run(resume(directory, response))
        assert asyncio.run(status(directory))["pending"] == before["pending"]
    final = asyncio.run(resume(directory, {before["pending"][0]["id"]: {"content": TWO_PART_REPLY}}))
    assert final["solve"]["objective"] == 13
    with pytest.raises(ValueError, match="ended"):
        asyncio.run(resume(directory, {}))


def test_host_caps_parallel_requests_before_returning_work_to_the_agent(tmp_path: Path) -> None:
    result = asyncio.run(start(tmp_path / "session", PRODUCTION_PROBLEM, method="autoformulation", sandbox="local", max_calls=2))
    assert result["status"] == "failed" and "limit" in result["failure"]
    assert result["usage"]["llm_calls"] == 2 and result["usage"]["solves"] == 0


def test_host_keeps_attachments_in_the_session_and_preserves_bind_data_offloading(tmp_path: Path) -> None:
    numbers = [0] * 21000 + [876543]
    code = PRODUCTION_CODE.replace('3 * m.x["A"]', 'max(__import__("json").loads(data["profit.json"])) * m.x["A"]')

    def script(role: str, messages: list, tools: list) -> str:
        prompt = "\n".join(message.text for message in messages)
        assert "876543" not in prompt and "truncated" not in prompt
        return TWO_PART_REPLY.replace(PRODUCTION_CODE, code)

    result = drive_host(tmp_path / "session", script, method="bind", data={"profit.json": json.dumps(numbers)})
    assert result["solve"]["objective"] == 4 * 876543
    assert "876543" not in json.dumps(result["spec"])


def test_host_trival_backtracks_from_code_validation_to_formulation(tmp_path: Path) -> None:
    script = trival_script([
        {"code_validation_passed": False, "code_validation_feedback": "Recheck the formulation.",
         "error_attribution": "formulation"},
        {"code_validation_passed": True, "code_validation_feedback": "Matches."},
    ], [dict(PASS_FORMULATION), dict(PASS_FORMULATION)])
    result = drive_host(tmp_path / "session", script, method="trival")
    assert result["status"] == "completed", result["failure"]
    assert "revised" in result["formulation"]
    assert result["solve"]["objective"] == 13 and result["usage"]["solves"] == 2
    titles = [step["title"] for step in result["steps"] if step["type"] == "llm"]
    assert titles.count("trival.formulation_validator") == 2
    assert titles.count("trival.code_validator") == 2


def test_host_solve_budget_keeps_results_bound_to_the_code_actually_executed(tmp_path: Path) -> None:
    script = by_role({"generate": TWO_PART_REPLY.replace("return m", "return m.missing"),
                      "repair": TWO_PART_REPLY, "review": ACCEPT_REVIEW})
    result = drive_host(tmp_path / "session", script, method="feedback_repair", max_solves=1)
    assert result["status"] == "failed" and "limit" in result["failure"]
    assert result["code"].strip() == PRODUCTION_CODE.strip()
    assert result["solve"] is None and result["usage"]["solves"] == 1


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_host_rejects_invalid_limits_before_creating_a_session(tmp_path: Path, limit: float) -> None:
    directory = tmp_path / "session"
    with pytest.raises(ValueError, match="finite and positive"):
        asyncio.run(start(directory, PRODUCTION_PROBLEM, time_limit=limit))
    assert not directory.exists()


@pytest.mark.docker
@pytest.mark.skipif(not os.environ.get("LLM4OM_TEST_DOCKER"), reason="set LLM4OM_TEST_DOCKER=1")
@pytest.mark.parametrize("method", ["direct", "feedback_repair", "trival"])
def test_host_executes_the_existing_docker_worker(tmp_path: Path, method: str) -> None:
    result = drive_host(tmp_path / "session", method_script(method, "pyomo"), method=method, sandbox="docker")
    assert result["status"] == "completed", result["failure"]
    assert result["solve"]["objective"] == 13 and result["usage"]["solves"] == 1
