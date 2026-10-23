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


@pytest.mark.parametrize("field", ["model", "api_key", "callbacks", "temperature"])
def test_extra_parameters_cannot_override_recorded_settings_or_tracking(field: str) -> None:
    with pytest.raises(ValueError, match="Extra parameters cannot replace"):
        chat_model(LLMSettings("anthropic", "recorded-model", api_key="dummy", extra_body={field: "override"}))


def test_provider_routing_remains_a_valid_extra_request_parameter() -> None:
    routing = {"order": ["provider-a"]}
    model = chat_model(LLMSettings("openai_compatible", "model", api_key="dummy", base_url="http://localhost:9/v1",
                                   extra_body={"provider": routing}))
    assert model._get_request_payload("test")["extra_body"] == {"provider": routing}


def test_deepseek_uses_the_native_client_and_keeps_tool_reasoning() -> None:
    from langchain_deepseek import ChatDeepSeek
    from openai.types.chat import ChatCompletion

    settings = LLMSettings("deepseek", "deepseek-flash", api_key="dummy", base_url="http://localhost:9/v1",
                           extra_body={"thinking": {"type": "disabled"}})
    model = chat_model(settings)
    assert isinstance(model, ChatDeepSeek)
    reply = model._create_chat_result(ChatCompletion.model_validate({
        "id": "test", "created": 1, "model": "deepseek-flash", "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "",
        "reasoning_content": "check the constraints", "tool_calls": [{"id": "call1", "type": "function",
        "function": {"name": "answer", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}))
    message = reply.generations[0].message
    payload = model._get_request_payload([HumanMessage("test"), message, ToolMessage("ok", tool_call_id="call1")])
    assert payload["model"] == "deepseek-flash"
    assert message.additional_kwargs["reasoning_content"] == "check the constraints"
    assert message.tool_calls[0]["name"] == "answer"
    assert payload["extra_body"] == settings.extra_body


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
