"""LLM providers, saved settings and LangChain chat-model construction."""

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    protocol: str  # LangChain provider integration
    base_url: str  # empty means the user supplies it


PROVIDERS = {provider.id: provider for provider in (
    Provider("openai", "OpenAI", "openai", "https://api.openai.com/v1"),
    Provider("google", "Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai"),
    Provider("kimi", "Kimi", "openai", "https://api.moonshot.cn/v1"),
    Provider("glm", "GLM（智谱）", "openai", "https://open.bigmodel.cn/api/paas/v4"),
    Provider("openrouter", "OpenRouter", "openrouter", "https://openrouter.ai/api/v1"),
    Provider("bailian", "阿里云百炼（北京）", "openai", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    Provider("deepseek", "DeepSeek", "deepseek", "https://api.deepseek.com/v1"),
    Provider("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com"),
    Provider("openai_compatible", "OpenAI 兼容（自定义地址）", "openai", ""),
)}


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    temperature: float | None = 0
    max_tokens: int | None = None
    timeout: float = 300
    max_retries: int = 2
    extra_body: dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return self.base_url or PROVIDERS[self.provider].base_url

    def validate(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"Unknown LLM provider {self.provider!r}.")
        if not self.model.strip():
            raise ValueError("Choose an LLM model.")
        if not self.url:
            raise ValueError("Enter the base URL of the OpenAI-compatible service.")
        if not self.api_key:
            raise ValueError(f"Set the API key for {PROVIDERS[self.provider].label}.")


def chat_model(settings: LLMSettings, *, callbacks: list[BaseCallbackHandler] | None = None,
               metadata: dict[str, Any] | None = None) -> BaseChatModel:
    settings.validate()
    # Streaming lets the run view show each reply as it is written; the reply and its usage stay the same.
    common: dict[str, Any] = {"model": settings.model, "api_key": settings.api_key, "max_retries": settings.max_retries,
                              "callbacks": callbacks, "metadata": metadata, "streaming": True}
    if settings.temperature is not None:
        common["temperature"] = settings.temperature
    protocol = PROVIDERS[settings.provider].protocol
    native = {**common, "base_url": settings.url, "timeout": settings.timeout,
              **({"max_tokens": settings.max_tokens} if settings.max_tokens is not None else {})}
    if protocol == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(**{**native, **settings.extra_body})
    if protocol == "openrouter":
        from langchain_openrouter import ChatOpenRouter
        from openrouter.components import ChatRequestReasoning

        if (reasoning := settings.extra_body.get("reasoning")) is not None:
            ChatRequestReasoning.model_validate(reasoning, extra="forbid")
        return ChatOpenRouter(**{**native, "timeout": int(settings.timeout * 1000), **settings.extra_body})
    openai_options = {"timeout": settings.timeout, "max_tokens": settings.max_tokens,
                      "extra_body": settings.extra_body or None, "stream_usage": True}
    if protocol == "deepseek":
        # ChatDeepSeek keeps reasoning_content across turns, which DeepSeek requires for tool calls in thinking mode.
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(**common, api_base=settings.url, **openai_options)
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(**common, base_url=settings.url, **openai_options)


async def list_models(settings: LLMSettings) -> list[str]:
    """Model IDs from the provider's catalog endpoint; some services do not offer one."""
    if PROVIDERS[settings.provider].protocol == "anthropic":
        from anthropic import AsyncAnthropic

        async with AsyncAnthropic(api_key=settings.api_key, base_url=settings.url, timeout=20) as client:
            return sorted([model.id async for model in client.models.list()])
    from openai import AsyncOpenAI

    async with AsyncOpenAI(api_key=settings.api_key, base_url=settings.url, timeout=20) as client:
        return sorted([model.id async for model in client.models.list()])


@dataclass(frozen=True)
class LLMPreset:
    """A fixed LLM configuration that runs choose by id. `source` is "env" for the LLM4OM_LLM_* preset."""

    id: str
    settings: LLMSettings
    source: str = "saved"

    def public(self) -> dict[str, Any]:
        """The preset without its key: what the browser and run records may see."""
        values = asdict(self.settings)
        del values["api_key"], values["timeout"], values["max_retries"]
        return {"id": self.id, "source": self.source, **values}


ENV_PRESET = "env"


class LLMPresetStore:
    """LLM presets in `<workspace>/.private/llm-presets.json` (mode 600), plus the LLM4OM_LLM_* preset.

    Presets can be added and deleted but never changed, and their keys never leave the server: no route returns a
    key, and a key is only sent to the base URL saved with it. The first preset is the default.
    """

    def __init__(self, workspace: Path) -> None:
        self.path = workspace / ".private" / "llm-presets.json"

    def _saved(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return self._migrate()
        return json.loads(self.path.read_text(encoding="utf-8"))["presets"]

    def _migrate(self) -> list[dict[str, Any]]:
        """v0.38 kept one profile per provider in llm-settings.json; each becomes a preset named after its provider."""
        old = self.path.with_name("llm-settings.json")
        if not old.exists():
            return []
        profiles = json.loads(old.read_text(encoding="utf-8"))["profiles"]
        presets = [{"id": provider, "provider": provider, **values} for provider, values in profiles.items()]
        self._write(presets)
        old.unlink()
        return presets

    def presets(self) -> list[LLMPreset]:
        """The environment preset first, then the saved ones in the order they were added."""
        saved = [LLMPreset(values.pop("id"), LLMSettings(**values)) for values in self._saved()]
        environment = settings_from_env()
        return ([LLMPreset(ENV_PRESET, environment, "env")] if environment else []) + saved

    def get(self, preset: str | None = None) -> LLMSettings:
        """The settings of `preset`, or of the default preset."""
        presets = self.presets()
        if not presets:
            raise ValueError("Add an LLM preset first (Web workbench, or LLM4OM_LLM_* environment variables).")
        if preset is None:
            return presets[0].settings
        for item in presets:
            if item.id == preset:
                return item.settings
        raise ValueError(f"No LLM preset {preset!r}; choose one of {[item.id for item in presets]}.")

    def add(self, settings: LLMSettings) -> LLMPreset:
        """Save `settings` as a new preset; its id comes from the model name."""
        settings.validate()
        saved = self._saved()
        taken = {ENV_PRESET} | {values["id"] for values in saved}
        base = name = re.sub(r"[^a-z0-9._-]+", "-", settings.model.lower()).strip("-.") or "preset"
        number = 2
        while name in taken:
            name, number = f"{base}-{number}", number + 1
        self._write(saved + [{"id": name, **asdict(settings)}])
        return LLMPreset(name, settings)

    def delete(self, preset: str) -> None:
        if preset == ENV_PRESET:
            raise ValueError("This preset comes from the server's LLM4OM_LLM_* variables; remove it there.")
        saved = self._saved()
        if not any(values["id"] == preset for values in saved):
            raise ValueError(f"No saved LLM preset {preset!r}.")
        self._write([values for values in saved if values["id"] != preset])

    def _write(self, presets: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.path, 0o600)
        self.path.write_text(json.dumps({"presets": presets}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def public(self) -> dict[str, Any]:
        return {"presets": [preset.public() for preset in self.presets()]}


def settings_from_env() -> LLMSettings | None:
    """Default settings from LLM4OM_LLM_* variables (a `.env` file in the working directory is read first)."""
    from dotenv import load_dotenv

    load_dotenv()
    model = os.environ.get("LLM4OM_LLM_MODEL", "")
    if not model:
        return None
    return LLMSettings(provider=os.environ.get("LLM4OM_LLM_PROVIDER", "openai_compatible"), model=model,
                       api_key=os.environ.get("LLM4OM_LLM_API_KEY", ""),
                       base_url=os.environ.get("LLM4OM_LLM_BASE_URL", ""),
                       extra_body=json.loads(os.environ.get("LLM4OM_LLM_EXTRA_BODY") or "{}"))
