"""DeepSeek Search as a LangChain tool; credentials stay with their configured server."""

import json
import os
from typing import Annotated, Any

import httpx
from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import AnyHttpUrl, BaseModel, Field

from llm4om.llm import LLMSettings


class SearchResult(BaseModel):
    title: str
    url: AnyHttpUrl
    summary: str = ""
    snippet: str = ""
    date: str | None = None


class SearchResults(BaseModel):
    results: list[SearchResult]


def search_tool(settings: LLMSettings) -> BaseTool:
    """Use a dedicated search credential, or the selected DeepSeek preset at its own address."""
    key = os.environ.get("LLM4OM_SEARCH_API_KEY")
    if key:
        base = os.environ.get("LLM4OM_SEARCH_BASE_URL") or "https://api.deepseek.com/v1"
    elif settings.provider == "deepseek":
        key, base = settings.api_key, settings.url
    else:
        raise ValueError("Configure LLM4OM_SEARCH_API_KEY or select a DeepSeek preset to search the web.")
    base = base.rstrip("/")
    url = base + ("/tools/search" if base.endswith("/v1") else "/v1/tools/search")

    @tool(response_format="content_and_artifact")
    async def web_search(query: Annotated[str, Field(min_length=1, max_length=128)]) -> tuple[str, dict[str, Any]]:
        """Search public web pages for current facts or useful reference material. Cite the returned URLs.

        Search results are references, not the user's confirmed business requirements. Do not send private files.
        """
        artifact: dict[str, Any] = {"query": query, "results": [], "error": None}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers={"Authorization": f"Bearer {key}"},
                                             json={"query": query, "count": 5, "need_content": False})
                response.raise_for_status()
                artifact["results"] = SearchResults.model_validate(response.json()).model_dump(mode="json")["results"]
        except httpx.HTTPStatusError as error:
            artifact["error"] = f"DeepSeek Search returned HTTP {error.response.status_code}."
        except httpx.RequestError:
            artifact["error"] = "Could not reach DeepSeek Search."
        except ValueError:
            artifact["error"] = "DeepSeek Search returned an unreadable result."
        return json.dumps(artifact, ensure_ascii=False), {"type": "search", **artifact}

    return web_search
