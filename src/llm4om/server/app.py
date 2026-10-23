"""Routes the LangGraph server mounts beside its own API: options, LLM presets, examples and the built frontend.

Runs, threads and streaming come from the LangGraph server itself (`/threads`, `/runs`, `/assistants`).
"""

import os
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from llm4om.budget import TokenBudget
from llm4om.graph import default_resources
from llm4om.languages import LANGUAGES
from llm4om.llm import PROVIDERS, LLMSettings, list_models
from llm4om.llm_presets import LLMPresetStore
from llm4om.methods import methods
from llm4om.server import examples
from llm4om.server.middleware import JsonOnlyWrites, RunRateLimit, ThreadCleanup

ASSETS = Path(str(files("llm4om.server").joinpath("web_assets")))
PAGES = ("/", "/run/{thread_id}", "/compare/{group}", "/chat/{thread_id}")  # no catch-all or /runs path, which would shadow the LangGraph API


class PresetBody(BaseModel):
    name: str = ""
    provider: str
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float | None = 0
    max_tokens: int | None = None
    extra_body: dict[str, Any] = {}


def create_app(presets: LLMPresetStore | None = None, budget: TokenBudget | None = None, runs_per_hour: int | None = None,
               trust_proxy: bool | None = None) -> FastAPI:
    """The platform routes. Settings left out come from the service resources and LLM4OM_RUNS_PER_HOUR and
    LLM4OM_TRUST_PROXY."""
    app = FastAPI(title="LLM4OM")
    app.add_middleware(ThreadCleanup)
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
                         "linear_only": m.linear_only, "languages": sorted(m.languages) if m.languages is not None else None}
                        for m in methods().values()],
            "languages": [{"id": item.id, "name": item.name, "solver": "AUTO"}
                          for item in LANGUAGES.values()],
            "providers": [asdict(provider) for provider in PROVIDERS.values()],
            "datasets": examples.datasets(),
            "search_configured": bool(os.environ.get("LLM4OM_SEARCH_API_KEY")),
        }

    @app.get("/api/backends")
    async def backends() -> dict[str, Any]:
        try:
            return await default_resources().sandbox.catalog()
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

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
        store.add(LLMSettings(**body.model_dump(exclude={"name"})), name=body.name)
        return public()

    @app.delete("/api/presets/{preset}")
    def delete_preset(preset: str) -> dict[str, Any]:
        store.delete(preset)
        return public()

    @app.post("/api/models")
    async def models(body: PresetBody) -> dict[str, Any]:
        """The provider's model list, read with the key in the request; saved keys are never used here."""
        settings = LLMSettings(**body.model_dump(exclude={"name"}))
        if settings.provider not in PROVIDERS:
            raise ValueError(f"Unknown LLM provider {settings.provider!r}.")
        if not settings.url:
            raise ValueError("Enter the base URL of the OpenAI-compatible service.")
        if not settings.api_key:
            raise ValueError("Enter the API key to read the model list.")
        try:
            return {"models": await list_models(settings)}
        except Exception as error:  # report any catalog failure; the user can still type a model ID
            raise HTTPException(502, f"Could not read the model list: {type(error).__name__}: {error}") from error

    @app.get("/api/datasets/{dataset_id}")
    def dataset(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
        try:
            return examples.cases(dataset_id, offset, limit)
        except KeyError:
            raise HTTPException(404, "This dataset does not exist.") from None

    if (ASSETS / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=ASSETS / "assets"), name="assets")
        for page in PAGES:
            app.add_api_route(page, lambda: FileResponse(ASSETS / "index.html"), include_in_schema=False)

    return app


app = create_app()
