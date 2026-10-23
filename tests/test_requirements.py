"""Requirements conversations keep drafts and history without running a modeling method or a solver."""

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from llm4om.budget import TokenBudget
from llm4om.graph import run
from llm4om.requirements import RequirementsContext, requirements_graph
from llm4om.runtime import Limits
from tests.conftest import LLM, PRODUCTION_PROBLEM, TWO_PART_REPLY, tool_call


def test_a_draft_update_finishes_the_turn_instead_of_repeating_forever(make_resources: Any) -> None:
    def reply(role: str, messages: list, tools: list) -> Any:
        if "update_draft" in tools:
            return tool_call("update_draft", description="按周计算成本。价格来源待确认。")
        assert "按周计算成本。价格来源待确认。" in messages[0].text
        assert "Web search is disabled" in messages[0].text
        return "已按周整理成本要求。若需查询实时价格，请开启联网搜索。"

    result = asyncio.run(requirements_graph().ainvoke(
        {"messages": [("human", "常见的价格和来源你联网搜索得到，成本按每周算。")], "description": "原稿：成本周期待确认。"},
        {"configurable": {"llm4om_resources": make_resources(reply, Limits(max_llm_calls=4))}}))
    assert result["failure"] is None, result["failure"]
    assert result["usage"]["llm_calls"] == 2
    assert result["messages"][-1].text.startswith("已按周整理")


def test_conversation_restores_history_and_respects_an_edited_draft(make_resources: Any) -> None:
    seen = []

    def reply(role: str, messages: list, tools: list) -> str:
        assert role == "requirements"
        assert tools == ([] if messages[-1].type == "tool" else ["update_draft"])
        seen.append(messages)
        if messages[-1].type == "tool":
            return "每个时段需要几人？" if len(seen) == 2 else "可以检查需求稿并用于建模。"
        return tool_call("update_draft", description="门店排班。每个时段的人数待确认。" if len(seen) == 1 else "门店排班，晚班至少 3 人。")

    async def check() -> None:
        graph = requirements_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": "conversation", "llm4om_resources": make_resources(reply)}}
        data = {"staff.csv": "name,hours\nAlice,8"}
        first = await graph.ainvoke({"messages": [HumanMessage("我想给门店排班")], "description": "", "data": data},
                                   config, context=RequirementsContext())
        assert [message.type for message in first["messages"]] == ["human", "ai", "tool", "ai"]
        assert first["usage"] == {"llm_calls": 2, "solves": 0, "input_tokens": 20, "output_tokens": 10}
        await graph.aupdate_state(config, {"description": "用户改稿：晚班至少 3 人。"}, as_node="discuss")
        second = await graph.ainvoke({"messages": [HumanMessage("其他要求不变")]}, config,
                                    context=RequirementsContext(locale="en"))
        assert len(second["messages"]) == 8
        assert second["data"] == data
        assert second["usage"]["llm_calls"] == 4 and second["usage"]["solves"] == 0
        assert "用户改稿：晚班至少 3 人。" in seen[2][0].text
        assert "staff.csv" in seen[2][0].text and "Alice,8" in seen[2][0].text
        assert seen[2][1].text == "我想给门店排班" and seen[2][2].text == first["messages"][1].text
        assert "English" in seen[2][0].text
        restored = await graph.aget_state(config)
        assert restored.values["description"] == second["description"]
        assert "test-key" not in str(restored.values)
        assert not {"code", "formulation", "solve", "spec"}.intersection(restored.values)

    asyncio.run(check())


def test_a_failed_turn_preserves_the_draft_and_retries_without_a_duplicate_message(make_resources: Any) -> None:
    replies = iter([tool_call("update_draft", description="不应提交的中间稿"), "",
                    tool_call("update_draft", description="保留合同，每种产品至少 5 件。"), "已整理。"])

    async def check() -> None:
        graph = requirements_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": "retry", "llm4om_resources": make_resources(lambda *_: next(replies))}}
        failed = await graph.ainvoke({"messages": [HumanMessage("请保留合同要求")], "description": "原需求稿", "data": {}}, config)
        assert "did not return a reply" in failed["failure"]
        assert failed["usage"]["llm_calls"] == 2
        saved = await graph.aget_state(config)
        assert saved.values["description"] == "原需求稿"
        assert len(saved.values["messages"]) == 1
        result = await graph.ainvoke({"messages": [saved.values["messages"][-1]]}, config)
        assert [message.type for message in result["messages"]] == ["human", "ai", "tool", "ai"]
        assert result["description"] == "保留合同，每种产品至少 5 件。"
        assert result["failure"] is None and result["usage"]["llm_calls"] == 4

    asyncio.run(check())


def test_requirements_use_the_selected_presets_daily_budget(make_resources: Any, tmp_path: Any) -> None:
    resources = replace(make_resources(lambda _, messages, __: "可以了" if messages[-1].type == "tool"
                                      else tool_call("update_draft", description="安排生产"), llm=None),
                        budget=TokenBudget(tmp_path, daily_limit=30))
    selected = resources.presets.add(LLM)

    async def check() -> None:
        graph = requirements_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": "budget", "llm4om_resources": resources}}
        await graph.ainvoke({"messages": [HumanMessage("安排生产")]}, config,
                           context=RequirementsContext(preset=selected.id))
        failed = await graph.ainvoke({"messages": [HumanMessage("接着聊")]}, config,
                                    context=RequirementsContext(preset=selected.id))
        assert "daily budget of 30 tokens" in failed["failure"]
        assert failed["usage"]["llm_calls"] == 2

    asyncio.run(check())


@pytest.mark.parametrize("method,language", [("direct", "pyomo"), ("feedback_repair", "ortools")])
def test_requirements_hand_off_only_problem_text_and_data(make_resources: Any, method: str, language: str) -> None:
    code = TWO_PART_REPLY if language == "pyomo" else '''### Formulation
Maximize 3 A + 2 B, using at most 8 units of each resource and integer quantities.
```python
from ortools.sat.python import cp_model
def build_model(data):
    m = cp_model.CpModel()
    a, b = m.new_int_var(0,8,'A'), m.new_int_var(0,8,'B')
    m.add(2*a+b<=8)
    m.add(a+2*b<=8)
    m.maximize(3*a+2*b)
    return m
```'''

    def reply(role: str, messages: list, tools: list) -> str:
        if role == "requirements":
            return ("The business problem is drafted." if messages[-1].type == "tool"
                    else tool_call("update_draft", description=PRODUCTION_PROBLEM))
        assert "CHAT_ONLY_MARKER" not in str(messages)
        return '{"action":"accept","reason":"Matches the problem."}' if role == "review" else code

    async def check() -> None:
        resources = make_resources(reply)
        draft = await requirements_graph().ainvoke({"messages": [HumanMessage("CHAT_ONLY_MARKER")],
                                                    "data": {"data.csv": "a,b\n1,2"}},
                                                   {"configurable": {"llm4om_resources": resources}})
        result = await run(draft["description"], data=draft["data"], method=method, language=language, resources=resources)
        assert result["solve"]["status"] == "optimal" and result["solve"]["objective"] == 13
        assert result["data"] == draft["data"]

    asyncio.run(check())
