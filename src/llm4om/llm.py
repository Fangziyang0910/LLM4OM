"""LLM settings, providers and LangChain chat-model construction."""

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr


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
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    temperature: float | None = 0
    max_tokens: int | None = None
    timeout: float = 300
    max_retries: int = 2
    extra_body: dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return self.base_url.strip() or PROVIDERS[self.provider].base_url

    def public(self) -> dict[str, Any]:
        """Reproducible settings without the credential; used in the run's configuration snapshot."""
        values = asdict(self)
        del values["api_key"]
        return {**values, "base_url": self.url}

    def redact(self, text: str) -> str:
        """Remove this preset's credential from any recorded error or traceback text."""
        for secret in dict.fromkeys((self.api_key, self.api_key.strip())):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text

    def with_thinking(self, enabled: bool | None) -> "LLMSettings":
        """Apply a conversation's DeepSeek switch without editing its shared preset."""
        if enabled is None:
            return self
        if self.provider != "deepseek":
            raise ValueError("The conversation thinking switch requires a DeepSeek preset.")
        extra = {**self.extra_body, "thinking": {"type": "enabled" if enabled else "disabled"}}
        if not enabled:
            extra.pop("reasoning_effort", None)
        return replace(self, extra_body=extra)

    def validate(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"Unknown LLM provider {self.provider!r}.")
        if not self.model.strip():
            raise ValueError("Choose an LLM model.")
        if not self.url:
            raise ValueError("Enter the base URL of the OpenAI-compatible service.")
        if not self.api_key.strip():
            raise ValueError(f"Set the API key for {PROVIDERS[self.provider].label}.")
        if self.temperature is not None and not math.isfinite(self.temperature):
            raise ValueError("Temperature must be a finite number.")
        if not isinstance(self.extra_body, dict):
            raise ValueError("Extra parameters must be a JSON object.")
        reserved = {
            "model", "model_name", "api_key", "base_url", "api_base", "temperature", "max_tokens",
            "max_tokens_to_sample", "timeout", "request_timeout", "default_request_timeout", "max_retries",
            "callbacks", "callback_manager", "metadata", "streaming", "stream", "stream_usage",
            "stream_options", "disable_streaming", "default_headers",
            "anthropic_api_url", "anthropic_api_key", "openrouter_api_key", "openrouter_api_base",
            "openai_api_key", "openai_api_base", "client", "async_client", "http_client", "http_async_client",
        }
        if duplicates := self.extra_body.keys() & reserved:
            raise ValueError(f"Extra parameters cannot replace configured fields: {', '.join(sorted(duplicates))}.")


def chat_model(settings: LLMSettings, *, callbacks: list[BaseCallbackHandler] | None = None,
               metadata: dict[str, Any] | None = None) -> BaseChatModel:
    settings.validate()
    # Streaming lets the run view show each reply as it is written; the reply and its usage stay the same.
    common: dict[str, Any] = {"model": settings.model, "api_key": SecretStr(settings.api_key),
                              "max_retries": settings.max_retries, "callbacks": callbacks,
                              "metadata": metadata, "streaming": True}
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
        # The native client exposes DeepSeek reasoning_content and tool/structured output support.
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(**common, api_base=settings.url, **openai_options)
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(**common, base_url=settings.url, **openai_options)


async def list_models(settings: LLMSettings) -> list[str]:
    """Model IDs from the provider's catalog endpoint; some services do not offer one."""
    if settings.provider not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider {settings.provider!r}.")
    if PROVIDERS[settings.provider].protocol == "anthropic":
        from anthropic import AsyncAnthropic

        async with AsyncAnthropic(api_key=settings.api_key, base_url=settings.url, timeout=20) as client:
            return sorted([model.id async for model in client.models.list()])
    from openai import AsyncOpenAI

    async with AsyncOpenAI(api_key=settings.api_key, base_url=settings.url, timeout=20) as client:
        return sorted([model.id async for model in client.models.list()])
