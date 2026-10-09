"""Text-only Provider interface and durable run resource Gateway."""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol
from llm4om.control import CancellationToken, _supervise
from llm4om.storage import _atomic
from llm4om.contracts import read_public_bytes
from urllib.error import HTTPError, URLError
from uuid import uuid4
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
import fcntl

import jsonschema

from llm4om.contracts import RunError, parse_json
from llm4om.methods import LLMResponse


class TextProvider(Protocol):
    plugin_id: str
    model: str
    identity: str
    max_output_tokens: int
    max_retries: int
    timeout_s: float

    def complete(self, messages: list[dict[str, str]], timeout: float) -> dict[str, Any]: ...

    async def acomplete(self, messages: list[dict[str, str]], timeout: float) -> dict[str, Any]: ...


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


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _connection_code(error: Exception) -> str:
    reason = error.reason if isinstance(error, URLError) else error
    return "provider_timeout" if isinstance(reason, TimeoutError) else "provider_connection_error"


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


class OpenAICompatibleProvider:
    plugin_id = "llm4om.providers.openai_compatible"

    def __init__(self, config: dict[str, Any], model: str, credential: str) -> None:
        self.model = model
        self.identity = config["base_url"].rstrip("/") + "/chat/completions"
        self.max_output_tokens = config.get("max_output_tokens", 1024)
        self.max_retries = config.get("max_retries", 2)
        self.timeout_s = float(config.get("timeout_s", 30))
        self._credential = credential

    def gateway(self, public: dict[str, Any], problem_sha256: str, store: Any,
                ledger: dict[str, Any], budget: Mapping[str, Any], config_dir: Path, *, deadline: float) -> "Gateway":
        archive = store.path.parent / ".private" / store.run_id
        def saved(digest: str, ledger: dict[str, Any]) -> None:
            store.state["gateway_sha256"] = digest
            store.state["ledger"].update(ledger)
            store.checkpoint()
        gateway = Gateway(self, budget, archive, deadline=deadline, cancellation=store.cancellation, on_save=saved,
                          inherited_ledger=store.state.get("inherited_ledger"))
        saved(hashlib.sha256((archive / "state.json").read_bytes()).hexdigest(), gateway.ledger)
        return gateway

    def _transport_input(self, messages: list[dict[str, str]], timeout: float) -> bytes:
        return json.dumps({"endpoint": self.identity, "model": self.model,
                           "max_output_tokens": self.max_output_tokens, "credential": self._credential,
                           "messages": messages, "timeout": timeout}, allow_nan=False).encode()

    def complete(self, messages: list[dict[str, str]], timeout: float) -> dict[str, Any]:
        if timeout <= 0:
            raise TimeoutError("Provider request deadline expired.")
        started = time.monotonic()
        payload = self._transport_input(messages, timeout)
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

    async def acomplete(self, messages: list[dict[str, str]], timeout: float) -> dict[str, Any]:
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

    def _http_complete(self, messages: list[dict[str, str]], timeout: float) -> dict[str, Any]:
        body = json.dumps({"model": self.model, "messages": messages,
                           "max_tokens": self.max_output_tokens, "stream": False}, allow_nan=False).encode()
        request = Request(self.identity, body, {"Content-Type": "application/json",
                          "Authorization": "Bearer " + self._credential}, method="POST")
        # Redirects could expose Authorization to a different origin; proxies are not part of this profile.
        with build_opener(_NoRedirect(), ProxyHandler({})).open(request, timeout=timeout) as response:
            provider_request_id = response.headers.get("x-request-id")
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise RunError("invalid_provider_response", "llm", "Provider response exceeds the supported size.")
        try:
            if self._credential.encode() in raw:
                raise ValueError("Response contains a credential.")
            value = parse_json(raw)
            if _contains_credential(value, self._credential):
                raise ValueError("Decoded response contains a credential.")
            choices = value["choices"]
            content = choices[0]["message"]["content"]
            if not isinstance(content, str) or self._credential in content:
                raise ValueError("Invalid content.")
            fields = _reply_usage(value)
            if any(token is not None and (type(token) is not int or token < 0) for token in fields.values()):
                raise ValueError("Invalid usage.")
            def safe(field: Any) -> str | None:
                return field if isinstance(field, str) and self._credential not in field else None
            return {"text": content, "response_id": safe(value.get("id")), "model": safe(value.get("model")),
                    "provider_request_id": safe(provider_request_id),
                    "finish_reason": safe(choices[0].get("finish_reason")), "usage": fields,
                    "response_sha256": hashlib.sha256(raw).hexdigest(), "raw_reply": raw.decode("utf-8")}
        except (RunError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise RunError("invalid_provider_response", "llm", "Provider returned an invalid text response.") from error


class OpenAICompatibleFactory:
    def describe(self) -> dict[str, Any]:
        return {"plugin_id": "llm4om.providers.openai_compatible", "features": ["text"],
                "usage_semantics": "total includes cached input and reasoning output; missing fields are unknown",
                "config_schema": {"type": "object", "properties": {
                    "base_url": {"type": "string", "minLength": 1},
                    "credential_env": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z_0-9]*$"},
                    "max_output_tokens": {"type": "integer", "minimum": 1},
                    "max_retries": {"type": "integer", "minimum": 0, "maximum": 5},
                    "timeout_s": {"type": "number", "exclusiveMinimum": 0}},
                    "required": ["base_url", "credential_env"], "additionalProperties": False}}

    def create(self, config: dict[str, Any], model: str, *,
               environment: Mapping[str, str] | None = None) -> OpenAICompatibleProvider:
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
        except (jsonschema.ValidationError, ValueError) as error:
            raise RunError("invalid_config", "admission", "Invalid text Provider configuration.") from error
        credential = (os.environ if environment is None else environment).get(config["credential_env"])
        if not credential or any(ord(character) < 32 or ord(character) > 126 for character in credential):
            raise RunError("auth_error", "admission", "Provider requires a valid credential environment variable.")
        return OpenAICompatibleProvider(config, model, credential)


