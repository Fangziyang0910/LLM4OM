"""Failure paths: parsing, cancellation, deadlines and provider requests."""

import asyncio
import json
import subprocess
import sys
import time
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from llm4om.graph import run
from llm4om.llm import LLMSettings, chat_model
from llm4om.runtime import Limits
from tests.conftest import TWO_PART_REPLY, ScriptedChat, tool_call


def test_optimus_json_preserves_urls_escapes_and_nested_values() -> None:
    # A subprocess bounds the old parser's infinite loop.
    script = r'''
from llm4om.methods.optimus.parsing import extract_json_from_end
text = '{"example": 0}\n```json\n{\n// comment\n"url": "https://example.org", "path": "a\\\\b", "nested": {"brace": "}"}}\n```'
assert extract_json_from_end(text) == {"url": "https://example.org", "path": "a\\b", "nested": {"brace": "}"}}
assert extract_json_from_end('{"url":"https://example.org"}') == {"url": "https://example.org"}
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=3)
    assert result.returncode == 0, result.stderr


def test_trival_timeout_stops_the_agent_loop(make_resources: Any) -> None:
    calls = []

    def script(*_: Any) -> AIMessage:
        calls.append(time.monotonic())
        time.sleep(0.06)
        return tool_call("write_semantic_facts", semantic_facts="facts")

    async def check() -> None:
        resources = make_resources(script, Limits(max_llm_calls=8, run_timeout=0.2))
        result = await run("test", method="trival", resources=resources)
        count = len(calls)
        await asyncio.sleep(0.2)
        assert "time limit" in result["failure"] and count > 0
        assert len(calls) == count, "the agent kept starting calls after its run ended"

    asyncio.run(check())


def test_autoformulation_failure_cancels_other_samples(make_resources: Any) -> None:
    started, finished, cancelled = [], [], []

    class SamplingChat(ScriptedChat):
        async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
            index = len(started)
            started.append(index)
            if index == 0:
                await asyncio.sleep(0.01)
                raise RuntimeError("provider failed")
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                cancelled.append(index)
                raise
            finished.append(index)
            return ChatResult(generations=[ChatGeneration(message=AIMessage("unused"))])

    async def check() -> None:
        resources = make_resources(lambda *_: "unused")
        resources.model_factory = lambda settings, **kwargs: SamplingChat(script=None, **kwargs)
        result = await run("test", method="autoformulation", options={"n_used_gpt": 3}, resources=resources)
        await asyncio.sleep(0.15)
        assert "provider failed" in result["failure"]
        assert started == [0, 1, 2] and sorted(cancelled) == [1, 2] and not finished

    asyncio.run(check())


def test_deadline_includes_final_solving(make_resources: Any) -> None:
    class SlowSandbox:
        cancelled = False

        async def solve(self, *args: Any) -> None:
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


@pytest.mark.parametrize("text", ["no JSON", "{", "// comment without a newline"])
def test_optimus_rejects_missing_json(text: str) -> None:
    from llm4om.methods.optimus.parsing import extract_json_from_end

    with pytest.raises(ValueError):
        extract_json_from_end(text)


def test_optimus_extracts_the_last_complete_array() -> None:
    from llm4om.methods.optimus.parsing import extract_json_from_end

    assert extract_json_from_end('Example: [0]. Answer: ["a[b]", [1, 2]]', list) == ["a[b]", [1, 2]]


def test_openrouter_rejects_reasoning_fields_the_sdk_would_discard() -> None:
    with pytest.raises(ValueError, match="enabled"):
        chat_model(LLMSettings("openrouter", "anthropic/test", api_key="dummy",
                               extra_body={"reasoning": {"enabled": True}}))


def test_cli_reports_failed_solve_without_a_status(capsys: Any) -> None:
    from llm4om.cli import _print_step

    _print_step({"type": "solve", "title": "final solve", "running": False, "failed": True})
    assert "final solve" in capsys.readouterr().err

@pytest.mark.parametrize('value', ['a}b', 'a{b', 'escaped\\"quote', {'nested': '{value}'}])
def test_autoformulation_dictionary_values_keep_braces_and_quotes(value: Any) -> None:
    from llm4om.methods.autoformulation.upstream.utils_prompt import extract_dict_from_string

    expected = {'label': value}
    _, parsed = extract_dict_from_string(f"formalization_dict['parameters'] = {expected!r}", 'parameters')
    assert parsed == expected


def test_a_solver_error_is_not_successful_execution() -> None:
    from llm4om.sandbox import SolveResult

    assert not SolveResult('error').executed
