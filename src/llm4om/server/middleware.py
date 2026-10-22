"""HTTP policies shared by platform routes and the native LangGraph API."""

import json
import re
import time
from collections import defaultdict, deque
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from httpx import HTTPStatusError
from langgraph_sdk import get_client
from starlette.types import ASGIApp, Receive, Scope, Send

from llm4om.progress import NAMESPACE


async def read_json(scope: Scope, receive: Receive) -> tuple[Any, Receive]:
    body = await Request(scope, receive).body()
    original_receive = receive
    pending = True

    async def replay() -> dict[str, Any]:
        nonlocal pending
        if pending:
            pending = False
            return {"type": "http.request", "body": body}
        return await original_receive()

    return json.loads(body), replay


class ThreadCleanup:
    """Stop a thread's writers before deletion and clear its progress before acknowledging the request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        threads: list[str] = []
        if scope["type"] == "http":
            path = scope["path"].rstrip("/")
            if scope["method"] == "DELETE" and (match := re.fullmatch(r"/threads/([^/]+)", path)):
                try:
                    threads = [str(UUID(match[1]))]
                except ValueError:
                    pass  # The native endpoint reports invalid IDs.
            elif scope["method"] == "POST" and path == "/threads/prune":
                try:
                    body, receive = await read_json(scope, receive)
                    if isinstance(body, dict) and body.get("strategy", "delete") == "delete":
                        threads = [str(UUID(thread)) for thread in body.get("thread_ids", [])]
                except (ValueError, TypeError, AttributeError):
                    await JSONResponse({"detail": "Send valid thread IDs."}, status_code=422)(scope, receive, send)
                    return
        if not threads:
            await self.app(scope, receive, send)
            return

        client = get_client(url=None)
        for thread in threads:
            try:
                for status in ("pending", "running"):
                    while runs := await client.runs.list(thread, status=status, limit=100):
                        for run in runs:
                            await client.runs.cancel(thread, run["run_id"], wait=True)
            except HTTPStatusError as error:
                if error.response.status_code != 404:
                    raise

        async def cleaned(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start" and (
                    200 <= message["status"] < 300 or (scope["method"] == "DELETE" and message["status"] == 404)):
                for thread in threads:
                    await client.store.delete_item(NAMESPACE, key=thread)
            await send(message)

        await self.app(scope, receive, cleaned)


class JsonOnlyWrites:
    """Rejects POST bodies that are not JSON on every route, the LangGraph API included.

    A cross-site page cannot send application/json without a CORS preflight, which this server never grants.
    POSTs without a body (such as cancelling a run) pass: they carry nothing a page could forge.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST":
            headers = dict(scope["headers"])
            content_type = headers.get(b"content-type", b"").decode()
            has_body = headers.get(b"content-length", b"0") != b"0" or b"transfer-encoding" in headers
            if (content_type or has_body) and not content_type.startswith("application/json"):
                await JSONResponse({"detail": "Send JSON."}, status_code=415)(scope, receive, send)
                return
        await self.app(scope, receive, send)


RUN_STARTS = re.compile(r"/(threads/[^/]+/)?runs(/stream|/wait|/batch)?/?")


class RunRateLimit:
    """Limits the runs one client address may start per hour; 0 means no limit.

    The address is the connecting peer's, or with `trust_proxy` the last X-Forwarded-For entry, which a reverse
    proxy such as Caddy sets to the address it saw. Trust it only when clients reach the server through the proxy
    alone; otherwise a client can send any address.
    """

    def __init__(self, app: ASGIApp, per_hour: int = 0, trust_proxy: bool = False) -> None:
        self.app, self.per_hour, self.trust_proxy = app, per_hour, trust_proxy
        self.starts: dict[str, deque[float]] = defaultdict(deque)

    def client(self, scope: Scope) -> str:
        forwarded = dict(scope["headers"]).get(b"x-forwarded-for", b"").decode().split(",")[-1].strip()
        if self.trust_proxy and forwarded:
            return forwarded
        return scope["client"][0] if scope.get("client") else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (self.per_hour and scope["type"] == "http" and scope["method"] == "POST"
                and RUN_STARTS.fullmatch(scope["path"])):
            count = 1
            if scope["path"].rstrip("/") == "/runs/batch":
                try:
                    payload, receive = await read_json(scope, receive)
                except ValueError:
                    await JSONResponse({"detail": "Send a JSON array of runs."}, status_code=400)(scope, receive, send)
                    return
                if not isinstance(payload, list):
                    await JSONResponse({"detail": "Send a JSON array of runs."}, status_code=400)(scope, receive, send)
                    return
                count = len(payload)
            now, client = time.monotonic(), self.client(scope)
            starts = self.starts[client]
            while starts and starts[0] <= now - 3600:
                starts.popleft()
            if len(starts) + count > self.per_hour:
                detail = f"This address may start {self.per_hour} runs per hour; {self.per_hour - len(starts)} remaining."
                await JSONResponse({"detail": detail}, status_code=429)(scope, receive, send)
                return
            starts.extend([now] * count)
        await self.app(scope, receive, send)
