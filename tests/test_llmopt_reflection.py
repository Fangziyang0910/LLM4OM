"""Self-correction must provide actionable feedback and an explicit final verdict."""

from typing import Any

import pytest
from langchain_core.messages import BaseMessage

from tests.conftest import PRODUCTION_CODE

MODEL = ("## Sets:\nP = {A, B}\n## Parameters:\nprofits = {A: 3, B: 2}\n"
         "## Variables:\nx in nonnegative integers\n## Objective:\nmax 3*x[A]+2*x[B]\n"
         "## Constraints:\n2*x[A]+x[B]<=8; x[A]+2*x[B]<=8")
CODE = f"```python\n{PRODUCTION_CODE}```"
ACCEPT = "The five-element is True.\nThe code is True.\nAnalysis:\nBoth match the problem."


@pytest.mark.parametrize("reply", [
    "I reviewed the model and code.",
    "The five-element is True.\nAnalysis:\nThe code has not been reviewed.",
    "The five-element is True.\nThe code is True.\nThe code is False.",
    "The five-element is True.\nThe code is True because it matches the problem.",
    "The five-element is True.\nThe code is True/False.",
])
def test_llmopt_does_not_accept_missing_or_conflicting_verdicts(run_method: Any, reply: str) -> None:
    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        return {"five_element": MODEL, "code": CODE, "self_correction": reply}[role]

    result = run_method("llmopt", script)
    assert result["failure"] and "self-correction" in result["failure"].lower()
    assert result["solve"]["objective"] == 13
    assert result["usage"]["solves"] == 1


@pytest.mark.parametrize("part", ["five-element", "code"])
@pytest.mark.parametrize("denial_first", [True, False], ids=["denial-first", "denial-last"])
def test_llmopt_rejects_conflicting_verdicts_with_inline_explanations(
    run_method: Any, part: str, denial_first: bool,
) -> None:
    denial = f"The {part} is False. The profit coefficient for A should be 3, not 6."
    review = f"{denial}\n{ACCEPT}" if denial_first else f"{ACCEPT}\n{denial}"
    wrong_code = CODE.replace('3 * m.x["A"]', '6 * m.x["A"]')

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        return {"five_element": MODEL, "code": wrong_code, "self_correction": review}[role]

    result = run_method("llmopt", script)
    assert result["failure"] and f"conflicting verdict for {part}" in result["failure"]
    assert result["solve"]["objective"] == 24
    assert result["usage"]["solves"] == 1
    assert any(review in step.get("content", "") for step in result["steps"] if step["type"] == "artifact")


@pytest.mark.parametrize("rejected", ["five_element", "code"])
def test_llmopt_rejected_step_receives_the_actual_review(run_method: Any, rejected: str) -> None:
    calls: dict[str, list[str]] = {}
    marker = "REFLECTION_FIX_PROFIT_COEFFICIENT"
    wrong_code = CODE.replace('3 * m.x["A"]', '6 * m.x["A"]')
    wrong_model = MODEL.replace("A: 3", "A: 6").replace("3*x[A]", "6*x[A]")

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        calls.setdefault(role, []).append(messages[-1].text)
        if role == "five_element":
            return wrong_model if rejected == role and len(calls[role]) == 1 else MODEL
        if role == "code":
            return CODE if marker in messages[-1].text else wrong_code
        if len(calls[role]) == 1:
            five, code = ("False", "True") if rejected == "five_element" else ("True", "False")
            return (f"The five-element is {five}.\nThe code is {code}.\nAnalysis:\n"
                    f"{marker}: A's profit must be 3, not 6.")
        return ACCEPT

    result = run_method("llmopt", script)
    assert marker in calls[rejected][1]
    assert result["failure"] is None
    assert result["solve"]["objective"] == 13
    assert result["usage"]["solves"] == 2
    assert any(marker in step.get("content", "") for step in result["steps"] if step["type"] == "artifact")


def test_llmopt_exhausted_review_is_a_failure_with_actual_result(run_method: Any, preset: Any) -> None:
    preset("LLMOPT", max_resolves=1)

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        return {"five_element": MODEL, "code": CODE,
                "self_correction": "The five-element is True.\nThe code is False.\nAnalysis:\nNot yet accepted."}[role]

    result = run_method("llmopt", script)
    assert result["failure"] and "self-correction" in result["failure"].lower()
    assert result["solve"]["objective"] == 13
    assert result["usage"]["solves"] == 2


@pytest.mark.parametrize("review", [
    "**The five-element is [True].**\n**The code is `True`.**\nAnalysis:\nREVIEW_VISIBLE",
    ACCEPT + "\nThe code is True because both profit coefficients match. REVIEW_VISIBLE",
], ids=["markdown", "consistent-explanation"])
def test_llmopt_accepts_consistent_verdicts_and_keeps_the_review_visible(run_method: Any, review: str) -> None:
    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        return {"five_element": MODEL, "code": CODE, "self_correction": review}[role]

    result = run_method("llmopt", script)
    assert result["failure"] is None
    assert result["solve"]["objective"] == 13
    assert any("REVIEW_VISIBLE" in step.get("content", "") for step in result["steps"] if step["type"] == "artifact")


def test_llmopt_cannot_accept_a_failed_execution(run_method: Any) -> None:
    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        return {"five_element": MODEL, "code": CODE.replace("return m", "return m.missing"),
                "self_correction": ACCEPT}[role]

    result = run_method("llmopt", script)
    assert result["failure"] and result["solve"]["error"]
    assert result["usage"]["solves"] == 1
