"""The platform graph: steps in the order they happen, limits and the run deadline."""

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from llm4om.graph import RunContext, platform_graph, run
from llm4om.methods import methods
from llm4om.runtime import Limits
from llm4om.sandbox import Sandbox
from tests.conftest import ACCEPT_REVIEW, PRODUCTION_CODE, TWO_PART_REPLY

BROKEN_CODE = PRODUCTION_CODE.replace("return m", "return m.missing")


@pytest.mark.parametrize("name", ["需求（周）.csv", "prices (2026)+tax.json", "费用￥.csv"])
def test_attached_file_names_preserve_normal_punctuation(make_resources: Any, name: str) -> None:
    code = TWO_PART_REPLY.replace("    m =", f"    assert data[{name!r}] == 'actual data'\n    m =")
    result = asyncio.run(run("test", data={name: "actual data"}, resources=make_resources(lambda *_: code)))
    assert result["failure"] is None, result["failure"]
    assert result["solve"]["objective"] == 13


@pytest.mark.parametrize("name", ["../prices.csv", "folder/prices.csv", "folder\\prices.csv", "bad\x00.csv", "bad\n.csv", " ", ".", ".."])
def test_attachment_names_must_be_single_file_names(make_resources: Any, name: str) -> None:
    result = asyncio.run(run("test", data={name: "data"}, resources=make_resources(lambda *_: TWO_PART_REPLY)))
    assert result["failure"] and result["usage"] == {}


def test_a_node_update_is_recorded_before_the_next_node_starts(run_method: Any) -> None:
    broken = TWO_PART_REPLY.replace(PRODUCTION_CODE, BROKEN_CODE)
    replies = iter([broken, TWO_PART_REPLY, ACCEPT_REVIEW])
    record = run_method("feedback_repair", lambda *_: next(replies))
    order = [(step["type"], step["title"]) for step in record["steps"]]
    assert order == [("llm", "generate"), ("artifact", "生成数学模型和代码"), ("solve", "求解"),
                     ("llm", "repair"), ("artifact", "按反馈修正模型和代码"), ("solve", "求解（修正 1）"),
                     ("llm", "review"), ("artifact", "复核模型与求解结果")]


def test_llm_call_limit_stops_the_run(run_method: Any) -> None:
    broken = TWO_PART_REPLY.replace(PRODUCTION_CODE, BROKEN_CODE)
    record = run_method("feedback_repair", lambda *_: broken, limits=Limits(max_llm_calls=2))
    assert "limit of 2 LLM calls" in record["failure"]
    assert record["code"].strip() == BROKEN_CODE.strip() and record["steps"][-1]["type"] == "error"


def test_deadline_includes_final_solving(make_resources: Any) -> None:
    class SlowSandbox(Sandbox):
        cancelled = False

        async def solve(self, *args: Any, **kwargs: Any) -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def check() -> None:
        resources = make_resources(lambda *_: TWO_PART_REPLY, Limits(run_timeout=0.3))
        sandbox = resources.sandbox = SlowSandbox()
        result = await asyncio.wait_for(run("test", resources=resources), timeout=1)
        assert sandbox.cancelled and "time limit" in result["failure"]
        assert result["steps"][-1]["type"] == "error"
        assert not any(step.get("running") for step in result["steps"])

    asyncio.run(check())


def test_final_solve_limit_is_recorded(make_resources: Any) -> None:
    result = asyncio.run(run("test", resources=make_resources(lambda *_: TWO_PART_REPLY, Limits(max_solves=0))))
    assert "limit of 0 solves" in result["failure"]
    assert result["steps"][-1]["type"] == "error" and result["usage"]["solves"] == 0


@pytest.mark.parametrize("changed", [False, True])
def test_an_interrupted_resolve_cannot_attach_an_old_solution_to_new_code(run_method: Any, changed: bool) -> None:
    from tests.test_methods import FIVE_ELEMENT, JUDGED, by_role

    revised = PRODUCTION_CODE.replace('3 * m.x["A"]', '6 * m.x["A"]') if changed else PRODUCTION_CODE
    record = run_method("llmopt", by_role({"five_element": FIVE_ELEMENT,
        "code": [f"```python\n{PRODUCTION_CODE}```", f"```python\n{revised}```"],
        "self_correction": JUDGED.format(five="True", code="False")}), limits=Limits(max_solves=1))
    assert "limit of 1 solves" in record["failure"]
    assert record["code"].strip() == revised.strip()
    assert record["solve"] is None if changed else record["solve"]["objective"] == 13
    assert any(step.get("objective") == 13 for step in record["steps"])


def test_method_provides_parameters_without_a_platform_naming_convention(make_resources: Any) -> None:
    async def check() -> None:
        method = replace(methods()["direct"], id="external-method", parameters=lambda: {"samples": 7})
        graph = platform_graph(method)
        result = await graph.ainvoke({"description": "test"},
            {"configurable": {"llm4om_resources": make_resources(lambda *_: TWO_PART_REPLY)}}, context=RunContext())
        assert result["spec"]["method"] == "external-method"
        assert result["spec"]["parameters"] == {"samples": 7}

    asyncio.run(check())


def test_new_runs_cannot_reuse_old_or_user_supplied_results(make_resources: Any) -> None:
    async def check() -> None:
        graph = platform_graph(methods()["direct"])
        graph.checkpointer = InMemorySaver()
        replies = iter([TWO_PART_REPLY, TWO_PART_REPLY.replace('3 * m.x["A"]', '6 * m.x["A"]')])
        config = {"configurable": {"thread_id": "reused", "llm4om_resources": make_resources(lambda *_: next(replies))}}
        for expected in (13, 24):
            result = await graph.ainvoke({"description": "test", "data": {}, "solve": {"status": "optimal", "objective": 999},
                                          "usage": {"llm_calls": 1000}}, config, context=RunContext())
            assert result["solve"]["objective"] == expected
            assert result["usage"]["llm_calls"] == result["usage"]["solves"] == 1
            assert len(result["steps"]) == 3

    asyncio.run(check())
