"""LLMOPT must keep source facts across the formulation/code boundary."""

from typing import Any

import pytest
from langchain_core.messages import BaseMessage

from llm4om.sandbox import Sandbox, SolveResult
from tests.conftest import PRODUCTION_CODE

FORMULATION = ("## Sets:\nN = {R-17, R-92}\n## Parameters:\nCoordinates and demands are in Table 1.\n"
               "## Variables:\nx binary\n## Objective:\nmin distance\n## Constraints:\nserve each customer")
CODE = f"```python\n{PRODUCTION_CODE}```"
ACCEPT = "The five-element is True.\nThe code is True.\nAnalysis:\nSource data checked."
PROBLEM = "Serve restaurants R-17 and R-92. Depot=(50,50). Do not change their identifiers."
TABLE = "restaurant_id,x,y,demand\nR-17,25,85,8\nR-92,35,25,12\n"


@pytest.fixture
def recorded_solves(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """No solver process: these checks exercise context delivery and refusal."""
    calls: list[dict[str, Any]] = []

    async def solve(self: Sandbox, code: str, data: dict[str, str], language: str,
                    time_limit: float, *, solver: str | None = None) -> SolveResult:
        calls.append({"code": code, "data": data})
        return SolveResult(status="optimal", objective=13)

    monkeypatch.setattr(Sandbox, "solve", solve)
    return calls


@pytest.mark.parametrize("attachment", [None, TABLE, "# source metadata\n" + " " * 21000 + TABLE],
                         ids=["inline", "csv", "large_csv"])
def test_llmopt_codegen_and_review_receive_source_facts_despite_an_incomplete_formulation(
    run_method: Any, recorded_solves: list[dict[str, Any]], attachment: str | None,
) -> None:
    problem = PROBLEM if attachment is not None else PROBLEM + "\nTable 1:\n" + TABLE
    data = {"restaurants.csv": attachment} if attachment is not None else {}
    seen: dict[str, str] = {}

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        seen[role] = messages[-1].text
        return {"five_element": FORMULATION, "code": CODE, "self_correction": ACCEPT}[role]

    result = run_method("llmopt", script, problem=problem, data=data)
    assert not result["failure"]
    for role in ("code", "self_correction"):
        assert problem in seen[role]
        assert TABLE in seen[role]
        if attachment is not None:
            assert "restaurants.csv" in seen[role] and attachment in seen[role]
    assert result["spec"]["parameters"]["code_context"] == "problem_and_formulation"
    assert result["usage"] == {"llm_calls": 3, "solves": 1, "input_tokens": 30, "output_tokens": 15}
    assert len(recorded_solves) == 1 and recorded_solves[0]["data"] == data


def test_llmopt_missing_data_refusal_identifies_the_missing_field_without_solving(
    run_method: Any, recorded_solves: list[dict[str, Any]],
) -> None:
    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        return {"five_element": FORMULATION,
                "code": "MISSING_PROBLEM_DATA: Coordinates for restaurant R-92 are missing."}[role]

    result = run_method("llmopt", script, problem=PROBLEM + "\nR-17=(25,85), demand=8; R-92 demand=12.")
    assert "Coordinates for restaurant R-92 are missing" in result["failure"]
    assert result["solve"] is None and result["code"] is None
    assert result["usage"]["llm_calls"] == 2 and result["usage"]["solves"] == 0
    assert not recorded_solves


def test_llmopt_rejected_code_keeps_original_source_and_actual_feedback(
    run_method: Any, recorded_solves: list[dict[str, Any]],
) -> None:
    seen: dict[str, list[str]] = {}
    feedback = "SOURCE_MISMATCH: R-92 must retain coordinate (35,25), not (20,80)."

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        seen.setdefault(role, []).append(messages[-1].text)
        if role == "five_element":
            return FORMULATION
        if role == "code":
            return CODE
        if len(seen[role]) == 1:
            return "The five-element is True.\nThe code is False.\nAnalysis:\n" + feedback
        return ACCEPT

    result = run_method("llmopt", script, problem=PROBLEM, data={"restaurants.csv": TABLE})
    assert not result["failure"]
    assert len(seen["code"]) == 2
    assert all(PROBLEM in prompt and TABLE in prompt for prompt in seen["code"])
    assert feedback in seen["code"][1] and PRODUCTION_CODE in seen["code"][1]
    assert result["usage"]["solves"] == len(recorded_solves) == 2
