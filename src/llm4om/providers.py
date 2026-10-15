"""Text Provider adapters, credentials and owned HTTP transport."""

import asyncio
import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import signal
import sys
import time
from copy import deepcopy
from email.message import Message
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

import jsonschema

from llm4om.contracts import RunError, parse_json
from llm4om.gateway import Gateway as Gateway, run_gateway


class TextProvider(Protocol):
    plugin_id: str
    model: str
    identity: str
    max_output_tokens: int
    max_retries: int
    timeout_s: float

    def prepare(self) -> None: ...

    def complete(self, messages: list[dict[str, Any]], timeout: float) -> dict[str, Any]: ...

    async def acomplete(self, messages: list[dict[str, Any]], timeout: float) -> dict[str, Any]: ...


def credential_environment(path: Path | None, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Read literal KEY=value lines; never execute or interpolate .env content."""
    values: dict[str, str] = {}
    if path is not None and path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)", line)
                if match is None:
                    raise ValueError("Invalid assignment.")
                key, value = match.groups()
                if value.startswith(('"', "'")):
                    if len(value) < 2 or value[-1] != value[0]:
                        raise ValueError("Invalid quote.")
                    value = value[1:-1]
                values[key] = value
        except (OSError, UnicodeError, ValueError) as error:
            raise RunError("invalid_credentials_file", "admission", "Cannot read literal credential assignments.") from error
    values.update(os.environ if environment is None else environment)
    return values


def _credential_value(config: dict[str, Any], environment: Mapping[str, str]) -> str:
    credential = environment.get(config["credential_env"])
    if not credential or any(ord(character) < 32 or ord(character) > 126 for character in credential):
        raise RunError("auth_error", "admission", "Provider requires a valid credential environment variable.")
    return credential


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _connection_code(error: Exception) -> str:
    reason = error.reason if isinstance(error, URLError) else error
    return "provider_timeout" if isinstance(reason, TimeoutError) else "provider_connection_error"


_CONNECTION_DIAGNOSTICS = frozenset({'tls_certificate', 'tls_interrupted', 'tls_error', 'dns_error',
    'connection_refused', 'connection_reset', 'timeout', 'connection_error'})


def _connection_diagnostic(error: Exception) -> str:
    reason = error.reason if isinstance(error, URLError) else error
    for classes, diagnostic in [
        ((ssl.SSLCertVerificationError,), 'tls_certificate'),
        ((ssl.SSLEOFError, ssl.SSLZeroReturnError), 'tls_interrupted'),
        ((ssl.SSLError,), 'tls_error'),
        ((socket.gaierror,), 'dns_error'),
        ((ConnectionRefusedError,), 'connection_refused'),
        ((ConnectionResetError,), 'connection_reset'),
        ((TimeoutError,), 'timeout'),
    ]:
        if isinstance(reason, classes):
            return diagnostic
    return 'connection_error'


def _reply_usage(value: dict[str, Any]) -> dict[str, Any]:
    usage = value.get("usage") or {}
    return {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")}


def _contains_credential(value: Any, credential: str) -> bool:
    if isinstance(value, str):
        return credential in value
    if isinstance(value, dict):
        return any(_contains_credential(key, credential) or _contains_credential(item, credential)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_credential(item, credential) for item in value)
    return False


def _validate_reply(value: dict[str, Any]) -> None:
    text = {"type": ["string", "null"]}
    usage = {name: {"type": ["integer", "null"], "minimum": 0} for name in
             ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens")}
    fields = {"text": {"type": "string"}, "response_id": text, "model": text, "finish_reason": text,
              "usage": {"type": "object", "properties": usage, "required": list(usage), "additionalProperties": False}}
    jsonschema.Draft202012Validator({"type": "object", "properties": {**fields, "stop_reason": text},
        "required": list(fields), "additionalProperties": False}).validate(value)
    json.dumps(value, allow_nan=False)


class HTTPTextProvider:
    plugin_id: str
    endpoint_path: str
    request_id_header: str
    connectivity_profile: str | None = None

    def __init__(self, config: dict[str, Any], model: str, credential: str | Callable[[], str]) -> None:
        self.config = deepcopy(config)
        self.model = model
        self.identity = config["base_url"].rstrip("/") + self.endpoint_path
        self.max_output_tokens = config.get("max_output_tokens", 1024)
        self.max_retries = config.get("max_retries", 2)
        self.timeout_s = float(config.get("timeout_s", 30))
        self._credential = credential if isinstance(credential, str) else ""
        self._load_credential = credential if callable(credential) else None

    def gateway(self, public: dict[str, Any], problem_sha256: str, store: Any,
                ledger: dict[str, Any], budget: Mapping[str, Any], config_dir: Path, *, deadline: float,
                role_providers: Mapping[str, "HTTPTextProvider"] | None = None) -> "Gateway":
        return run_gateway(self, store, budget, deadline=deadline, role_providers=role_providers)


    def prepare(self) -> None:
        """Resolve local credentials once, before durable admission or direct transport."""
        if self._load_credential is not None:
            self._credential = self._load_credential()
            self._load_credential = None

    def _transport_input(self, messages: list[dict[str, Any]], timeout: float,
                         *, operation: str = "complete") -> bytes:
        self.prepare()
        return json.dumps({"provider": self.plugin_id, "endpoint": self.identity, "model": self.model,
                           "config": self.config,
                           "max_output_tokens": self.max_output_tokens, "credential": self._credential,
                           "messages": messages, "timeout": timeout, "operation": operation}, allow_nan=False).encode()

    def complete(self, messages: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
        return self._transport_call(messages, timeout)

    def check_connectivity(self, timeout: float) -> dict[str, Any]:
        """Read protocol metadata without submitting a generation request."""
        return self._transport_call([], timeout, operation="models_get")

    def _transport_call(self, messages: list[dict[str, Any]], timeout: float,
                        *, operation: str = "complete") -> dict[str, Any]:
        if timeout <= 0:
            raise TimeoutError("Provider request deadline expired.")
        started = time.monotonic()
        payload = self._transport_input(messages, timeout, operation=operation)
        with subprocess.Popen(_TRANSPORT_COMMAND, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, start_new_session=True) as process:
            try:
                raw, _ = process.communicate(payload,
                                             timeout=max(0, timeout - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise TimeoutError("Provider request deadline expired.") from None
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
        return _transport_result(raw)

    async def acomplete(self, messages: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
        if timeout <= 0:
            raise TimeoutError("Provider request deadline expired.")
        started = time.monotonic()
        payload = self._transport_input(messages, timeout)
        process = await asyncio.create_subprocess_exec(
            *_TRANSPORT_COMMAND, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        pending = asyncio.create_task(process.communicate(payload))
        try:
            raw, _ = await asyncio.wait_for(asyncio.shield(pending),
                                            max(0, timeout - (time.monotonic() - started)))
            return _transport_result(raw)
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                await pending
            finally:
                await process.wait()

    def _request(self, messages: list[dict[str, Any]]) -> Request:
        raise NotImplementedError

    def _models_request(self) -> Request | None:
        return None

    def _http_connectivity(self, timeout: float) -> dict[str, Any]:
        request = self._models_request()
        if request is None:
            return {"status": "not_supported"}
        proxy = self.config.get("proxy_url")
        with build_opener(_NoRedirect(), ProxyHandler({"http": proxy, "https": proxy} if proxy else {})).open(request, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        try:
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("Oversized metadata.")
            value = parse_json(raw)
            id_field = 'id'
            has_more = value.get('has_more') is True
            if 'data' in value:
                models = value['data']
            else:
                output = value['output']
                total, page, size = (output[field] for field in ('total', 'page_no', 'page_size'))
                if (value.get('success') is False or type(total) is not int or total < 0
                        or type(page) is not int or page < 1 or type(size) is not int or size < 1):
                    raise ValueError('Invalid directory pagination.')
                models, id_field, has_more = output['models'], 'model', total > page * size
            if (not isinstance(models, list) or _contains_credential(value, self._credential)
                    or any(not isinstance(item, dict) or not isinstance(item.get(id_field), str) or not item[id_field] for item in models)):
                raise ValueError("Invalid model list.")
            available = []
            for item in models:
                name = item.get('name') or item.get('display_name') or item[id_field]
                if not isinstance(name, str):
                    raise ValueError('Invalid model display name.')
                available.append({'id': item[id_field], 'name': name})
            return {"status": "reachable", "model_listed": any(item["id"] == self.model for item in available),
                'models': available, 'has_more': has_more}
        except (RunError, ValueError, KeyError, TypeError):
            raise RunError("invalid_provider_response", "admission", "Model directory returned invalid metadata.") from None

    @staticmethod
    def decode_reply(value: dict[str, Any]) -> dict[str, Any]:
        """Decode protocol evidence identically for HTTP and credential-free restoration."""
        raise NotImplementedError

    def _http_complete(self, messages: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
        # Only the declared route is used; redirects could expose origin credentials.
        proxy = self.config.get("proxy_url")
        proxies = {"http": proxy, "https": proxy} if proxy else {}
        with build_opener(_NoRedirect(), ProxyHandler(proxies)).open(self._request(messages), timeout=timeout) as response:
            provider_request_id = response.headers.get(self.request_id_header)
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise RunError("invalid_provider_response", "llm", "Provider response exceeds the supported size.")
        try:
            value = parse_json(raw)
            if (self._credential.encode() in raw or _contains_credential(value, self._credential)
                    or self._credential in (provider_request_id or "")):
                raise ValueError("Response contains a credential.")
            reply = self.decode_reply(value)
            _validate_reply(reply)
            if _contains_credential(reply, self._credential):
                raise ValueError("Decoded response contains a credential.")
            return {**reply, "provider_request_id": provider_request_id,
                    "response_sha256": hashlib.sha256(raw).hexdigest(), "raw_reply": raw.decode("utf-8")}
        except (Exception, SystemExit) as error:
            raise RunError("invalid_provider_response", "llm", "Provider returned an invalid text response.") from error


class OpenAICompatibleProvider(HTTPTextProvider):
    plugin_id = "llm4om.providers.openai_compatible"
    endpoint_path = "/chat/completions"
    request_id_header = "x-request-id"
    connectivity_profile = "models_get/0.1.0"

    def _models_request(self) -> Request:
        base = self.config['base_url'].rstrip('/')
        url = base + '/models'
        # DashScope's compatibility route uses its native directory on the same origin.
        if urlsplit(base).path == '/compatible-mode/v1':
            url = base.removesuffix('/compatible-mode/v1') + '/api/v1/models?capabilities=TG&page_no=1&page_size=100'
        return Request(url,
                       headers={"Authorization": "Bearer " + self._credential}, method="GET")

    def _request(self, messages: list[dict[str, Any]]) -> Request:
        body = json.dumps({"model": self.model, "messages": messages,
                           "max_tokens": self.max_output_tokens, "stream": False}, allow_nan=False).encode()
        return Request(self.identity, body, {"Content-Type": "application/json",
                       "Authorization": "Bearer " + self._credential}, method="POST")

    @staticmethod
    def decode_reply(value: dict[str, Any]) -> dict[str, Any]:
        choice = value["choices"][0]
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("Invalid text.")
        fields = _reply_usage(value)
        if any(token is not None and (type(token) is not int or token < 0) for token in fields.values()):
            raise ValueError("Invalid usage.")
        def optional(field: Any) -> str | None:
            return field if isinstance(field, str) else None
        return {"text": content, "response_id": optional(value.get("id")), "model": optional(value.get("model")),
                "finish_reason": optional(choice.get("finish_reason")), "usage": fields}


class AnthropicProvider(HTTPTextProvider):
    plugin_id = "llm4om.providers.anthropic"
    endpoint_path = "/messages"
    request_id_header = "request-id"
    connectivity_profile = "models_get/0.1.0"

    def _models_request(self) -> Request:
        return Request(self.config["base_url"].rstrip("/") + "/models",
                       headers={"x-api-key": self._credential, "anthropic-version": "2023-06-01"}, method="GET")

    def _request(self, messages: list[dict[str, Any]]) -> Request:
        system = [block for message in messages if message["role"] == "system"
                  for block in ([{"type": "text", "text": message["content"]}]
                                if isinstance(message["content"], str) else message["content"])]
        body = {"model": self.model, "max_tokens": self.max_output_tokens, "stream": False,
                "messages": [message for message in messages if message["role"] != "system"]}
        if system:
            body["system"] = system
        return Request(self.identity, json.dumps(body, allow_nan=False).encode(), {
            "Content-Type": "application/json", "x-api-key": self._credential,
            "anthropic-version": "2023-06-01"}, method="POST")

    @staticmethod
    def decode_reply(value: dict[str, Any]) -> dict[str, Any]:
        if value["type"] != "message" or value["role"] != "assistant":
            raise ValueError("Invalid Messages response.")
        blocks = value["content"]
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("Missing content blocks.")
        text = []
        for block in blocks:
            kind = block["type"]
            if kind == "text" and isinstance(block["text"], str):
                text.append(block["text"])
            elif kind == "thinking" and isinstance(block["thinking"], str):
                continue
            elif kind == "redacted_thinking" and isinstance(block["data"], str):
                continue
            else:
                raise ValueError("Unsupported or invalid content block.")
        stop = value.get("stop_reason")
        if not text and stop != "max_tokens":
            raise ValueError("Missing text response.")
        usage = value.get("usage")
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            raise ValueError("Invalid usage.")
        counts = [usage.get(key) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")]
        if any(count is not None and (type(count) is not int or count < 0) for count in counts):
            raise ValueError("Invalid usage count.")
        def known_sum(values: list[Any]) -> int | None:
            return sum(values) if all(value is not None for value in values) else None
        for key in ("id", "model", "stop_reason"):
            if value.get(key) is not None and not isinstance(value[key], str):
                raise ValueError("Invalid response identity.")
        return {"text": "".join(text), "response_id": value.get("id"), "model": value.get("model"),
                "stop_reason": stop, "finish_reason": {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length"}.get(stop, stop) if isinstance(stop, str) else None,
                "usage": {"input_tokens": known_sum(counts[:3]), "output_tokens": counts[3],
                          "cached_tokens": known_sum(counts[1:3]), "total_tokens": known_sum(counts),
                          "reasoning_tokens": None}}


class HTTPTextFactory:
    provider_type: type[HTTPTextProvider]

    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.2.0", "kind": "llm_provider", "plugin_version": "0.1.0",
                "contract_range": ">=0.2.0,<0.3.0", "display_name": self.provider_type.__name__,
                "description": "Non-streaming HTTP text Adapter with shared Gateway accounting.",
                "capabilities": {"provider_profile": "http_text/0.1.0", "problem_types": [],
                    "input_artifact_kinds": ["text_messages"], "output_artifact_kinds": ["text_response"],
                    "llm_features": ["text"],
                    **({"connectivity_check": self.provider_type.connectivity_profile} if self.provider_type.connectivity_profile else {}), "usage_semantics":
                        "total includes cached input and reasoning output; missing fields are unknown"},
                "dependencies": {"python": []}, "source": None,
                "plugin_id": self.provider_type.plugin_id,
                "config_schema": {"type": "object", "properties": {
                    "base_url": {"type": "string", "minLength": 1},
                    "credential_env": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z_0-9]*$"},
                    "proxy_url": {"type": "string", "minLength": 1},
                    "max_output_tokens": {"type": "integer", "minimum": 1},
                    "max_retries": {"type": "integer", "minimum": 0, "maximum": 5},
                    "timeout_s": {"type": "number", "exclusiveMinimum": 0}},
                    "required": ["base_url", "credential_env"], "additionalProperties": False}}

    def validate(self, config: dict[str, Any], model: str) -> None:
        try:
            jsonschema.Draft202012Validator(self.describe()["config_schema"]).validate(config)
            address = urlsplit(config["base_url"])
            if address.port == 0:
                raise ValueError("Invalid endpoint port.")
            if (address.scheme not in {"http", "https"} or not address.hostname or address.username
                    or address.password or address.query or address.fragment
                    or (address.scheme == "http" and address.hostname not in {"localhost", "127.0.0.1", "::1"})):
                raise ValueError("Unsupported endpoint.")
            if not model or not isinstance(model, str):
                raise ValueError("Model required.")
            if "proxy_url" in config:
                proxy = urlsplit(config["proxy_url"])
                if (proxy.scheme != "http" or not proxy.hostname or proxy.port == 0
                        or proxy.username is not None or proxy.password is not None
                        or proxy.path not in {"", "/"} or proxy.query or proxy.fragment
                        or any(ord(char) < 33 or char.isspace() for char in config["proxy_url"])):
                    raise ValueError("Unsupported HTTP proxy.")
        except (jsonschema.ValidationError, ValueError) as error:
            raise RunError("invalid_config", "admission", "Invalid text Provider configuration.") from error

    def create(self, config: dict[str, Any], model: str, *,
               environment: Mapping[str, str] | None = None) -> HTTPTextProvider:
        self.validate(config, model)
        return self.provider_type(config, model, _credential_value(config, os.environ if environment is None else environment))

    def restore(self, config: dict[str, Any], model: str, *,
                environment: Callable[[], Mapping[str, str]]) -> HTTPTextProvider:
        """Resolve credentials only if restored work actually needs another HTTP attempt."""
        self.validate(config, model)
        return self.provider_type(config, model, lambda: _credential_value(config, environment()))


class OpenAICompatibleFactory(HTTPTextFactory):
    provider_type = OpenAICompatibleProvider


class AnthropicFactory(HTTPTextFactory):
    provider_type = AnthropicProvider

    def validate(self, config: dict[str, Any], model: str) -> None:
        if set(config) & {"tools", "response_schema", "images", "stream"}:
            raise RunError("capability_mismatch", "admission", "Messages Adapter supports non-streaming text only.")
        super().validate(config, model)

    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest["capabilities"]["usage_semantics"] = (
                "input = uncached + cache creation + cache read; cached is their cache subset; "
                "total = input + output; missing components and reasoning are unknown")
        return manifest


class MockProvider:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def gateway(self, public: dict[str, Any], problem_sha256: str, store: Any,
                ledger: dict[str, Any], budget: Mapping[str, Any], config_dir: Path, *, deadline: float,
                role_providers: Mapping[str, HTTPTextProvider] | None = None) -> Any:
        if role_providers:
            raise RunError("capability_mismatch", "admission", "Mock Provider does not route external role models.")
        from llm4om.contracts import public_path
        from llm4om.mock import MockGateway
        return MockGateway(public_path(config_dir, self.config["response_artifact"]), public,
                           problem_sha256, store, ledger, budget["max_llm_attempts"])


class MockFactory:
    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.2.0", "kind": "llm_provider", "plugin_version": "0.1.0",
            "contract_range": ">=0.2.0,<0.3.0", "display_name": "Mock",
            "description": "Explicit replay of a public hand-authored artifact.",
            "capabilities": {"provider_profile": "mock_text/0.1.0", "problem_types": [],
                "input_artifact_kinds": ["text_messages"], "output_artifact_kinds": ["text_response"],
                "llm_features": ["text"]}, "dependencies": {"python": []}, "source": None,
            "plugin_id": "llm4om.providers.mock", "config_schema": {
            "type": "object", "properties": {"response_artifact": {"type": "string", "minLength": 1}},
            "required": ["response_artifact"], "additionalProperties": False}}

    def create(self, config: dict[str, Any], model: str, *, environment: Mapping[str, str] | None = None) -> MockProvider:
        try:
            jsonschema.Draft202012Validator(self.describe()["config_schema"]).validate(config)
        except jsonschema.ValidationError as error:
            raise RunError("invalid_config", "admission", "Invalid Mock Provider configuration.") from error
        return MockProvider(config)


def provider_factory(plugin_id: str) -> HTTPTextFactory | MockFactory:
    from llm4om.plugins import discover_plugins
    plugin = discover_plugins().get(("llm_provider", plugin_id))
    if plugin is None:
        raise RunError("unknown_plugin", "admission", "Requested Provider is not installed.")
    factory = plugin.factory
    if not isinstance(factory, (HTTPTextFactory, MockFactory)):
        raise RunError("invalid_plugin_manifest", "admission", "Provider factory has no supported text profile.")
    return factory


_TRANSPORT_COMMAND = [sys.executable, "-c", "from llm4om.providers import _transport_main; _transport_main()"]


def _transport_result(raw: bytes) -> dict[str, Any]:
    if not raw:
        raise RunError("provider_connection_error", "llm", "Provider transport exited without a result.")
    value = parse_json(raw)
    if "http_status" in value:
        raise HTTPError("", value["http_status"], "Provider HTTP request failed.", Message(), None)
    if "error" in value:
        diagnostic = value.get('connection_diagnostic')
        details = {'connection_diagnostic': diagnostic} if isinstance(diagnostic, str) and diagnostic in _CONNECTION_DIAGNOSTICS else None
        raise RunError(value["error"], "llm", "Provider request failed; outcome and charge may be unknown.", details=details)
    result: dict[str, Any] = value["reply"]
    return result


def _transport_main() -> None:
    value = json.loads(sys.stdin.buffer.read())
    # The isolated child must not let NO_PROXY override an explicitly selected route.
    if value["config"].get("proxy_url"):
        os.environ.pop("NO_PROXY", None)
        os.environ.pop("no_proxy", None)
    factory = provider_factory(value["provider"])
    if not isinstance(factory, HTTPTextFactory):
        raise ValueError("Provider has no HTTP transport.")
    provider = factory.provider_type(value["config"], value["model"], value["credential"])
    try:
        from llm4om.plugins import _quiet
        with _quiet():
            result: dict[str, Any] = {"reply": provider._http_connectivity(value["timeout"])
                if value.get("operation") == "models_get" else provider._http_complete(value["messages"], value["timeout"])}
    except HTTPError as error:
        status = error.code
        error.close()
        result = {"http_status": status}
    except (TimeoutError, URLError, ConnectionError, OSError) as error:
        result = {"error": _connection_code(error), "connection_diagnostic": _connection_diagnostic(error)}
    except RunError as error:
        result = {"error": error.code}
    sys.stdout.buffer.write(json.dumps(result, allow_nan=False).encode())
