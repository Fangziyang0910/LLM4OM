"""Presentation languages preserve the methods' source data, repair paths and response protocols."""

import asyncio
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from llm4om.graph import run
from llm4om.methods import methods
from llm4om.runtime import Limits
from tests.conftest import PRODUCTION_CODE, PRODUCTION_PROBLEM, TWO_PART_REPLY, tool_call
from tests.test_autoco import FORMULATION_JSON, REVIEW_PASS, SEMANTIC_JSON, SINGLE_OBJ_CODE
from tests.test_method_libraries import method_script

BROKEN_REPLY = TWO_PART_REPLY.replace("return m", "return m.missing")
ROLES = {
    "direct": ["generate"],
    "bind": ["bind_generate", "bind_generate"],
}


@pytest.mark.parametrize("method", ROLES)
@pytest.mark.parametrize("locale,language", [("zh", "Simplified Chinese"), ("en", "English")])
def test_locale_preserves_source_and_protocol_through_repair(make_resources: Any, method: str,
                                                            locale: str, language: str) -> None:
    calls: list[str] = []

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

        if method == "direct":
            return TWO_PART_REPLY
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


@pytest.mark.parametrize("method", list(methods()))
@pytest.mark.parametrize("locale,language", [("zh", "Simplified Chinese"), ("en", "English")])
def test_every_method_receives_locale_and_preserves_its_protocol(
    make_resources: Any, preset: Any, method: str, locale: str, language: str,
) -> None:
    if method == "autoco":
        preset("AUTOCO", max_modeling_revisions=1, enable_pilot=False)

        def base(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
            replies = {
                "semantic_grounding": SEMANTIC_JSON,
                "formulate": FORMULATION_JSON,
                "review_formulation": REVIEW_PASS,
                "instantiate": f"```python\n{SINGLE_OBJ_CODE}```",
            }
            if role == "kg_agent":
                assert "commit_configuration" in tools
                return tool_call("commit_configuration", algorithm="GA", operators={},
                                 hyperparameters={"pop_size": 20}, rationale="Compact integer problem.")
            return replies[role]
    else:
        base = method_script(method, "pyomo")
    calls: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
        prompt = "\n".join(message.text for message in messages)
        assert prompt.count("Output language: Write explanatory prose in " + language) == 1
        assert "JSON enum values" in prompt and "classification names" in prompt
        calls.append(role)
        return base(role, messages, tools)

    limits = Limits(solve_time_limit=5.5) if method == "autoco" else None
    record = asyncio.run(run(PRODUCTION_PROBLEM, method=method,
                             resources=make_resources(script, limits=limits), locale=locale))

    assert not record.get("failure"), record.get("failure")
    assert record["spec"]["locale"] == locale
    assert record["solve"]["objective"] == pytest.approx(13)
    assert record["formulation"] and record["code"]
    assert all(value == round(value) for value in record["solve"]["variables"].values())
    assert calls and record["usage"]["llm_calls"] == len(calls)
    if method == "autoco":
        assert record["spec"]["language"] == "autoco"
        assert record["solve"]["status"] == "feasible" and record["solve"]["solver"] == "GA"
        assert calls == ["semantic_grounding", "formulate", "review_formulation", "instantiate", "kg_agent"]