def _resource_bytes(state: dict[str, Any]) -> bytes:
    return json.dumps(state, allow_nan=False).encode()


@contextmanager
def _resource_lock(archive: Path) -> Iterator[None]:
    descriptor = os.open(archive / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _public_trace(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("attempt_id", "request_id", "request_sha256", "provider", "endpoint_sha256",
              "requested_model", "role", "start", "end", "reservation", "estimated_input_tokens",
              "diagnostic", "status", "response_id", "response_sha256", "model", "finish_reason",
              "provider_request_id", "cost", "usage")
    return [{field: item[field] for field in fields} for item in attempts]


@dataclass(frozen=True)
class RecoveredResources:
    ledger: dict[str, Any]
    trace: list[dict[str, Any]]


def _resource_state(archive: Path, *, expected: str | None = None,
                    allow_unpublished_genesis: bool = False) -> dict[str, Any]:
    """Verify the entire immutable chain, including the mutable head and core anchor."""
    # ponytail: full snapshots suit bounded runs; use incremental records for large search budgets.
    try:
        head = archive / "state.json"
        current = read_public_bytes(head) if head.exists() else None
        current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
        versions: dict[str, dict[str, Any]] = {}
        children: dict[str | None, str] = {}
        for path in (archive / "journal").glob("*.json"):
            envelope = parse_json(read_public_bytes(path))
            state = envelope["state"]
            digest = hashlib.sha256(_resource_bytes(state)).hexdigest()
            previous = envelope["previous_sha256"]
            if (path.stem != digest or envelope["schema_version"] != "0.1.0"
                    or previous in children or digest in versions):
                raise ValueError("Invalid resource chain.")
            versions[digest] = state
            children[previous] = digest
        if ((current_hash is not None and current_hash not in versions)
                or (expected is not None and expected not in versions)
                or (current_hash is None and not allow_unpublished_genesis)):
            raise ValueError("Missing resource anchor or invalid mutable bytes.")
        previous_state = None
        seen = set()
        cursor = children.get(None)
        while cursor is not None:
            if cursor in seen:
                raise ValueError("Resource cycle.")
            seen.add(cursor)
            state = versions[cursor]
            attempts = state["attempts"]
            if state["archive_id"] != archive.name or len({item["attempt_id"] for item in attempts}) != len(attempts):
                raise ValueError("Resource identity mismatch.")
            if previous_state is not None:
                if any(state[key] != previous_state[key] for key in ("budget", "deadline", "archive_id", "provider_identity", "inherited_ledger")):
                    raise ValueError("Resource configuration changed.")
                old = previous_state["attempts"]
                if len(attempts) not in (len(old), len(old) + 1):
                    raise ValueError("Resource attempts were dropped.")
                changed = 0
                for before, after in zip(old, attempts):
                    if before == after:
                        continue
                    changed += 1
                    mutable = {"end", "diagnostic", "status", "response_id", "response_sha256", "model",
                               "finish_reason", "provider_request_id", "usage", "reservation", "reply", "raw_reply"}
                    if (before["status"] != "unknown" or before["end"] is not None
                            or any(after.get(key) != value for key, value in before.items() if key not in mutable)
                            or (after["status"] != "success" and after["reservation"] != before["reservation"])):
                        raise ValueError("Invalid resource settlement.")
                if changed != (1 if len(attempts) == len(old) else 0):
                    raise ValueError("Invalid resource transition.")
                if len(attempts) > len(old) and (attempts[-1]["status"] != "unknown" or attempts[-1]["end"] is not None):
                    raise ValueError("Admission must preserve an unknown reservation before sending.")
            elif attempts:
                raise ValueError("Resource genesis must be empty.")
            for item in attempts:
                if (type(item["reservation"]) is not int or item["reservation"] < 0
                        or item["status"] not in {"unknown", "success"}
                        or any(value is not None and (type(value) is not int or value < 0) for value in item["usage"].values())):
                    raise ValueError("Invalid resource counters.")
                identity = state["provider_identity"]
                if (item["provider"] != identity["plugin_id"] or item["requested_model"] != identity["model"]
                        or item["endpoint_sha256"] != identity["endpoint_sha256"]
                        or not isinstance(item["request_id"], str) or not item["request_id"]
                        or re.fullmatch(r"[0-9a-f]{64}", item["request_sha256"]) is None
                        or type(item["estimated_input_tokens"]) is not int or item["estimated_input_tokens"] <= 0):
                    raise ValueError("Invalid immutable request identity.")
                if item["status"] == "success":
                    raw = item["raw_reply"].encode()
                    reply = parse_json(raw)
                    if (hashlib.sha256(raw).hexdigest() != item["response_sha256"]
                            or reply["choices"][0]["message"]["content"] != item["reply"]
                            or _reply_usage(reply) != item["usage"]
                            or (item["usage"]["total_tokens"] is not None and item["reservation"] != 0)):
                        raise ValueError("Invalid response bytes or settlement.")
                if (item["usage"]["total_tokens"] is None
                        and item["reservation"] != item["estimated_input_tokens"] + identity["max_output_tokens"]):
                    raise ValueError("Reservation changed without known usage.")
                if item["status"] == "unknown" and (item.get("reply") is not None or item["reservation"] <= 0):
                    raise ValueError("Unknown outcomes require held reservations.")
            previous_state = state
            following = children.get(cursor)
            if following is None:
                if len(seen) != len(versions):
                    raise ValueError("Disconnected resource chain.")
                if current_hash is None and (len(versions) != 1 or attempts or expected is not None):
                    raise ValueError("Only an unpublished empty genesis can lack its head.")
                return state
            cursor = following
        raise ValueError("Missing resource genesis.")
    except (OSError, RunError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        raise RunError("checkpoint_incompatible", "admission", "Cannot verify the private resource journal and committed bytes.") from error


class Gateway:
    """A private archive is the run identity; restore uses that same archive and budget."""
    def __init__(self, provider: TextProvider, budget: Mapping[str, Any], archive: Path, *, deadline: float | None = None,
                 cancellation: CancellationToken | None = None,
                 on_save: Callable[[str, dict[str, Any]], None] | None = None,
                 inherited_ledger: Mapping[str, Any] | None = None) -> None:
        try:
            jsonschema.Draft202012Validator({"type": "object", "properties": {
                **{name: {"type": "integer", "minimum": 0} for name in ["max_llm_attempts", "max_total_tokens"]},
                "max_concurrency": {"type": "integer", "minimum": 1},
                "wall_time_s": {"type": "number", "exclusiveMinimum": 0}},
                "required": ["max_llm_attempts", "max_total_tokens", "max_concurrency", "wall_time_s"]}).validate(dict(budget))
            json.dumps(dict(budget), allow_nan=False)
        except (jsonschema.ValidationError, ValueError, TypeError) as error:
            raise RunError("invalid_config", "admission", "Invalid shared Gateway budget.") from error
        self.provider, self.budget, self.archive = provider, dict(budget), archive
        self.cancellation = cancellation or CancellationToken()
        self._on_save = on_save
        self.inherited_ledger = dict(inherited_ledger or {})
        self.calls: list[LLMResponse] = []
        archive.mkdir(parents=True, exist_ok=True, mode=0o700)
        archive.chmod(0o700)
        with _resource_lock(self.archive):
            if not (archive / "state.json").exists():
                if any((archive / "journal").glob("*.json")):
                    _atomic(archive / "state.json", _resource_bytes(_resource_state(archive, allow_unpublished_genesis=True)))
                else:
                    self._save({"budget": self.budget, "deadline": deadline if deadline is not None else time.time() + budget["wall_time_s"], "attempts": [], "inherited_ledger": self.inherited_ledger, "archive_id": archive.name,
                            "provider_identity": {"plugin_id": provider.plugin_id, "model": provider.model,
                                "endpoint_sha256": hashlib.sha256(provider.identity.encode()).hexdigest(),
                                "max_output_tokens": provider.max_output_tokens}})
            state = self._load()
            identity = {"plugin_id": provider.plugin_id, "model": provider.model,
                        "endpoint_sha256": hashlib.sha256(provider.identity.encode()).hexdigest(),
                        "max_output_tokens": provider.max_output_tokens}
            if state["inherited_ledger"] != self.inherited_ledger or state["provider_identity"] != identity or state["budget"] != self.budget or (deadline is not None and state["deadline"] != deadline):
                raise RunError("checkpoint_incompatible", "admission", "Gateway identity or budget differs from its saved resource state.")
            _atomic(archive / "state.json", _resource_bytes(state))

    @classmethod
    def recover(cls, archive: Path, *, expected_sha256: str, budget: Mapping[str, Any],
                deadline: float, inherited_ledger: Mapping[str, Any]) -> RecoveredResources:
        """Verify durable usage without credentials; return only public resource evidence."""
        try:
            with _resource_lock(archive):
                state = _resource_state(archive, expected=expected_sha256)
                if (state["budget"] != dict(budget) or state["deadline"] != deadline
                        or state["inherited_ledger"] != dict(inherited_ledger)):
                    raise RunError("checkpoint_incompatible", "admission", "Resource budget or deadline changed.")
                return RecoveredResources(cls._ledger(state["attempts"], state["inherited_ledger"]),
                                          _public_trace(state["attempts"]))
        except (OSError, KeyError, TypeError) as error:
            raise RunError("checkpoint_incompatible", "admission", "Cannot recover saved resource evidence.") from error

    def _load(self) -> dict[str, Any]:
        return _resource_state(self.archive)

    def _save(self, state: dict[str, Any]) -> None:
        raw = _resource_bytes(state)
        journal = self.archive / "journal"
        journal.mkdir(mode=0o700, exist_ok=True)
        previous = None
        if (self.archive / "state.json").exists():
            previous = hashlib.sha256(_resource_bytes(self._load())).hexdigest()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != previous:
            version = journal / (digest + ".json")
            if version.exists():
                raise RunError("checkpoint_incompatible", "storage", "Resource version already exists.")
            _atomic(version, json.dumps({"schema_version": "0.1.0", "previous_sha256": previous,
                                       "state": state}, allow_nan=False).encode())
        _atomic(self.archive / "state.json", raw)
        if self._on_save is not None:
            self._on_save(hashlib.sha256(raw).hexdigest(), self._ledger(state["attempts"], self.inherited_ledger))

    @property
    def trace(self) -> list[dict[str, Any]]:
        with _resource_lock(self.archive):
            return _public_trace(self._load()["attempts"])

    @property
    def ledger(self) -> dict[str, Any]:
        with _resource_lock(self.archive):
            attempts = self._load()["attempts"]
        return self._ledger(attempts, self.inherited_ledger)

    @staticmethod
    def _ledger(attempts: list[dict[str, Any]], inherited: Mapping[str, Any] | None = None) -> dict[str, Any]:
        inherited = inherited or {}
        known = [item["usage"]["total_tokens"] for item in attempts if item["usage"]["total_tokens"] is not None]
        return {"llm_attempts": len(attempts) + inherited.get("llm_attempts", 0),
                "external_llm_requests": len(attempts) + inherited.get("external_llm_requests", 0),
                "total_tokens": sum(known) + (inherited.get("total_tokens") or 0)
                if len(known) == len(attempts) and (not inherited or inherited.get("total_tokens") is not None) else None,
                "known_total_tokens": sum(known) + inherited.get("known_total_tokens", inherited.get("total_tokens") or 0),
                "reserved_tokens": sum(item["reservation"] for item in attempts) + inherited.get("reserved_tokens", 0), "cost": None,
                "evidence_origin": "external_provider"}

    async def complete(self, request: dict[str, Any]) -> LLMResponse:
        self.cancellation.check()
        if set(request) - {"messages", "request_id", "role"}:
            raise RunError("capability_mismatch", "admission", "Provider supports non-streaming text messages only.")
        try:
            jsonschema.Draft202012Validator({"type": "object", "properties": {
                "messages": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
                    "role": {"enum": ["system", "user", "assistant"]}, "content": {"type": "string"}},
                    "required": ["role", "content"], "additionalProperties": False}},
                "request_id": {"type": "string", "minLength": 1}, "role": {"type": "string", "minLength": 1}},
                "required": ["messages"], "additionalProperties": False}).validate(request)
            raw = json.dumps({"endpoint": self.provider.identity, "model": self.provider.model,
                              "max_output_tokens": self.provider.max_output_tokens,
                              "request": request}, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        except (jsonschema.ValidationError, ValueError, TypeError) as error:
            raise RunError("invalid_llm_request", "admission", "Requests require role/text messages.") from error
        request_hash = hashlib.sha256(raw).hexdigest()
        request_id = request.get("request_id", uuid4().hex)
        with _resource_lock(self.archive):
            state = self._load()
            for item in state["attempts"]:
                if item["request_id"] == request_id:
                    if item["request_sha256"] != request_hash:
                        raise RunError("checkpoint_incompatible", "admission", "Saved request identity has different content.")
                    if item.get("reply") is not None:
                        return self._response(item)
            if any(item["request_id"] == request_id for item in state["attempts"]):
                raise RunError("provider_outcome_unknown", "llm", "Saved request has no reusable reply; reservations remain held.")
        # OS locks release on process exit, while unknown token reservations stay durable.
        slot = None
        for index in range(self.budget["max_concurrency"]):
            descriptor = os.open(self.archive / f"slot-{index}", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                slot = descriptor
                break
            except BlockingIOError:
                os.close(descriptor)
        if slot is None:
            raise RunError("budget_exhausted", "admission", "No shared Provider concurrency slot remains.")
        try:
            return await self._attempts(request, request_id, request_hash, len(raw))
        finally:
            os.close(slot)

    async def _attempts(self, request: dict[str, Any], request_id: str, request_hash: str, estimate: int) -> LLMResponse:
        for retry in range(self.provider.max_retries + 1):
            with _resource_lock(self.archive):
                state = self._load()
                for previous in state["attempts"]:
                    if (previous["request_id"] == request_id and previous["request_sha256"] == request_hash
                            and previous.get("reply") is not None):
                        return self._response(previous)
                if retry == 0 and any(previous["request_id"] == request_id for previous in state["attempts"]):
                    raise RunError("provider_outcome_unknown", "llm", "An identical shared request is already admitted.")
                remaining = state["deadline"] - time.time()
                if remaining <= 0:
                    raise RunError("deadline_exhausted", "admission", "The shared run deadline has expired.")
                reservation = estimate + self.provider.max_output_tokens
                used = sum(item["reservation"] + (item["usage"]["total_tokens"] or 0) for item in state["attempts"])
                used += self.inherited_ledger.get("reserved_tokens", 0) + self.inherited_ledger.get("known_total_tokens", self.inherited_ledger.get("total_tokens") or 0)
                if len(state["attempts"]) + self.inherited_ledger.get("llm_attempts", 0) >= self.budget["max_llm_attempts"] or used + reservation > self.budget["max_total_tokens"]:
                    raise RunError("budget_exhausted", "admission", "No shared Provider attempt or token budget remains.")
                attempt_id = uuid4().hex
                item = {"attempt_id": attempt_id, "request_id": request_id, "request_sha256": request_hash,
                        "provider": self.provider.plugin_id,
                        "endpoint_sha256": hashlib.sha256(self.provider.identity.encode()).hexdigest(),
                        "requested_model": self.provider.model, "role": request.get("role", "formulation"),
                        "start": time.time(), "end": None, "reservation": reservation,
                        "estimated_input_tokens": estimate, "diagnostic": "outcome_unknown", "status": "unknown",
                        "response_id": None, "response_sha256": None, "model": None, "finish_reason": None,
                        "provider_request_id": None, "cost": None,
                        "usage": {key: None for key in ["input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens"]}}
                state["attempts"].append(item)
                self._save(state)
            reply = None
            code = None
            retryable = False
            try:
                reply = await _supervise(self.provider.acomplete(
                    request["messages"], min(self.provider.timeout_s, state["deadline"] - time.time())),
                    self.cancellation)
            except HTTPError as error:
                code = "auth_error" if error.code in {401, 403} else "rate_limit" if error.code == 429 else "provider_error" if error.code >= 500 else "invalid_provider_request"
                retryable = error.code == 429 or 500 <= error.code < 600
                error.close()
            except (TimeoutError, URLError, ConnectionError, OSError) as error:
                code = _connection_code(error)
                retryable = code != "provider_timeout"
            except RunError as error:
                code = error.code
                retryable = code in {"rate_limit", "provider_error", "provider_connection_error"}
            with _resource_lock(self.archive):
                state = self._load()
                item = next(item for item in state["attempts"] if item["attempt_id"] == attempt_id)
                item.update(end=time.time(), diagnostic=code, status="success" if reply is not None else "unknown")
                if reply is not None:
                    item.update({key: value for key, value in reply.items() if key != "text"})
                    item["reply"] = reply["text"]
                    if reply["usage"]["total_tokens"] is not None:
                        item["reservation"] = 0
                    total = sum(entry["reservation"] + (entry["usage"]["total_tokens"] or 0) for entry in state["attempts"])
                    total += self.inherited_ledger.get("reserved_tokens", 0) + self.inherited_ledger.get("known_total_tokens", self.inherited_ledger.get("total_tokens") or 0)
                    if total > self.budget["max_total_tokens"]:
                        item["diagnostic"] = "token_budget_overrun"
                    elif time.time() > state["deadline"]:
                        item["diagnostic"] = "deadline_exhausted"
                self._save(state)
                remaining = state["deadline"] - time.time()
            if reply is not None:
                self.cancellation.check()
                return self._response(item)
            if not retryable or retry == self.provider.max_retries:
                raise RunError(code or "provider_error", "llm", "Provider request failed; outcome and charge may be unknown.")
            delay = min(0.1 * 2 ** retry, 1.0)
            if remaining <= delay:
                raise RunError("deadline_exhausted", "llm", "No shared deadline remains for a retry.")
            await asyncio.sleep(delay)
        raise AssertionError("Bounded attempts must return or fail.")

    def _response(self, item: dict[str, Any]) -> LLMResponse:
        if item["diagnostic"] in {"token_budget_overrun", "deadline_exhausted"}:
            raise RunError(item["diagnostic"], "llm", "Provider success exceeded a shared resource limit; reply is saved.")
        response = LLMResponse(item["reply"], item["attempt_id"], "external_provider", item["response_sha256"], item["finish_reason"])
        self.calls.append(response)
        return response


class MockProvider:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def gateway(self, public: dict[str, Any], problem_sha256: str, store: Any,
                ledger: dict[str, Any], budget: Mapping[str, Any], config_dir: Path, *, deadline: float) -> Any:
        from llm4om.contracts import public_path
        from llm4om.mock import MockGateway
        return MockGateway(public_path(config_dir, self.config["response_artifact"]), public,
                           problem_sha256, store, ledger, budget["max_llm_attempts"])


class MockFactory:
    def describe(self) -> dict[str, Any]:
        return {"plugin_id": "llm4om.providers.mock", "features": ["text"], "config_schema": {
            "type": "object", "properties": {"response_artifact": {"type": "string", "minLength": 1}},
            "required": ["response_artifact"], "additionalProperties": False}}

    def create(self, config: dict[str, Any], model: str, *, environment: Mapping[str, str] | None = None) -> MockProvider:
        try:
            jsonschema.Draft202012Validator(self.describe()["config_schema"]).validate(config)
        except jsonschema.ValidationError as error:
            raise RunError("invalid_config", "admission", "Invalid Mock Provider configuration.") from error
        return MockProvider(config)


def provider_factory(plugin_id: str) -> OpenAICompatibleFactory | MockFactory:
    factories: dict[str, OpenAICompatibleFactory | MockFactory] = {
        "llm4om.providers.mock": MockFactory(), "llm4om.providers.openai_compatible": OpenAICompatibleFactory()}
    factory = factories.get(plugin_id)
    if factory is None:
        raise RunError("unknown_plugin", "admission", "Requested Provider is not installed.")
    return factory


_TRANSPORT_COMMAND = [sys.executable, "-c", "from llm4om.providers import _transport_main; _transport_main()"]


def _transport_result(raw: bytes) -> dict[str, Any]:
    if not raw:
        raise RunError("provider_connection_error", "llm", "Provider transport exited without a result.")
    value = parse_json(raw)
    if "http_status" in value:
        raise HTTPError("", value["http_status"], "Provider HTTP request failed.", Message(), None)
    if "error" in value:
        raise RunError(value["error"], "llm", "Provider request failed; outcome and charge may be unknown.")
    result: dict[str, Any] = value["reply"]
    return result


def _transport_main() -> None:
    value = json.loads(sys.stdin.buffer.read())
    provider = OpenAICompatibleProvider({"base_url": value["endpoint"].removesuffix("/chat/completions"),
                                        "max_output_tokens": value["max_output_tokens"]},
                                       value["model"], value["credential"])
    try:
        result: dict[str, Any] = {"reply": provider._http_complete(value["messages"], value["timeout"])}
    except HTTPError as error:
        status = error.code
        error.close()
        result = {"http_status": status}
    except (TimeoutError, URLError, ConnectionError, OSError) as error:
        result = {"error": _connection_code(error)}
    except RunError as error:
        result = {"error": error.code}
    sys.stdout.buffer.write(json.dumps(result, allow_nan=False).encode())
