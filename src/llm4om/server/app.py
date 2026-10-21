"""Routes the LangGraph server mounts beside its own API: options, LLM settings, examples and the built frontend.

Runs, threads and streaming come from the LangGraph server itself (`/threads`, `/runs`, `/assistants`).
"""

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
from llm4om.llm import PROVIDERS, LLMSettings, SettingsStore, list_models
from llm4om.methods import methods
from llm4om.server import examples

ASSETS = Path(str(files("llm4om.server").joinpath("web_assets")))
PAGES = ("/", "/run/{thread_id}")  # the single-page app; no catch-all or /runs path, which would shadow the LangGraph API


class SettingsBody(BaseModel):
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


def create_app(settings: SettingsStore | None = None) -> FastAPI:
    app = FastAPI(title="LLM4OM")
    app.add_middleware(JsonOnlyWrites)
    store = settings or default_resources().settings

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

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return store.public()

    @app.post("/api/settings")
    def save_settings(body: SettingsBody) -> dict[str, Any]:
        store.save(LLMSettings(**body.model_dump()))
        return store.public()

    @app.delete("/api/settings/{provider}")
    def delete_settings(provider: str) -> dict[str, Any]:
        store.delete(provider)
        return store.public()

    @app.post("/api/models")
    async def models(body: SettingsBody) -> dict[str, Any]:
        settings = store.with_key(LLMSettings(**body.model_dump()))
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
