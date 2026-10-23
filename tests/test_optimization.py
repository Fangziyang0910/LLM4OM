"""The primary conversation delegates first and later calculations to the platform graphs."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from llm4om.agent import AgentContext, optimization_graph
from tests.conftest import ACCEPT_REVIEW, PRODUCTION_CODE, PRODUCTION_PROBLEM, TWO_PART_REPLY, tool_call
from tests.test_followups import EXPLANATION, REVISED_REPLY
from tests.test_sandbox import ORTOOLS_CODE


@pytest.fixture
def saved_plans(monkeypatch):
    snapshots = {}

    async def get(identifier, **kwargs):
        if identifier not in snapshots:
            response = httpx.Response(404, request=httpx.Request("GET", "http://api/threads/" + identifier))
            raise httpx.HTTPStatusError("not found", request=response.request, response=response)
        return deepcopy(snapshots[identifier])

    async def create(*, thread_id, metadata, supersteps, **kwargs):
        snapshots[thread_id] = {"values": deepcopy(supersteps[0]["updates"][0]["values"]),
            "metadata": metadata, "checkpoint": {"checkpoint_id": str(uuid4())}}
        return {"thread_id": thread_id}

    client = SimpleNamespace(threads=SimpleNamespace(get=AsyncMock(side_effect=get),
        get_state=AsyncMock(side_effect=get), create=AsyncMock(side_effect=create)))
    monkeypatch.setattr("llm4om.agent.get_client", lambda **kwargs: client)
    return snapshots, client


def test_an_initial_idea_can_be_discussed_without_creating_a_run(make_resources, saved_plans):
    def reply(role, messages, tools):
        assert role == "optimization" and "model_and_solve" in tools
        assert "lookup_variables" not in tools and "solve_scenarios" not in tools
        assert "staff.csv" in messages[0].text
        return "每班需要几个人？每个人最多工作几天？"

    result = asyncio.run(optimization_graph().ainvoke({"messages": [("human", "帮我排班")],
        "data": {"staff.csv": "name\nA"}}, {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}))
    assert result["failure"] is None and result["plans"] == []
    saved_plans[1].threads.create.assert_not_called()


@pytest.mark.parametrize("retry_reply", [False, True])
def test_a_first_solve_is_saved_and_later_changes_use_its_frozen_result(make_resources, saved_plans, retry_reply):
    snapshots, client = saved_plans
    attempts = []

    def reply(role, messages, tools):
        if role == "optimization":
            if '"already_computed_scenarios":' in messages[0].text:
                assert "model_and_solve" not in tools
                return "已经算好的目标值是 13。"
            if messages[-1].type == "human":
                if "再调整" in messages[-1].text:
                    return tool_call("solve_scenarios", scenarios=[{"name": "B 至少 3 件", "instruction": "B 至少生产 3 件"}])
                return tool_call("model_and_solve", description=PRODUCTION_PROBLEM, name="生产计划")
            assert "model_and_solve" not in tools
            if retry_reply and not attempts:
                attempts.append(True)
                raise RuntimeError("final reply failed")
            return "计算完成。"
        if role == "revise_problem":
            request = json.loads(messages[-1].text)
            return request["original_problem"] + "\n" + request["change_request"]
        if role == "explain_result":
            return EXPLANATION
        return REVISED_REPLY if "B 至少生产 3 件" in str(messages) else TWO_PART_REPLY

    async def check():
        graph = optimization_graph()
        graph.checkpointer = InMemorySaver()
        config = {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}
        first = await graph.ainvoke({"messages": [("human", "请计算生产计划")], "data": {"capacity.csv": "capacity\n8"}}, config)
        assert bool(first["failure"]) == retry_reply
        if retry_reply:
            first = await graph.ainvoke({"messages": [first["messages"][-1]]}, config)
            assert first["failure"] is None
            assert len([m for m in first["messages"] if m.type == "human"]) == 1
            client.threads.create.assert_awaited_once()
        source = first["current"]
        original = deepcopy(snapshots[source["thread_id"]])
        assert original["values"]["solve"]["objective"] == 13
        assert original["values"]["data"] == {"capacity.csv": "capacity\n8"}
        assert original["metadata"]["conversation"] == config["configurable"]["thread_id"]
        assert original["metadata"]["origin"] == config["configurable"]["thread_id"]
        second = await graph.ainvoke({"messages": [("human", "再调整 B 至少生产 3 件")]}, config)
        assert second["failure"] is None, second["failure"]
        assert second["source"] == source and second["current"] != source
        assert snapshots[second["current"]["thread_id"]]["values"]["solve"]["objective"] == 12
        assert snapshots[source["thread_id"]] == original
        assert "test-key" not in json.dumps(snapshots)

    asyncio.run(check())


def test_pinned_configuration_wins_over_agent_arguments(make_resources, saved_plans):
    def reply(role, messages, tools):
        if role == "optimization":
            return (tool_call("model_and_solve", description=PRODUCTION_PROBLEM, name="生产计划", method="trival", language="gurobipy")
                    if messages[-1].type == "human" else "实际求解完成。")
        return EXPLANATION if role == "explain_result" else TWO_PART_REPLY

    result = asyncio.run(optimization_graph().ainvoke({"messages": [("human", "请计算")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}},
        context=AgentContext(method="direct", language="pyomo")))
    assert result["failure"] is None, result["failure"]
    actual = saved_plans[0][result["current"]["thread_id"]]["values"]
    assert actual["spec"]["method"] == "direct" and actual["spec"]["language"] == "pyomo"
    assert actual["solve"]["objective"] == 13


@pytest.mark.parametrize("method, expected, library, code", [("Direct", "direct", "Pyomo", TWO_PART_REPLY),
    ("Feedback Repair", "feedback_repair", "Pyomo", TWO_PART_REPLY),
    ("Direct", "direct", "OR-Tools", TWO_PART_REPLY.replace(PRODUCTION_CODE, ORTOOLS_CODE))],
    ids=["direct-pyomo", "feedback-repair-pyomo", "direct-ortools"])
def test_tool_arguments_accept_registered_display_names_and_save_canonical_ids(make_resources, saved_plans, method, expected, library, code):
    def reply(role, messages, tools):
        if role == "optimization":
            return (tool_call("model_and_solve", description=PRODUCTION_PROBLEM, name="生产计划", method=method, language=library)
                    if messages[-1].type == "human" else "实际求解完成。")
        return EXPLANATION if role == "explain_result" else ACCEPT_REVIEW if role == "review" else code

    result = asyncio.run(optimization_graph().ainvoke({"messages": [("human", "请计算")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}))
    assert result["failure"] is None, result["failure"]
    actual = saved_plans[0][result["current"]["thread_id"]]["values"]
    assert actual["spec"]["method"] == expected and actual["spec"]["language"] == ("ortools" if library == "OR-Tools" else "pyomo")
    assert actual["solve"]["objective"] == 13


def test_available_methods_and_backends_come_from_the_registry(make_resources, saved_plans):
    def reply(role, messages, tools):
        if messages[-1].type == "human":
            return tool_call("modeling_capabilities")
        facts = json.loads(messages[-1].text)
        assert len(facts["methods"]) == 13 and len(facts["libraries"]) == 9
        assert next(m for m in facts["methods"] if m["id"] == "optimus")["linear_only"]
        assert "backends" in facts
        return "可以选择十三种方法和九个建模库。"

    resources = make_resources(reply)
    resources.sandbox.catalog = AsyncMock(return_value={"libraries": {"pyomo": []}})
    result = asyncio.run(optimization_graph().ainvoke({"messages": [("human", "有哪些方法？")]},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": resources}}))
    assert result["failure"] is None
    resources.sandbox.catalog.assert_awaited_once()
    saved_plans[1].threads.create.assert_not_called()


def test_rejected_input_does_not_become_a_frozen_modeling_baseline(make_resources, saved_plans):
    def reply(role, messages, tools):
        assert role == "optimization"
        if messages[-1].type == "human":
            return tool_call("model_and_solve", description=PRODUCTION_PROBLEM, name="生产计划")
        assert "lookup_variables" not in tools and "solve_scenarios" not in tools
        assert json.loads(messages[-1].text)["failure"]
        return "请修正附件名称后再计算。"

    result = asyncio.run(optimization_graph().ainvoke({"messages": [("human", "请计算")], "data": {"../invalid.csv": "1"}},
        {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}}))
    assert result["failure"] is None, result["failure"]
    assert not result.get("current") and not result.get("source")
    assert len(result["plans"]) == 1


def test_steps_stream_to_the_workspace_without_entering_agent_messages(make_resources, saved_plans):
    def reply(role, messages, tools):
        if role == "optimization":
            return (tool_call("model_and_solve", description=PRODUCTION_PROBLEM, name="生产计划")
                    if messages[-1].type == "human" else "实际目标值为 13。")
        return EXPLANATION if role == "explain_result" else TWO_PART_REPLY

    async def check():
        events, roles = [], []
        async for _, mode, data in optimization_graph().astream({"messages": [("human", "请计算生产计划")]},
                {"configurable": {"thread_id": str(uuid4()), "llm4om_resources": make_resources(reply)}},
                stream_mode=["messages", "custom"], subgraphs=True):
            if mode == "custom":
                events.append(data)
            else:
                message, metadata = data
                if message.type != "tool":
                    roles.append(metadata.get("llm4om_role"))
                    assert "build_model" not in message.text
        assert roles and set(roles) == {"optimization"}
        assert any(event["step"].get("formulation") for event in events)
        assert any(event["step"].get("code") for event in events)
        assert any(event["step"]["type"] == "solve" for event in events)
        assert all(event["tool_call_id"] and event["method"] == "direct" for event in events)
        assert "test-key" not in str(events)

    asyncio.run(check())
