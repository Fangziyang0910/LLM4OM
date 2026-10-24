"""A LangChain model that requests an answer from the running coding agent, never from an LLM API."""

import json
from typing import Any, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.func import task
from langgraph.runtime import get_runtime
from langgraph.types import interrupt


@task
async def request_answer(request: dict[str, Any]) -> dict[str, Any]:
    records = get_runtime().context.records
    id, cached = records.begin("llm", request)
    if cached is not None:
        return cached
    reply = interrupt(request)
    records.complete(id, reply)
    calls = [f"{call['name']}({json.dumps(call['args'], ensure_ascii=False)})" for call in reply.get("tool_calls", [])]
    records.recorder.step("llm", request["role"], "\n\n".join([reply.get("content", ""), *calls]).strip(),
                          id=id, running=False)
    return reply


class HostChatModel(BaseChatModel):
    role: str

    @property
    def _llm_type(self) -> str:
        return "llm4om-host"

    def _generate(self, messages: list[BaseMessage], **kwargs: Any) -> ChatResult:
        raise RuntimeError("Host modeling uses async LangGraph execution.")

    async def _agenerate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                        **kwargs: Any) -> ChatResult:
        tools = kwargs.pop("tools", [])
        request = {"role": self.role, "messages": convert_to_openai_messages(messages), "tools": tools,
                   "options": {**kwargs, **({"stop": stop} if stop else {})}}
        reply = await request_answer(request)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(**reply))])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)


def validate_responses(pending: list[dict[str, Any]], responses: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(responses, dict) or set(responses) != {item["id"] for item in pending}:
        raise ValueError("Supply one response for every pending request ID, with no extra IDs.")
    validated = {}
    for request in pending:
        id = request["id"]
        value = responses[id]
        if not isinstance(value, dict) or set(value) - {"content", "tool_calls"}:
            raise ValueError(f"Response {id} must contain content and/or tool_calls.")
        if not isinstance(value.get("content", ""), str) or not isinstance(value.get("tool_calls", []), list):
            raise ValueError(f"Response {id} needs string content and a tool_calls array.")
        try:
            calls = [{**call, "id": call.get("id") or f"call_{id}_{index}"}
                     for index, call in enumerate(value.get("tool_calls", []))]
            message = AIMessage(content=value.get("content", ""), tool_calls=calls, id=f"host_{id}")
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"Invalid response {id}: {error}") from error
        choice = request["options"].get("tool_choice")
        if choice in ("required", "any", True) and not message.tool_calls:
            raise ValueError(f"Response {id} must call one of the supplied tools.")
        if not message.content.strip() and not message.tool_calls:
            raise ValueError(f"Response {id} is empty.")
        validated[id] = {"content": message.content, "tool_calls": message.tool_calls, "id": message.id}
    return validated
