"""Chat models for each provider protocol receive the saved settings."""

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from llm4om.llm import LLMSettings, chat_model


def test_anthropic_receives_extra_parameters() -> None:
    thinking = {"type": "enabled", "budget_tokens": 1024}
    model = chat_model(LLMSettings("anthropic", "claude-sonnet-4-5", api_key="dummy", temperature=None,
                                   max_tokens=2048, extra_body={"thinking": thinking}))
    payload = model._get_request_payload("test")
    assert payload["thinking"] == thinking and payload["max_tokens"] == 2048


def test_openrouter_preserves_reasoning_in_streamed_tool_conversations() -> None:
    requests = []
    details = [{"type": "reasoning.text", "text": "test thought", "index": 0, "format": "unknown"}]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        delta = {"role": "assistant", "content": "done"}
        if len(requests) == 1:
            delta.update(content="", reasoning="test thought", reasoning_details=details,
                         tool_calls=[{"index": 0, "id": "call1", "type": "function",
                                      "function": {"name": "answer", "arguments": "{}"}}])
        base = {"id": "test", "model": "anthropic/test", "object": "chat.completion.chunk", "created": 1}
        chunks = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                  {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                  {**base, "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}]
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    async def check() -> None:
        model = chat_model(LLMSettings("openrouter", "anthropic/test", api_key="dummy", max_retries=0,
                                       extra_body={"reasoning": {"effort": "high"}}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model.client.sdk_configuration.async_client = client
            model.client.sdk_configuration.async_client_supplied = True
            reply = await model.ainvoke([HumanMessage("test")])
            await model.ainvoke([HumanMessage("test"), reply, ToolMessage("ok", tool_call_id="call1")])
        assert model.request_timeout == 300_000  # OpenRouter uses milliseconds.
        assert requests[0]["reasoning"] == {"effort": "high"}
        assert requests[1]["messages"][1]["reasoning_details"] == details
        assert requests[1]["messages"][1]["reasoning"] == "test thought"
        assert reply.usage_metadata["total_tokens"] == 15

    asyncio.run(check())


def test_openrouter_rejects_reasoning_fields_the_sdk_would_discard() -> None:
    with pytest.raises(ValueError, match="enabled"):
        chat_model(LLMSettings("openrouter", "anthropic/test", api_key="dummy",
                               extra_body={"reasoning": {"enabled": True}}))
