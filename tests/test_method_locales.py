"""Presentation languages preserve the methods' source data, repair paths and response protocols."""

import asyncio
import json
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from llm4om.graph import run
from llm4om.methods import methods
from tests.conftest import PRODUCTION_CODE, PRODUCTION_PROBLEM, TWO_PART_REPLY
from tests.test_method_libraries import method_script

BROKEN_REPLY = TWO_PART_REPLY.replace("return m", "return m.missing")
ROLES = {
    "direct": ["generate"],
    "feedback_repair": ["generate", "repair", "review"],
    "bind": ["bind_generate", "bind_generate"],
    "optimind": ["optimind_classify", "optimind_generate", "optimind_generate", "optimind_generate"],
}


@pytest.mark.parametrize("method", ROLES)
@pytest.mark.parametrize("locale,language", [("zh", "Simplified Chinese"), ("en", "English")])
def test_locale_preserves_source_and_protocol_through_repair(make_resources: Any, method: str,
                                                            locale: str, language: str) -> None:
    calls: list[str] = []
    reason = "模型与题意一致。" if locale == "zh" else "The model matches the problem."

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        systems = [message.text for message in messages if isinstance(message, SystemMessage)]
        assert len(systems) == 1
        instruction = "Output language: Write explanatory prose in " + language
        assert systems[0].count(instruction) == 1
        assert "JSON enum values" in systems[0] and "classification names" in systems[0]
        original = next(message.text for message in messages if isinstance(message, HumanMessage))
        assert PRODUCTION_PROBLEM in original
        assert "Output language:" not in original
        calls.append(role)

        if role == "optimind_classify":
            assert "JSON array of exact class names" in systems[0]
            assert "TravelingSalesman" in systems[0]
            return "[]"
        if role == "review":
            return json.dumps({"action": "accept", "reason": reason}, ensure_ascii=False)
        if method == "direct":
            return TWO_PART_REPLY
        if role == "repair":
            assert "missing" in messages[-1].text
            return TWO_PART_REPLY
        if role == "optimind_generate" and calls.count(role) == 3:
            return "模型无需进一步修改。" if locale == "zh" else "No further model changes are needed."
        if calls.count(role) == 1:
            return BROKEN_REPLY
        assert "missing" in messages[-1].text
        return TWO_PART_REPLY

    record = asyncio.run(run(PRODUCTION_PROBLEM, method=method, resources=make_resources(script), locale=locale))

    assert not record.get("failure"), record.get("failure")
    assert record["spec"]["locale"] == locale
    assert record["solve"]["objective"] == 13
    assert record["solve"]["variables"] == {"x[A]": 3, "x[B]": 2}
    assert record["code"].strip() == PRODUCTION_CODE.strip()
    assert calls == ROLES[method]
    statuses = [step["status"] for step in record["steps"] if step["type"] == "solve"]
    assert statuses == (["optimal"] if method == "direct" else ["error", "optimal"])
    assert record["usage"]["llm_calls"] == len(calls)
    if method == "feedback_repair":
        review = next(step for step in record["steps"] if step["type"] == "llm" and step["title"] == "review")
        assert json.loads(review["content"]) == {"action": "accept", "reason": reason}


@pytest.mark.parametrize("method", list(methods()))
@pytest.mark.parametrize("locale,language", [("zh", "Simplified Chinese"), ("en", "English")])
def test_every_method_receives_locale_and_preserves_its_protocol(
    make_resources: Any, preset: Any, method: str, locale: str, language: str,
) -> None:
    # Reuse the existing one-candidate test configuration; production search parameters remain unchanged.
    preset("AUTOFORMULATION", n_used_gpt=1, n_top=1, n_reward=1, total_rollouts=1)
    base = method_script(method, "pyomo")
    calls: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
        prompt = "\n".join(message.text for message in messages)
        assert prompt.count("Output language: Write explanatory prose in " + language) == 1
        assert "JSON enum values" in prompt and "classification names" in prompt
        calls.append(role)
        return base(role, messages, tools)

    record = asyncio.run(run(PRODUCTION_PROBLEM, method=method, resources=make_resources(script), locale=locale))

    assert not record.get("failure"), record.get("failure")
    assert record["spec"]["locale"] == locale
    assert record["solve"]["objective"] == pytest.approx(13)
    assert record["formulation"] and record["code"]
    assert all(value == round(value) for value in record["solve"]["variables"].values())
    assert calls and record["usage"]["llm_calls"] == len(calls)


@pytest.mark.parametrize("locale", ["zh", "en"])
def test_sac_anchor_math_is_requested_and_retained_in_the_final_formulation(make_resources: Any, locale: str) -> None:
    base = method_script("sac_opt", "pyomo")
    checked: set[str] = set()
    variable = r"$x_A$ — quantity; domain: $x_A \in \mathbb{Z}_{\ge 0}$; bound: $x_A \le 4$."

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
        if role in {"sac_parameters", "sac_variables", "sac_constraints", "sac_objective"}:
            assert "Use LaTeX math delimiters" in messages[0].text
            assert "subscripts" in messages[0].text and "JSON" in messages[0].text
            checked.add(role)
        if role == "sac_variables":
            return json.dumps({"items": [variable]})
        return base(role, messages, tools)

    record = asyncio.run(run(PRODUCTION_PROBLEM, method="sac_opt", resources=make_resources(script), locale=locale))
    assert not record.get("failure"), record.get("failure")
    assert record["solve"]["objective"] == pytest.approx(13)
    assert variable in record["formulation"]
    assert record["spec"]["locale"] == locale
    assert checked == {"sac_parameters", "sac_variables", "sac_constraints", "sac_objective"}
