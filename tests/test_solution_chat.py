"""Plan conversations read frozen results and calculate through the unchanged modeling pipeline."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from llm4om.graph import run
from llm4om.solution_chat import SolutionContext, solution_graph
from tests.conftest import PRODUCTION_PROBLEM, TWO_PART_REPLY, tool_call
from tests.test_followups import EXPLANATION, REVISED_REPLY


def checkpoint_client(monkeypatch: pytest.MonkeyPatch, original: dict) -> tuple[Any, dict, dict]:
    source = {"thread_id": str(uuid4()), "checkpoint_id": str(uuid4())}
    snapshots = {source["thread_id"]: {"values": deepcopy(original), "checkpoint": {"checkpoint_id": source["checkpoint_id"]}}}

    async def get(thread_id: str, **kwargs: Any) -> dict:
        if thread_id not in snapshots:
            response = httpx.Response(404, request=httpx.Request("GET", "http://api/threads/" + thread_id))
            raise httpx.HTTPStatusError("not found", request=response.request, response=response)
        return {"thread_id": thread_id, **snapshots[thread_id]}

    async def create(*, thread_id: str, supersteps: list, metadata: dict, **kwargs: Any) -> dict:
        assert metadata["parent"]["thread_id"] in snapshots
        snapshots[thread_id] = {"values": deepcopy(supersteps[0]["updates"][0]["values"]),
                                "checkpoint": {"checkpoint_id": str(uuid4())}, "metadata": metadata}
        return {"thread_id": thread_id}

    client = SimpleNamespace(threads=SimpleNamespace(get=AsyncMock(side_effect=get),
        get_state=AsyncMock(side_effect=get), create=AsyncMock(side_effect=create)))
    monkeypatch.setattr("llm4om.solution_chat.get_client", lambda **kwargs: client)
    return client, snapshots, source


def test_a_result_question_reads_actual_values_without_running_a_model(make_resources: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def reply(role: str, messages: list, tools: list) -> Any:
        if role != "solution_chat":
            return TWO_PART_REPLY
        if messages[-1].type == "human":
            return tool_call("lookup_variables", query="B")
        assert json.loads(messages[-1].text)["variables"] == {"x[B]": 2}
        return "B 的实际生产数量是 2。"

    resources = make_resources(reply)
    original = asyncio.run(run(PRODUCTION_PROBLEM, resources=resources))
    client, snapshots, source = checkpoint_client(monkeypatch, original)
    result = asyncio.run(solution_graph().ainvoke({"source": source, "messages": [("human", "B 的数量是多少？")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}}, context=SolutionContext()))
    assert result["failure"] is None and not result["plans"]
    assert result["usage"]["llm_calls"] == 2 and result["usage"]["solves"] == 0
    client.threads.create.assert_not_called()
    assert snapshots[source["thread_id"]]["values"] == original


def test_comparing_another_plan_reads_its_objective_conditions_and_status(make_resources: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    original = asyncio.run(run(PRODUCTION_PROBLEM, resources=make_resources(lambda *_: TWO_PART_REPLY)))
    client, snapshots, source = checkpoint_client(monkeypatch, original)
    current = {"thread_id": str(uuid4()), "checkpoint_id": str(uuid4())}
    snapshots[current["thread_id"]] = {"values": {**original, "description": PRODUCTION_PROBLEM + " B 至少生产 3 件。",
        "solve": {**original["solve"], "objective": 12, "variables": {"x[A]": 2, "x[B]": 3}}},
        "checkpoint": {"checkpoint_id": current["checkpoint_id"]}}

    def reply(role: str, messages: list, tools: list) -> Any:
        assert '"objective": 12' in messages[0].text
        if messages[-1].type == "human":
            return tool_call("lookup_variables", query="B", plan_id=source["thread_id"])
        facts = json.loads(messages[-1].text)
        assert facts["objective"] == 13 and facts["status"] == "optimal"
        assert facts["description"] == PRODUCTION_PROBLEM and facts["variables"] == {"x[B]": 2}
        return "新方案利润是 12，原方案是 13，减少 1。"

    async def check() -> dict:
        graph = solution_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}
        await graph.aupdate_state(config, {"source": source, "current": current, "messages": []}, as_node="discuss")
        return await graph.ainvoke({"messages": [("human", "比原方案改善了吗？")]}, config)

    result = asyncio.run(check())
    assert result["failure"] is None, result["failure"]
    assert result["current"] == current and result["usage"]["solves"] == 0
    client.threads.create.assert_not_called()


@pytest.mark.parametrize("multiple", [False, True])
def test_changes_use_the_existing_pipeline_and_save_real_results(make_resources: Any, monkeypatch: pytest.MonkeyPatch, multiple: bool) -> None:
    scenarios = [{"name": "B 至少 3 件", "instruction": "B 至少生产 3 件"}]
    if multiple:
        scenarios.append({"name": "B 至少 4 件", "instruction": "B 至少生产 4 件"})

    def reply(role: str, messages: list, tools: list) -> Any:
        if role == "solution_chat":
            if messages[-1].type == "human":
                return tool_call("solve_scenarios", scenarios=scenarios)
            assert "solve_scenarios" not in tools
            results = json.loads(messages[-1].text)
            assert [item["objective"] for item in results] == ([12, 8] if multiple else [12])
            return "以上数值来自实际求解。"
        if role == "revise_problem":
            value = json.loads(messages[-1].text)
            return value["original_problem"] + "\n" + value["change_request"]
        if role == "explain_result":
            return EXPLANATION
        return REVISED_REPLY.replace('>= 3)', '>= 4)') if "B 至少生产 4 件" in str(messages) else REVISED_REPLY

    resources = make_resources(reply)
    original = asyncio.run(run(PRODUCTION_PROBLEM, data={"capacity.csv": "capacity\n8\n"},
                              resources=make_resources(lambda *_: TWO_PART_REPLY)))
    client, snapshots, source = checkpoint_client(monkeypatch, original)
    result = asyncio.run(solution_graph().ainvoke({"source": source, "messages": [HumanMessage("请计算这些新条件")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}}, context=SolutionContext()))
    assert result["failure"] is None, result["failure"]
    assert len(result["plans"]) == len(scenarios) and result["usage"]["llm_calls"] == 2
    assert result["current"] == (source if multiple else result["plans"][0]["source"])
    for plan in result["plans"]:
        values = snapshots[plan["source"]["thread_id"]]["values"]
        assert values["data"] == original["data"] and values["spec"]["method"] == "direct"
        assert values["solve"]["status"] == "optimal" and values["usage"]["solves"] == 1
        assert values["timing"]["finished_at"]
        assert "test-key" not in json.dumps(values)
    assert snapshots[source["thread_id"]]["values"] == original
    assert client.threads.create.await_count == len(scenarios)


def test_a_later_question_uses_the_new_current_plan(make_resources: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def reply(role: str, messages: list, tools: list) -> Any:
        if role == "solution_chat":
            if messages[-1].type == "human":
                return (tool_call("lookup_variables", query="B") if "再查询" in messages[-1].text else
                        tool_call("solve_scenarios", scenarios=[{"name": "B 至少 3 件", "instruction": "B 至少生产 3 件"}]))
            if messages[-1].name == "lookup_variables":
                assert json.loads(messages[-1].text)["variables"] == {"x[B]": 3}
            return "已按当前方案的实际结果回答。"
        if role == "revise_problem":
            request = json.loads(messages[-1].text)
            return request["original_problem"] + "\n" + request["change_request"]
        return EXPLANATION if role == "explain_result" else REVISED_REPLY

    resources = make_resources(reply)
    original = asyncio.run(run(PRODUCTION_PROBLEM, resources=make_resources(lambda *_: TWO_PART_REPLY)))
    _, snapshots, source = checkpoint_client(monkeypatch, original)

    async def check() -> None:
        graph = solution_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}}
        first = await graph.ainvoke({"source": source, "messages": [("human", "请把 B 至少生产 3 件再计算")]}, config)
        second = await graph.ainvoke({"messages": [("human", "再查询 B 的实际数量")]}, config)
        assert second["current"] == first["current"] and len(second["plans"]) == 1
        assert second["failure"] is None and second["usage"]["llm_calls"] == 4
        assert snapshots[source["thread_id"]]["values"] == original

    asyncio.run(check())


def test_retrying_a_failed_explanation_keeps_the_calculation_without_repeating_it(make_resources: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def reply(role: str, messages: list, tools: list) -> Any:
        if role == "solution_chat":
            if '"already_computed_scenarios":' in messages[0].text:
                assert "solve_scenarios" not in tools
                assert '"objective": 12' in messages[0].text
                return "已完成的实际目标值是 12，没有重复计算。"
            if messages[-1].type == "human":
                return tool_call("solve_scenarios", scenarios=[{"name": "B 至少 3 件", "instruction": "B 至少生产 3 件"}])
            raise RuntimeError("reply unavailable")
        if role == "revise_problem":
            value = json.loads(messages[-1].text)
            return value["original_problem"] + "\n" + value["change_request"]
        return EXPLANATION if role == "explain_result" else REVISED_REPLY

    resources = make_resources(reply)
    original = asyncio.run(run(PRODUCTION_PROBLEM, resources=make_resources(lambda *_: TWO_PART_REPLY)))
    client, _, source = checkpoint_client(monkeypatch, original)

    async def check() -> None:
        graph = solution_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}}
        failed = await graph.ainvoke({"source": source, "messages": [("human", "请按 B 至少生产 3 件计算")]}, config)
        assert "reply unavailable" in failed["failure"] and len(failed["plans"]) == 1
        result = await graph.ainvoke({"messages": [failed["messages"][-1]]}, config)
        assert result["failure"] is None and len(result["plans"]) == 1
        assert len([message for message in result["messages"] if message.type == "human"]) == 1
        client.threads.create.assert_awaited_once()

    asyncio.run(check())


@pytest.mark.parametrize("resume", [True, False])
def test_a_partly_saved_batch_keeps_its_base_and_can_be_resumed_or_left_behind(make_resources: Any, monkeypatch: pytest.MonkeyPatch, resume: bool) -> None:
    scenarios = [{"name": f"B 至少 {n} 件", "instruction": f"B 至少生产 {n} 件"} for n in (3, 4)]
    revised = []

    def reply(role: str, messages: list, tools: list) -> Any:
        if role == "solution_chat":
            if messages[-1].type == "human":
                if "只解释当前方案" in messages[-1].text:
                    assert '"unfinished_scenarios":' not in messages[0].text
                    assert '"objective": 13' in messages[0].text
                    return "当前方案仍为原方案，实际目标值 13。"
                assert "solve_scenarios" in tools
                request = [{**item, "name": item["name"] + "（重试改名）"} for item in scenarios] if '"unfinished_scenarios":' in messages[0].text else scenarios
                return tool_call("solve_scenarios", scenarios=request)
            return "两个方案的实际目标值分别是 12 和 8。"
        if role == "revise_problem":
            request = json.loads(messages[-1].text)
            revised.append(request["change_request"])
            return request["original_problem"] + "\n" + request["change_request"]
        if role == "explain_result":
            return EXPLANATION
        return REVISED_REPLY.replace('>= 3)', '>= 4)') if "B 至少生产 4 件" in str(messages) else REVISED_REPLY

    original = asyncio.run(run(PRODUCTION_PROBLEM, resources=make_resources(lambda *_: TWO_PART_REPLY)))
    client, snapshots, source = checkpoint_client(monkeypatch, original)
    save = client.threads.create.side_effect

    async def fail_second_save(**kwargs: Any) -> dict:
        if client.threads.create.await_count == 2:
            raise RuntimeError("temporary storage failure")
        return await save(**kwargs)

    client.threads.create.side_effect = fail_second_save

    async def check() -> None:
        graph = solution_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}
        failed = await graph.ainvoke({"source": source, "messages": [("human", "分别计算 B 至少生产 3 件和至少生产 4 件")]}, config)
        assert failed["failure"] and len(failed["plans"]) == 1
        assert failed["current"] == source
        if not resume:
            result = await graph.ainvoke({"messages": [("human", "只解释当前方案，不要继续计算")]}, config)
            assert result["failure"] is None and result["pending"] is None
            assert result["current"] == source and len(result["plans"]) == 1
            assert client.threads.create.await_count == 2
            return
        result = await graph.ainvoke({"messages": [failed["messages"][-1]]}, config)
        assert result["failure"] is None, result["failure"]
        assert result["current"] == source and len(result["plans"]) == 2
        assert [snapshots[plan["source"]["thread_id"]]["values"]["solve"]["objective"] for plan in result["plans"]] == [12, 8]
        assert revised.count("B 至少生产 3 件") == 1
        assert all(snapshots[plan["source"]["thread_id"]]["metadata"]["parent"] == source for plan in result["plans"])
        assert len([message for message in result["messages"] if message.type == "human"]) == 1

    asyncio.run(check())


def test_modeling_messages_do_not_leak_into_the_conversation_stream(make_resources: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def reply(role: str, messages: list, tools: list) -> Any:
        if role == "solution_chat":
            return (tool_call("solve_scenarios", scenarios=[{"name": "B 至少 3 件", "instruction": "B 至少生产 3 件"}])
                    if messages[-1].type == "human" else "实际求解结果为 12。")
        if role == "revise_problem":
            request = json.loads(messages[-1].text)
            return request["original_problem"] + "\n" + request["change_request"]
        return EXPLANATION if role == "explain_result" else REVISED_REPLY

    resources = make_resources(reply)
    original = asyncio.run(run(PRODUCTION_PROBLEM, resources=make_resources(lambda *_: TWO_PART_REPLY)))
    _, _, source = checkpoint_client(monkeypatch, original)

    async def check() -> None:
        roles = []
        progress = []
        async for _, mode, data in solution_graph().astream(
                {"source": source, "messages": [("human", "请按新条件计算")]},
                {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}},
                stream_mode=["messages", "custom"], subgraphs=True):
            if mode == "custom":
                progress.append(data)
            else:
                message, metadata = data
                if message.type != "tool":
                    roles.append(metadata.get("llm4om_role"))
                    assert "build_model" not in message.text
        assert roles and set(roles) == {"solution_chat"}
        assert {item["stage"] for item in progress} == {"revise", "model", "solve", "explain"}
        assert all(item["index"] == item["total"] == 1 and item["tool_call_id"] for item in progress)
        assert "build_model" not in str(progress) and "test-key" not in str(progress)

    asyncio.run(check())
