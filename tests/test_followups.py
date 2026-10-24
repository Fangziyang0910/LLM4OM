"""Platform follow-ups reuse a method without changing its modeling steps or solved values."""

import asyncio
import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from llm4om.graph import RunContext, platform_graph, run
from llm4om.methods import methods
from llm4om.runtime import Limits
from llm4om.sandbox import SolveResult
from tests.conftest import PRODUCTION_CODE, PRODUCTION_PROBLEM, TWO_PART_REPLY

EXPLANATION = json.dumps({
    "summary": "按下表安排两种产品的生产。", "objective_label": "总利润", "objective_unit": "元",
    "decisions": [{"variable": "x[A]", "label": "A 产品生产数量", "unit": "件"},
                  {"variable": "x[B]", "label": "B 产品生产数量", "unit": "件"}],
    "notes": ["生产数量为非负整数。"],
}, ensure_ascii=False)
REVISED = PRODUCTION_PROBLEM + "\nB 至少生产 3 件。"
REVISED_REPLY = TWO_PART_REPLY.replace("    return m", '    m.minimum_b = pyo.Constraint(expr=m.x["B"] >= 3)\n    return m')
INFEASIBLE_REPLY = TWO_PART_REPLY.replace("    return m", '    m.contract = pyo.Constraint(m.P, rule=lambda m, p: m.x[p] >= 5)\n    return m')


def test_infeasibility_explanation_uses_real_conflicts_and_keeps_the_model(make_resources: Any) -> None:
    roles = []

    def reply(role: str, messages: Any, *_: Any) -> str:
        roles.append(role)
        if role == "explain_infeasibility":
            assert "English" in messages[0].content
            facts = json.loads(messages[-1].content)
            assert facts["tool"] == "Gurobi IIS"
            assert any("contract" in item for item in facts["constraints"].values())
            return json.dumps({"summary": "The contract quantities exceed the available resources.",
                               "conflicts": [{"constraint_ids": list(map(int, facts["constraints"])),
                                              "explanation": "The minimum quantities and capacity cannot hold together."}],
                               "adjustments": [{"title": "Review contract quantities", "instruction": "Remove the minimum contract quantities. Keep all other requirements."}]})
        assert "Gurobi IIS" not in messages[-1].content
        return INFEASIBLE_REPLY

    result = asyncio.run(run(PRODUCTION_PROBLEM + " Each product must be at least 5.", explain=True, locale="en",
                             resources=make_resources(reply)))
    assert roles == ["generate", "explain_infeasibility"]
    assert result["failure"] is None and result["explanation_error"] is None
    assert result["solve"]["status"] == "infeasible" and result["explanation"] is None
    assert result["infeasibility"]["conflicts"][0]["constraints"] == result["solve"]["diagnosis"]["items"]
    assert result["infeasibility"]["adjustments"][0]["instruction"].startswith("Remove")
    assert 'rule=lambda m, p: m.x[p] >= 5' in result["code"]
    assert result["usage"]["solves"] == 1


@pytest.mark.parametrize("status,diagnosis", [
    ("infeasible", None),
    ("infeasible", {"tool": "Gurobi IIS", "items": [], "total": 0, "error": "No license"}),
    ("locally_infeasible", {"tool": "test", "items": ["x >= 2", "x <= 1"], "total": 2, "error": None}),
    ("infeasible_or_unbounded", None),
])
def test_no_conflict_is_invented_without_a_diagnosed_infeasible_model(make_resources: Any, status: str,
                                                                    diagnosis: Any, monkeypatch: Any) -> None:
    roles = []
    resources = make_resources(lambda role, *_: roles.append(role) or TWO_PART_REPLY)

    async def solve(*_: Any, **__: Any) -> SolveResult:
        return SolveResult(status, None, {}, "", None, diagnosis)

    monkeypatch.setattr(resources.sandbox, "solve", solve)
    result = asyncio.run(run(PRODUCTION_PROBLEM, explain=True, resources=resources))
    assert roles == ["generate"] and result["infeasibility"] is None
    assert result["solve"]["status"] == status


def test_invalid_conflict_references_do_not_discard_the_diagnosis(make_resources: Any) -> None:
    invalid = json.dumps({"summary": "Conflict", "conflicts": [{"constraint_ids": [999], "explanation": "Invalid"}]})
    result = asyncio.run(run(PRODUCTION_PROBLEM, explain=True,
                             resources=make_resources(lambda role, *_: invalid if role == "explain_infeasibility" else INFEASIBLE_REPLY)))
    assert result["failure"] is None and result["solve"]["status"] == "infeasible"
    assert result["solve"]["diagnosis"]["items"]
    assert result["infeasibility"] is None and "actual solver diagnosis" in result["explanation_error"]


def test_business_explanation_references_the_actual_solved_model(make_resources: Any) -> None:
    roles = []

    def reply(role: str, messages: Any, tools: Any) -> str:
        roles.append(role)
        if role == "explain_result":
            assert "Simplified Chinese" in messages[0].content
            facts = json.loads(messages[-1].content)
            assert facts["objective"] == 13
            assert facts["variables"] == {"x[A]": 3, "x[B]": 2}
            return EXPLANATION
        return TWO_PART_REPLY

    result = asyncio.run(run(PRODUCTION_PROBLEM, explain=True, resources=make_resources(reply)))
    assert roles == ["generate", "explain_result"]
    assert result["failure"] is None and result["explanation_error"] is None
    assert result["explanation"]["objective_label"] == "总利润"
    assert result["solve"]["objective"] == 13 and result["code"] == PRODUCTION_CODE
    assert result["usage"]["llm_calls"] == 2 and result["usage"]["solves"] == 1


