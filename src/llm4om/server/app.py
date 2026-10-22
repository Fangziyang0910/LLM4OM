"""Routes the LangGraph server mounts beside its own API: options, LLM presets, examples and the built frontend.

Runs, threads and streaming come from the LangGraph server itself (`/threads`, `/runs`, `/assistants`).
"""

import os
import re
import time
from collections import defaultdict, deque
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from llm4om.graph import default_resources
from llm4om.languages import LANGUAGES
from llm4om.llm import PROVIDERS, LLMPresetStore, LLMSettings, list_models
from llm4om.methods import methods
from llm4om.runtime import TokenBudget
from llm4om.server import examples

ASSETS = Path(str(files("llm4om.server").joinpath("web_assets")))
PAGES = ("/", "/run/{thread_id}", "/compare/{group}")  # the single-page app; no catch-all or /runs path, which would shadow the LangGraph API


class PresetBody(BaseModel):
    provider: str
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float | None = 0
    max_tokens: int | None = None
    extra_body: dict[str, Any] = {}


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
            now, client = time.monotonic(), self.client(scope)
            starts = self.starts[client]
            while starts and starts[0] <= now - 3600:
                starts.popleft()
            if len(starts) >= self.per_hour:
                wait = max(1, round((starts[0] + 3600 - now) / 60))
                detail = f"This address started {self.per_hour} runs in the last hour. Try again in {wait} min."
                await JSONResponse({"detail": detail}, status_code=429)(scope, receive, send)
                return
            starts.append(now)
        await self.app(scope, receive, send)


def create_app(presets: LLMPresetStore | None = None, budget: TokenBudget | None = None, runs_per_hour: int | None = None,
               trust_proxy: bool | None = None) -> FastAPI:
    """The platform routes. Settings left out come from the service resources and LLM4OM_RUNS_PER_HOUR and
    LLM4OM_TRUST_PROXY."""
    app = FastAPI(title="LLM4OM")
    app.add_middleware(JsonOnlyWrites)
    app.add_middleware(RunRateLimit, per_hour=int(os.environ.get("LLM4OM_RUNS_PER_HOUR") or 0)
                       if runs_per_hour is None else runs_per_hour,
                       trust_proxy=os.environ.get("LLM4OM_TRUST_PROXY", "") not in ("", "0", "false")
                       if trust_proxy is None else trust_proxy)
    store = presets or default_resources().presets
    budget = budget or (default_resources().budget if presets is None else None)

    @app.exception_handler(ValueError)
    async def bad_input(_: Request, error: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.get("/api/options")
    def options() -> dict[str, Any]:
        return {
            "methods": [{"id": m.id, "name": m.name, "description": m.description, "source": m.source,
                         "languages": sorted(m.languages) if m.languages is not None else None}
                        for m in methods().values()],
            "languages": [{"id": item.id, "name": item.name, "solver": item.solver} for item in LANGUAGES.values()],
            "providers": [asdict(provider) for provider in PROVIDERS.values()],
            "datasets": examples.datasets(),
        }

    def public() -> dict[str, Any]:
        """The presets without keys, with the tokens each used today and the daily budget (0: none)."""
        used = budget.used() if budget else {}
        return {"presets": [{**preset, "tokens_today": used.get(preset["id"], 0)} for preset in store.public()["presets"]],
                "daily_tokens": budget.daily_limit if budget else 0}

    # Presets are added and deleted, never changed or read back with their keys.
    @app.get("/api/presets")
    def get_presets() -> dict[str, Any]:
        return public()

    @app.post("/api/presets")
    def add_preset(body: PresetBody) -> dict[str, Any]:
        store.add(LLMSettings(**body.model_dump()))
        return public()

    @app.delete("/api/presets/{preset}")
    def delete_preset(preset: str) -> dict[str, Any]:
        store.delete(preset)
        return public()

    @app.post("/api/models")
    async def models(body: PresetBody) -> dict[str, Any]:
        """The provider's model list, read with the key in the request; saved keys are never used here."""
        settings = LLMSettings(**body.model_dump())
        if not settings.api_key:
            raise ValueError("Enter the API key to read the model list.")
        try:
            return {"models": await list_models(settings)}
        except Exception as error:  # report any catalog failure; the user can still type a model ID
            raise HTTPException(502, f"Could not read the model list: {type(error).__name__}: {error}") from error

    @app.get("/api/datasets/{dataset_id}")
    def dataset(dataset_id: str, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        try:
            return examples.cases(dataset_id, offset, min(limit, 100))
        except KeyError:
            raise HTTPException(404, "This dataset does not exist.") from None

    if (ASSETS / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=ASSETS / "assets"), name="assets")
        for page in PAGES:
            app.add_api_route(page, lambda: FileResponse(ASSETS / "index.html"), include_in_schema=False)

    return app


app = create_app()
