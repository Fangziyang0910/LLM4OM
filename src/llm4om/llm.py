"""LLM providers, saved settings and LangChain chat-model construction."""

import json
import os
from dataclasses import asdict, dataclass, field, replace
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

    def public(self) -> dict[str, Any]:
        """Settings without the key, safe to store in run records and send to the browser."""
        values = asdict(self)
        key = values.pop("api_key")
        values["api_key_preview"] = (key[:3] + "…" + key[-4:]) if len(key) > 8 else ("已设置" if key else "")
        return values

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


class SettingsStore:
    """Per-provider settings in `<workspace>/.private/llm-settings.json` (mode 600), plus the selected provider."""

    def __init__(self, workspace: Path) -> None:
        self.path = workspace / ".private" / "llm-settings.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"selected": None, "profiles": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _profiles(self) -> tuple[str | None, dict[str, LLMSettings]]:
        """The selected provider and every profile: the saved ones, plus the LLM4OM_LLM_* settings for their
        provider when nothing is saved for it. The environment profile is selected when nothing is saved."""
        saved = self._read()
        profiles = {provider: LLMSettings(provider=provider, **values) for provider, values in saved["profiles"].items()}
        selected = saved["selected"]
        if (environment := settings_from_env()) is not None:
            profiles.setdefault(environment.provider, environment)
            selected = selected or environment.provider
        return selected, profiles

    def load(self, provider: str | None = None) -> LLMSettings | None:
        """The profile of `provider`, or of the selected provider."""
        selected, profiles = self._profiles()
        return profiles.get(provider or selected or "")

    def resolve(self, provider: str | None = None, model: str | None = None) -> LLMSettings:
        """The settings a run uses: the provider's profile (default: the selected one), with `model` when it names one."""
        return resolve(self.load(provider), model)

    def with_key(self, settings: LLMSettings) -> LLMSettings:
        """`settings` with the known key of its provider when its own key is empty: an empty key field keeps the key."""
        if settings.api_key or (known := self.load(settings.provider)) is None:
            return settings
        return replace(settings, api_key=known.api_key)

    def save(self, settings: LLMSettings) -> None:
        settings = self.with_key(settings)
        settings.validate()
        saved = self._read()
        values = asdict(settings)
        del values["provider"]
        saved["profiles"][settings.provider] = values
        saved["selected"] = settings.provider
        self._write(saved)

    def _write(self, saved: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.path, 0o600)
        self.path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def delete(self, provider: str) -> None:
        """Forget the saved profile of `provider`; the next saved one becomes selected."""
        saved = self._read()
        if provider not in saved["profiles"]:
            raise ValueError("Only saved settings can be deleted; settings from LLM4OM_LLM_* stay in the environment.")
        del saved["profiles"][provider]
        if saved["selected"] == provider:
            saved["selected"] = next(iter(saved["profiles"]), None)
        self._write(saved)

    def public(self) -> dict[str, Any]:
        """The selected provider and every profile, without keys; `saved` is false for the environment profile."""
        selected, profiles = self._profiles()
        saved = self._read()["profiles"]
        return {"selected": selected, "profiles": {provider: {**settings.public(), "saved": provider in saved}
                                                   for provider, settings in profiles.items()}}


def resolve(settings: LLMSettings | None, model: str | None = None) -> LLMSettings:
    """Valid settings for a run: `settings` with `model` when it names one."""
    if settings is None:
        raise ValueError("Configure an LLM first (Web settings, or LLM4OM_LLM_* environment variables).")
    settings = replace(settings, model=model) if model else settings
    settings.validate()
    return settings


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
