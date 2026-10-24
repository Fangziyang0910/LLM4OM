"""Compose native LangChain tools and middleware for the existing conversation modes."""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import BaseTool

from llm4om.llm import LLMSettings
from llm4om.web_search import search_tool

from .calculation import calculation
from .modeling import modeling
from .plans import plans
from .session import Conversation


def assemble_capabilities(session: Conversation, preset: str | None,
                          settings: LLMSettings) -> tuple[list[BaseTool], list[AgentMiddleware]]:
    middleware = [*plans(session), calculation(session)]
    tools = []
    if session.optimization:
        middleware += modeling(session, preset)
        if session.choice.search:
            tools.append(search_tool(settings))
    return tools, middleware
