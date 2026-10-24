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

from llm4om.agent import AgentContext, optimization_graph, solution_graph
from llm4om.graph import run
from llm4om.llm import LLMSettings
from llm4om.requirements import RequirementsContext, requirements_graph
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
    monkeypatch.setattr("llm4om.agent.get_client", lambda **kwargs: client)
    return client, snapshots, source


@pytest.mark.parametrize("kind", ["requirements", "optimization", "solution_chat"])
def test_each_conversation_applies_thinking_only_to_its_own_model(make_resources, monkeypatch, kind):
    def reply(role, messages, tools):
        assert "Simplified Chinese" in messages[0].text
        assert "简体中文" not in messages[0].text
        return "确认了，可以继续讨论。"

    resources = make_resources(reply, llm=LLMSettings(
        "deepseek", "deepseek-flash", api_key="test-key", extra_body={"thinking": {"type": "disabled"}}))
    _, _, source = checkpoint_client(monkeypatch, {"description": "原问题", "spec": {"preset": None}})
    seen = []
    factory = resources.model_factory

    def model(settings, **kwargs):
        seen.append(settings.extra_body["thinking"]["type"])
        return factory(settings, **kwargs)

    resources.model_factory = model
    graph = {"requirements": requirements_graph, "optimization": optimization_graph, "solution_chat": solution_graph}[kind]()
    context = RequirementsContext(thinking=True) if kind == "requirements" else AgentContext(thinking=True)
    result = asyncio.run(graph.ainvoke({"messages": [("human", "继续解释")], "source": source},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}}, context=context))
    assert result["failure"] is None, result["failure"]
    assert seen == ["enabled"]
    assert resources.llm.extra_body["thinking"]["type"] == "disabled"


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
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}}, context=AgentContext()))
    assert result["failure"] is None and not result["plans"]
    assert result["usage"]["llm_calls"] == 2 and result["usage"]["solves"] == 0
    client.threads.create.assert_not_called()
    assert snapshots[source["thread_id"]]["values"] == original


@pytest.mark.parametrize("factory", [optimization_graph, solution_graph])
def test_choosing_a_saved_plan_changes_the_next_turn_without_recalculating(make_resources, monkeypatch, factory):
    original = {"description": "原生产计划", "spec": {"preset": None},
                "solve": {"status": "optimal", "objective": 13, "variables": {"x[B]": 2}}}
    client, snapshots, source = checkpoint_client(monkeypatch, original)
    selected = {"thread_id": str(uuid4()), "checkpoint_id": str(uuid4())}
    snapshots[selected["thread_id"]] = {"values": {**original, "description": "B 至少生产 3 件",
        "solve": {"status": "optimal", "objective": 12, "variables": {"x[B]": 3}}},
        "checkpoint": {"checkpoint_id": selected["checkpoint_id"]}}

    def reply(role, messages, tools):
        facts = json.JSONDecoder().raw_decode(messages[0].text.split("Current frozen plan:\n", 1)[1])[0]
        assert len(facts["available_plans"]) == 2
        assert [plan["id"] for plan in facts["available_plans"]] == [source["thread_id"], selected["thread_id"]]
        assert facts["available_plans"][0]["original"]
        if messages[-1].type == "human" and "就用" in messages[-1].text:
            return tool_call("select_plan", plan_id=selected["thread_id"])
        assert '"objective": 12' in messages[0].text
        return "接下来就按 B 至少生产 3 件的方案继续。"

    async def check():
        graph = factory()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}
        await graph.aupdate_state(config, {"source": source, "current": source, "messages": [], "plans": [
            {"name": "原方案", "instruction": "原生产计划", "source": source, "group": None, "turn_id": "first"},
            {"name": "方案二", "instruction": "B 至少生产 3 件", "source": selected, "group": None, "turn_id": "earlier"}]}, as_node="discuss")
        chosen = await graph.ainvoke({"messages": [("human", "就用方案二，先别重新算")]}, config)
        assert chosen["failure"] is None, chosen["failure"]
        assert chosen["current"] == selected
        later = await graph.ainvoke({"messages": [("human", "我们现在讨论的条件是什么？")]}, config)
        assert later["failure"] is None and later["current"] == selected
        assert len(later["plans"]) == 2 and later["usage"]["solves"] == 0
        assert later["source"] == source

    asyncio.run(check())
    client.threads.create.assert_not_called()
    assert snapshots[source["thread_id"]]["values"] == original


