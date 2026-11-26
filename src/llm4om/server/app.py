"""Routes the LangGraph server mounts beside its own API: options, LLM presets, examples and the built frontend.

Runs, threads and streaming come from the LangGraph server itself (`/threads`, `/runs`, `/assistants`).
"""

import asyncio
import os
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.staticfiles import StaticFiles

from llm4om.budget import TokenBudget
from llm4om.graph import default_resources
from llm4om.languages import LANGUAGES
from llm4om.llm import PROVIDERS, LLMSettings, list_models
from llm4om.llm_presets import LLMPresetStore
from llm4om.methods import methods
from llm4om.runtime import LimitExceeded
from llm4om.server import examples
from llm4om.server.assets import WorkbenchAssets
from llm4om.server.middleware import JsonOnlyWrites, RunRateLimit, ThreadCleanup
from llm4om.server.translations import ExampleTranslations, TranslationError

ASSETS = Path(str(files("llm4om.server").joinpath("web_assets")))
PAGES = ("/", "/model", "/agent", "/agent/{thread_id}", "/run/{thread_id}", "/compare/{group}", "/chat/{thread_id}", "/discussion/{thread_id}")


class PresetBody(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    name: str = ""
    provider: str
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float | None = 0
    max_tokens: int | None = None
    extra_body: dict[str, Any] = {}


class TranslationBody(BaseModel):
    case_id: str
    locale: Literal["zh", "en"] = "zh"


class ReadingTranslationBody(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    locale: Literal["zh", "en"] = "zh"


def create_app(presets: LLMPresetStore | None = None, budget: TokenBudget | None = None, runs_per_hour: int | None = None,
               trust_proxy: bool | None = None) -> FastAPI:
    """The platform routes. Settings left out come from the service resources and LLM4OM_RUNS_PER_HOUR and
    LLM4OM_TRUST_PROXY."""
    app = FastAPI(title="通用智能优化求解器", description="求解各种复杂优化问题的通用求解器")
    app.add_middleware(ThreadCleanup)
    app.add_middleware(RunRateLimit, per_hour=int(os.environ.get("LLM4OM_RUNS_PER_HOUR") or 0)
                       if runs_per_hour is None else runs_per_hour,
                       trust_proxy=os.environ.get("LLM4OM_TRUST_PROXY", "").strip().lower() in ("1", "true", "yes", "on")
                       if trust_proxy is None else trust_proxy)
    app.add_middleware(JsonOnlyWrites)
    store = presets or default_resources().presets
    budget = budget or (default_resources().budget if presets is None else None)
    translations = ExampleTranslations(store, budget)

    @app.exception_handler(ValueError)
    async def bad_input(_: Request, error: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    # Installed graphs and their public configuration are fixed when this service starts.
    options_body = JSONResponse({
        "methods": [{"id": m.id, "name": m.name, "description": m.description, "source": m.source,
                     "linear_only": m.linear_only, "builtin_solver": m.builtin_solver,
                     "languages": sorted(m.languages) if m.languages is not None else None}
                    for m in methods().values()],
        "languages": [{"id": item.id, "name": item.name, "solver": "AUTO"} for item in LANGUAGES.values()],
        "providers": [asdict(provider) for provider in PROVIDERS.values()],
        "datasets": examples.datasets(),
        "search_configured": bool(os.environ.get("LLM4OM_SEARCH_API_KEY")),
    }).body

    @app.get("/api/options", response_model=dict[str, Any])
    async def options() -> Response:
        return Response(options_body, media_type="application/json")

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
        settings.validate(require_model=False)
        try:
            return {"models": await list_models(settings)}
        except Exception as error:  # report any catalog failure; the user can still type a model ID
            detail = settings.redact(f"{type(error).__name__}: {error}")
            raise HTTPException(502, f"Could not read the model list: {detail}") from error

    @app.get("/api/datasets")
    def search_datasets(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                        q: str = Query("", max_length=200)) -> dict[str, Any]:
        return examples.cases(None, offset, limit, q)

    @app.get("/api/datasets/{dataset_id}")
    def dataset(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                q: str = Query("", max_length=200)) -> dict[str, Any]:
        try:
            return examples.cases(dataset_id, offset, limit, q=q)
        except KeyError:
            raise HTTPException(404, "This dataset does not exist.") from None

    async def reading_translation(text: str, locale: Literal["zh", "en"]) -> dict[str, Any]:
        try:
            return await translations.translate(text, locale)
        except LimitExceeded as error:
            raise HTTPException(429, str(error)) from None
        except TranslationError as error:
            raise HTTPException(502, str(error)) from None
        except OSError:
            raise HTTPException(503, "The translation cache is unavailable. Please retry.") from None

    @app.post("/api/translations")
    async def translate_reading(body: ReadingTranslationBody) -> dict[str, Any]:
        if not body.text.strip():
            raise HTTPException(400, "Provide text to translate.")
        return await reading_translation(body.text, body.locale)

    @app.post("/api/datasets/{dataset_id}/translation")
    async def translate_example(dataset_id: str, body: TranslationBody) -> dict[str, Any]:
        try:
            original = await asyncio.to_thread(examples.case, dataset_id, body.case_id)
        except KeyError:
            raise HTTPException(404, "This example does not exist.") from None
        return {"id": body.case_id, **await reading_translation(original["description"], body.locale)}

    if (ASSETS / "index.html").is_file():
        app.mount("/assets", WorkbenchAssets(ASSETS / "assets"), name="assets")
        shell = StaticFiles(directory=ASSETS)

        async def workbench(request: Request) -> Response:
            response = await shell.get_response("index.html", request.scope)
            response.headers["cache-control"] = "no-cache"
            return response

        for page in PAGES:
            app.add_api_route(page, workbench, methods=["GET", "HEAD"], include_in_schema=False)

    return app


app = create_app()