def test_bad_explanation_cannot_invalidate_a_solved_model(make_resources: Any) -> None:
    invalid = EXPLANATION.replace("x[A]", "invented_variable")
    result = asyncio.run(run(PRODUCTION_PROBLEM, explain=True,
        resources=make_resources(lambda role, *_: invalid if role == "explain_result" else TWO_PART_REPLY)))
    assert result["failure"] is None and result["solve"]["objective"] == 13
    assert result["explanation"] is None and "actual solution" in result["explanation_error"]


def test_explanation_respects_the_budget_without_discarding_the_solution(make_resources: Any) -> None:
    result = asyncio.run(run(PRODUCTION_PROBLEM, explain=True,
        resources=make_resources(lambda *_: TWO_PART_REPLY, Limits(max_llm_calls=1))))
    assert result["failure"] is None and result["solve"]["objective"] == 13
    assert "limit of 1 LLM calls" in result["explanation_error"]


def test_an_explanation_timeout_has_a_readable_error_and_keeps_the_solution(make_resources: Any) -> None:
    def reply(role: str, *_: Any) -> str:
        if role == "explain_result":
            raise TimeoutError()
        return TWO_PART_REPLY

    result = asyncio.run(run(PRODUCTION_PROBLEM, explain=True, resources=make_resources(reply)))
    assert result["failure"] is None and result["solve"]["objective"] == 13
    assert result["explanation_error"] == "TimeoutError"


def test_revision_passes_the_new_problem_to_the_same_modeling_method(make_resources: Any) -> None:
    roles = []

    def reply(role: str, messages: Any, tools: Any) -> str:
        roles.append(role)
        if role == "revise_problem":
            request = json.loads(messages[-1].content)
            assert request["original_problem"] == PRODUCTION_PROBLEM
            assert request["change_request"] == "B 至少生产 3 件"
            assert request["data_files"] == ["capacity.csv"]
            return REVISED
        assert REVISED in messages[-1].content and "capacity.csv" in messages[-1].content
        return REVISED_REPLY

    result = asyncio.run(run(PRODUCTION_PROBLEM, change="B 至少生产 3 件", data={"capacity.csv": "capacity\n8"},
                             resources=make_resources(reply)))
    assert roles == ["revise_problem", "generate"]
    assert result["description"] == REVISED
    assert result["revision"] == {"description": PRODUCTION_PROBLEM, "instruction": "B 至少生产 3 件"}
    assert result["data"] == {"capacity.csv": "capacity\n8"}
    assert result["solve"]["objective"] == 12 and result["spec"]["method"] == "direct"
    assert result["solve"]["variables"] == {"x[A]": 2, "x[B]": 3}


def test_capacity_revision_keeps_the_resource_upper_bound(make_resources: Any) -> None:
    original = "Produce integer A and B, each at least 5. Profit is 3A+2B. Cutting usage 2A+B must not exceed 8. Maximize profit."
    revised = original.replace("exceed 8", "exceed 15")
    code = PRODUCTION_CODE.replace('    m.machining = pyo.Constraint(expr=m.x["A"] + 2 * m.x["B"] <= 8)\n', '')
    code = code.replace('<= 8', '<= 15').replace('    return m', '    m.contract = pyo.Constraint(m.P, rule=lambda m, p: m.x[p] >= 5)\n    return m')

    def reply(role: str, messages: Any, *_: Any) -> str:
        if role == "revise_problem":
            assert json.loads(messages[-1].content)["original_problem"] == original
            return revised
        assert revised in messages[-1].content
        return f"### Formulation\nMaximize 3A+2B, with A,B integer and >=5, 2A+B<=15.\n\n```python\n{code}```"

    result = asyncio.run(run(original, change="Set the cutting capacity upper bound to 15; preserve the contract quantities.",
                             resources=make_resources(reply)))
    assert result["description"] == revised and result["revision"]["description"] == original
    assert result["solve"]["status"] == "optimal" and result["solve"]["objective"] == 25
    assert result["solve"]["variables"] == {"x[A]": 5, "x[B]": 5}


def test_empty_revision_stops_before_modeling(make_resources: Any) -> None:
    roles = []

    def reply(role: str, *_: Any) -> str:
        roles.append(role)
        return ""

    result = asyncio.run(run(PRODUCTION_PROBLEM, change="B 至少生产 3 件", resources=make_resources(reply)))
    assert roles == ["revise_problem"]
    assert result["solve"] is None and result["description"] == PRODUCTION_PROBLEM
    assert "did not produce" in result["failure"]


def test_a_later_run_does_not_repeat_an_old_change_request(make_resources: Any) -> None:
    roles = []

    def reply(role: str, messages: Any, tools: Any) -> str:
        roles.append(role)
        if role == "revise_problem":
            return REVISED
        return REVISED_REPLY if REVISED in messages[-1].content else TWO_PART_REPLY

    async def check() -> None:
        graph = platform_graph(methods()["direct"])
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": "revision", "llm4om_resources": make_resources(reply)}}
        first = await graph.ainvoke({"description": PRODUCTION_PROBLEM, "change": "B 至少生产 3 件"}, config, context=RunContext())
        second = await graph.ainvoke({"description": PRODUCTION_PROBLEM}, config, context=RunContext())
        assert first["solve"]["objective"] == 12 and second["solve"]["objective"] == 13
        assert second["revision"] is None and second["change"] is None
        assert roles == ["revise_problem", "generate", "generate"]

    asyncio.run(check())