def test_a_reply_failure_keeps_an_explicit_plan_selection(make_resources, monkeypatch):
    original = {"description": "原方案", "spec": {"preset": None}, "solve": {"status": "optimal", "objective": 13}}
    client, snapshots, source = checkpoint_client(monkeypatch, original)
    selected = {"thread_id": str(uuid4()), "checkpoint_id": str(uuid4())}
    snapshots[selected["thread_id"]] = {"values": {**original, "description": "选中的方案"},
        "checkpoint": {"checkpoint_id": selected["checkpoint_id"]}}

    def reply(role, messages, tools):
        if messages[-1].type == "human":
            return tool_call("select_plan", plan_id=selected["thread_id"])
        raise RuntimeError("reply unavailable")

    async def check():
        graph = solution_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}
        await graph.aupdate_state(config, {"source": source, "current": source, "messages": [], "plans": [{
            "name": "方案二", "instruction": "已算好的方案", "source": selected, "group": None, "turn_id": "earlier"}]}, as_node="discuss")
        result = await graph.ainvoke({"messages": [("human", "接下来就用方案二")]}, config)
        assert "reply unavailable" in result["failure"]
        assert result["current"] == selected and result["source"] == source

    asyncio.run(check())
    client.threads.create.assert_not_called()


@pytest.mark.parametrize("expression", ["__import__('os')", "v.clear()", "v['x[0]'] = 9", "1 / 0", "v['missing']", "True", "1e999"])
def test_calculator_input_errors_can_be_corrected_within_the_same_reply(make_resources, monkeypatch, expression):
    original = {"description": "实际零值", "spec": {"preset": None},
        "solve": {"status": "optimal", "objective": 0, "variables": {"x[0]": 0}}}
    client, snapshots, source = checkpoint_client(monkeypatch, original)

    def reply(role, messages, tools):
        if messages[-1].type == "human":
            return tool_call("calculate", expression=expression)
        if messages[-1].status == "error":
            return tool_call("calculate", expression="v['x[0]']")
        assert json.loads(messages[-1].text)["result"] == 0
        return "该决策的实际值是 0。"

    result = asyncio.run(solution_graph().ainvoke({"source": source, "messages": [("human", "核对实际决策")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}))
    assert result["failure"] is None, result["failure"]
    assert len([m for m in result["messages"] if m.type == "tool" and m.status == "error"]) == 1
    assert result["current"] == source and not result["plans"]
    assert snapshots[source["thread_id"]]["values"] == original
    client.threads.create.assert_not_called()


def test_variable_pages_can_reach_values_beyond_the_initial_snapshot(make_resources, monkeypatch):
    original = {"description": "250 项决策", "spec": {"preset": None},
        "solve": {"status": "optimal", "objective": 0, "variables": {f"x[{i}]": i for i in range(250)}}}
    _, snapshots, source = checkpoint_client(monkeypatch, original)

    def reply(role, messages, tools):
        if messages[-1].type == "human":
            return tool_call("lookup_variables", query="")
        facts = json.loads(messages[-1].text)
        if facts["next_offset"] is not None:
            return tool_call("lookup_variables", query="", offset=facts["next_offset"])
        assert len(facts["variables"]) == 50 and facts["variables"]["x[249]"] == 249
        return "最后一项的实际值是 249。"

    result = asyncio.run(solution_graph().ainvoke({"source": source, "messages": [("human", "最后一项的值是多少？")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}))
    assert result["failure"] is None, result["failure"]
    assert snapshots[source["thread_id"]]["values"] == original


def test_unrelated_arithmetic_does_not_read_or_switch_the_saved_plan(make_resources, monkeypatch):
    original = {"description": "原方案", "spec": {"preset": None},
        "solve": {"status": "optimal", "objective": 13, "variables": {"x[B]": 2}}}
    client, snapshots, source = checkpoint_client(monkeypatch, original)

    def reply(role, messages, tools):
        if messages[-1].type == "human":
            return tool_call("calculate", expression="19 * 23")
        facts = json.loads(messages[-1].text)
        assert facts["result"] == 437 and facts["source"] is None and facts["matched_variables"] == 0
        return "19 × 23 = 437。"

    result = asyncio.run(solution_graph().ainvoke({"source": source, "messages": [("human", "题外话，19乘23是多少？")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}))
    assert result["failure"] is None, result["failure"]
    assert result["current"] == source and not result["plans"]
    assert snapshots[source["thread_id"]]["values"] == original
    client.threads.create.assert_not_called()


def test_plan_arithmetic_uses_all_frozen_variables_and_does_not_solve(make_resources, monkeypatch):
    original = {"description": "250 项实际决策", "data": {}, "spec": {"preset": None},
        "solve": {"status": "optimal", "objective": 31125, "variables": {f"x[{i}]": i for i in range(250)}}}
    client, snapshots, source = checkpoint_client(monkeypatch, original)

    def reply(role, messages, tools):
        if messages[-1].type == "human":
            return tool_call("calculate", expression="sum(values)")
        result = json.loads(messages[-1].text)
        assert result["result"] == 31125 and result["matched_variables"] == 250
        return "250 项决策合计为 31,125。"

    result = asyncio.run(solution_graph().ainvoke({"source": source, "messages": [("human", "合计是多少？")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}))
    assert result["failure"] is None, result["failure"]
    assert result["current"] == source and result["usage"]["solves"] == 0
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
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}}, context=AgentContext()))
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
