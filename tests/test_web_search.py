"""The search tool binds credentials to an endpoint and persists public sources, never keys."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from llm4om.llm import LLMSettings
from llm4om.requirements import RequirementsContext, requirements_graph
from llm4om.web_search import search_tool
from tests.conftest import LLM, tool_call


@pytest.mark.parametrize("dedicated", [False, True])
def test_search_uses_the_correct_credential_and_returns_sources(monkeypatch: pytest.MonkeyPatch, dedicated: bool) -> None:
    monkeypatch.delenv("LLM4OM_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("LLM4OM_SEARCH_BASE_URL", raising=False)
    settings = LLMSettings(provider="deepseek", api_key="model-secret", model="deepseek-flash",
                           base_url="https://relay.example/v1")
    if dedicated:
        monkeypatch.setenv("LLM4OM_SEARCH_API_KEY", "search-secret")
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"results": [{"title": "Staff scheduling", "url": "https://example.org/scheduling",
                                                      "snippet": "Reference only", "date": "2026-10-23"}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    message = asyncio.run(search_tool(settings).ainvoke({"type": "tool_call", "name": "web_search", "id": "search_1",
                                                         "args": {"query": "staff scheduling"}}))
    assert str(seen[0].url) == ("https://api.deepseek.com/v1/tools/search" if dedicated else "https://relay.example/v1/tools/search")
    assert seen[0].headers["authorization"] == ("Bearer search-secret" if dedicated else "Bearer model-secret")
    assert json.loads(seen[0].content) == {"query": "staff scheduling", "count": 5, "need_content": False}
    assert message.artifact["results"][0]["url"] == "https://example.org/scheduling"
    assert message.artifact["error"] is None
    assert "secret" not in str(message)


@pytest.mark.parametrize("status,payload", [(403, {}), (200, {"results": [{"title": "Unsafe", "url": "javascript:alert(1)"}]})])
def test_failed_or_malformed_searches_do_not_publish_sources(monkeypatch: pytest.MonkeyPatch, status: int, payload: dict) -> None:
    monkeypatch.setenv("LLM4OM_SEARCH_API_KEY", "search-secret")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=payload)), **kwargs))
    message = asyncio.run(search_tool(LLM).ainvoke({"type": "tool_call", "name": "web_search", "id": "search_1",
                                                    "args": {"query": "scheduling"}}))
    assert message.artifact["error"] and not message.artifact["results"]
    assert "search-secret" not in str(message) and "javascript" not in str(message)


def test_agent_searches_updates_draft_and_keeps_actual_sources(make_resources: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM4OM_SEARCH_API_KEY", "search-secret")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"results": [{"title": "Reference", "url": "https://example.org/guide"}]})), **kwargs))

    def reply(role, messages, tools):
        assert role == "requirements"
        assert ("web_search" in tools) == (messages[-1].name != "update_draft")
        assert ("update_draft" in tools) == (messages[-1].name != "update_draft")
        if messages[-1].type == "human":
            return tool_call("web_search", query="staff scheduling public guide")
        if messages[-1].name == "web_search":
            assert "https://example.org/guide" in messages[-1].text
            return tool_call("update_draft", description="门店排班。参考建议待用户确认。")
        return "请确认是否使用这份参考：https://example.org/guide"

    result = asyncio.run(requirements_graph().ainvoke({"messages": [("human", "查一下公开的门店排班资料")], "description": ""},
                                                     {"configurable": {"llm4om_resources": make_resources(reply)}},
                                                     context=RequirementsContext(search=True)))
    assert not result["failure"] and result["description"] == "门店排班。参考建议待用户确认。"
    sources = [message.artifact for message in result["messages"] if message.type == "tool" and message.name == "web_search"]
    assert sources[0]["results"][0]["title"] == "Reference"
    assert result["usage"]["llm_calls"] == 3 and result["usage"]["solves"] == 0
    assert "search-secret" not in str(result) and "test-key" not in str(result)
