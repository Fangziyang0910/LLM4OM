"""Durable LLM call budgets, private resource journal and recovery."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, TYPE_CHECKING
from urllib.error import HTTPError, URLError
from uuid import uuid4
import jsonschema

from llm4om.contracts import RunError, parse_json, read_public_bytes
from llm4om.control import CancellationToken, _supervise
from llm4om.methods import LLMResponse
from llm4om.storage import RunStore, _atomic, _mkdir
if TYPE_CHECKING:
    from llm4om.providers import TextProvider, HTTPTextProvider


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
    return [{**{field: item[field] for field in fields},
             **({"connection_diagnostic": item["connection_diagnostic"]} if "connection_diagnostic" in item else {}),
             **({"stop_reason": item["stop_reason"]} if "stop_reason" in item else {})} for item in attempts]


@dataclass(frozen=True)
class RecoveredResources:
    ledger: dict[str, Any]
    trace: list[dict[str, Any]]


def _resource_state(archive: Path, *, expected: str | None = None,
                    allow_unpublished_genesis: bool = False) -> dict[str, Any]:
    from llm4om.providers import HTTPTextFactory, provider_factory, _validate_reply, _CONNECTION_DIAGNOSTICS
    """Verify the entire immutable chain, including the mutable head and core anchor."""
    # Full snapshots suit bounded runs; incremental records would scale to larger search budgets.
    try:
        decoders: dict[str, type[HTTPTextProvider]] = {}
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
            if cursor == current_hash and expected is not None and expected not in seen:
                raise ValueError("Mutable resource head precedes the committed core anchor.")
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
                               "finish_reason", "stop_reason", "provider_request_id", "usage", "reservation", "reply", "raw_reply", "connection_diagnostic"}
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
                if 'connection_diagnostic' in item and (not isinstance(item['connection_diagnostic'], str)
                        or item['connection_diagnostic'] not in _CONNECTION_DIAGNOSTICS):
                    raise ValueError('Invalid public connection diagnostic.')
                if (type(item["reservation"]) is not int or item["reservation"] < 0
                        or item["status"] not in {"unknown", "success"}
                        or any(value is not None and (type(value) is not int or value < 0) for value in item["usage"].values())):
                    raise ValueError("Invalid resource counters.")
                base_identity = state["provider_identity"]
                identity = base_identity.get("roles", {}).get(item["role"], base_identity)
                if (item["provider"] != identity["plugin_id"] or item["requested_model"] != identity["model"]
                        or item["endpoint_sha256"] != identity["endpoint_sha256"]
                        or not isinstance(item["request_id"], str) or not item["request_id"]
                        or re.fullmatch(r"[0-9a-f]{64}", item["request_sha256"]) is None
                        or type(item["estimated_input_tokens"]) is not int or item["estimated_input_tokens"] <= 0):
                    raise ValueError("Invalid immutable request identity.")
                if item["status"] == "success":
                    raw = item["raw_reply"].encode()
                    if identity["plugin_id"] not in decoders:
                        factory = provider_factory(identity["plugin_id"])
                        if not isinstance(factory, HTTPTextFactory):
                            raise ValueError("Resource Provider has no response decoder.")
                        decoders[identity["plugin_id"]] = factory.provider_type
                    from llm4om.plugins import _quiet
                    with _quiet():
                        decoded = decoders[identity["plugin_id"]].decode_reply(parse_json(raw))
                    _validate_reply(decoded)
                    if (hashlib.sha256(raw).hexdigest() != item["response_sha256"]
                            or any(item.get("reply" if key == "text" else key) != value for key, value in decoded.items())
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
    except (Exception, SystemExit) as error:
        raise RunError("checkpoint_incompatible", "admission", "Cannot verify the private resource journal and committed bytes.") from error


class Gateway:
    """A private archive is the run identity; restore uses that same archive and budget."""
    def __init__(self, provider: TextProvider, budget: Mapping[str, Any], archive: Path, *, deadline: float | None = None,
                 cancellation: CancellationToken | None = None,
                 on_save: Callable[[str, dict[str, Any]], None] | None = None,
                 inherited_ledger: Mapping[str, Any] | None = None,
                 role_providers: Mapping[str, HTTPTextProvider] | None = None) -> None:
        from llm4om.providers import HTTPTextProvider
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
        self.role_providers = dict(role_providers or {})
        if any(not isinstance(role, str) or not role.strip() or not isinstance(selected, HTTPTextProvider)
               for role, selected in self.role_providers.items()):
            raise RunError("invalid_config", "admission", "Role overrides require named HTTP text Providers.")
        identity = {"plugin_id": provider.plugin_id, "model": provider.model,
            "endpoint_sha256": hashlib.sha256(provider.identity.encode()).hexdigest(), "max_output_tokens": provider.max_output_tokens}
        if self.role_providers:
            identity["roles"] = {role: {"plugin_id": selected.plugin_id, "model": selected.model,
                "endpoint_sha256": hashlib.sha256(selected.identity.encode()).hexdigest(), "max_output_tokens": selected.max_output_tokens}
                for role, selected in self.role_providers.items()}
        self.cancellation = cancellation or CancellationToken()
        self._on_save = on_save
        self.inherited_ledger = dict(inherited_ledger or {})
        self.calls: list[LLMResponse] = []
        _mkdir(archive, mode=0o700)
        archive.chmod(0o700)
        with _resource_lock(self.archive):
            if not (archive / "state.json").exists():
                if any((archive / "journal").glob("*.json")):
                    _atomic(archive / "state.json", _resource_bytes(_resource_state(archive, allow_unpublished_genesis=True)))
                else:
                    self._save({"budget": self.budget, "deadline": deadline if deadline is not None else time.time() + budget["wall_time_s"], "attempts": [], "inherited_ledger": self.inherited_ledger, "archive_id": archive.name,
                            "provider_identity": identity})
            state = self._load()
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
        _mkdir(journal, mode=0o700)
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
        for message in request.get("messages", []) if isinstance(request.get("messages"), list) else []:
            if isinstance(message, dict) and isinstance(message.get("content"), list):
                if any(isinstance(block, dict) and block.get("type") != "text" for block in message["content"]):
                    raise RunError("capability_mismatch", "admission", "Provider supports text blocks only.")
        try:
            jsonschema.Draft202012Validator({"type": "object", "properties": {
                "messages": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
                    "role": {"enum": ["system", "user", "assistant"]}, "content": {"oneOf": [
                        {"type": "string"}, {"type": "array", "minItems": 1, "items": {
                            "type": "object", "properties": {"type": {"const": "text"}, "text": {"type": "string"}},
                            "required": ["type", "text"], "additionalProperties": False}}]}},
                    "required": ["role", "content"], "additionalProperties": False}},
                "request_id": {"type": "string", "minLength": 1}, "role": {"type": "string", "minLength": 1}},
                "required": ["messages"], "additionalProperties": False}).validate(request)
            provider = self.role_providers.get(request.get("role", "formulation"), self.provider)
            raw = json.dumps({"endpoint": provider.identity, "model": provider.model,
                              "max_output_tokens": provider.max_output_tokens,
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
            return await self._attempts(request, request_id, request_hash, len(raw), provider)
        finally:
            os.close(slot)

    async def _attempts(self, request: dict[str, Any], request_id: str, request_hash: str, estimate: int,
                        provider: TextProvider) -> LLMResponse:
        from llm4om.providers import _connection_code, _connection_diagnostic, _CONNECTION_DIAGNOSTICS
        for retry in range(provider.max_retries + 1):
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
                reservation = estimate + provider.max_output_tokens
                used = sum(item["reservation"] + (item["usage"]["total_tokens"] or 0) for item in state["attempts"])
                used += self.inherited_ledger.get("reserved_tokens", 0) + self.inherited_ledger.get("known_total_tokens", self.inherited_ledger.get("total_tokens") or 0)
                if len(state["attempts"]) + self.inherited_ledger.get("llm_attempts", 0) >= self.budget["max_llm_attempts"] or used + reservation > self.budget["max_total_tokens"]:
                    raise RunError("budget_exhausted", "admission", "No shared Provider attempt or token budget remains.")
                provider.prepare()
                self.cancellation.check()
                if time.time() >= state["deadline"]:
                    raise RunError("deadline_exhausted", "admission", "The shared run deadline has expired.")
                attempt_id = uuid4().hex
                item = {"attempt_id": attempt_id, "request_id": request_id, "request_sha256": request_hash,
                        "provider": provider.plugin_id,
                        "endpoint_sha256": hashlib.sha256(provider.identity.encode()).hexdigest(),
                        "requested_model": provider.model, "role": request.get("role", "formulation"),
                        "start": time.time(), "end": None, "reservation": reservation,
                        "estimated_input_tokens": estimate, "diagnostic": "outcome_unknown", "status": "unknown",
                        "response_id": None, "response_sha256": None, "model": None, "finish_reason": None,
                        "provider_request_id": None, "cost": None,
                        "usage": {key: None for key in ["input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens"]}}
                state["attempts"].append(item)
                self._save(state)
            reply = None
            code = None
            connection_diagnostic = None
            retryable = False
            try:
                reply = await _supervise(provider.acomplete(
                    request["messages"], min(provider.timeout_s, state["deadline"] - time.time())),
                    self.cancellation)
            except HTTPError as error:
                code = "auth_error" if error.code in {401, 403} else "rate_limit" if error.code == 429 else "provider_error" if error.code >= 500 else "invalid_provider_request"
                retryable = error.code == 429 or 500 <= error.code < 600
                error.close()
            except (TimeoutError, URLError, ConnectionError, OSError) as error:
                code = _connection_code(error)
                connection_diagnostic = _connection_diagnostic(error)
                retryable = code != "provider_timeout"
            except RunError as error:
                code = error.code
                candidate_diagnostic = (error.details or {}).get('connection_diagnostic')
                if isinstance(candidate_diagnostic, str) and candidate_diagnostic in _CONNECTION_DIAGNOSTICS:
                    connection_diagnostic = candidate_diagnostic
                retryable = code in {"rate_limit", "provider_error", "provider_connection_error"}
            with _resource_lock(self.archive):
                state = self._load()
                item = next(item for item in state["attempts"] if item["attempt_id"] == attempt_id)
                item.update(end=time.time(), diagnostic=code, status="success" if reply is not None else "unknown")
                if connection_diagnostic is not None:
                    item['connection_diagnostic'] = connection_diagnostic
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
            if not retryable or retry == provider.max_retries:
                raise RunError(code or "provider_error", "llm", "Provider request failed; outcome and charge may be unknown.",
                    details={'connection_diagnostic': connection_diagnostic} if connection_diagnostic is not None else None)
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


def run_gateway(provider: TextProvider, store: RunStore, budget: Mapping[str, Any], *, deadline: float,
                role_providers: Mapping[str, HTTPTextProvider] | None = None) -> Gateway:
    archive = store.path.parent / ".private" / store.run_id
    def saved(digest: str, ledger: dict[str, Any]) -> None:
        store.state["gateway_sha256"] = digest
        store.state["ledger"].update(ledger)
        store.checkpoint()
    gateway = Gateway(provider, budget, archive, deadline=deadline, cancellation=store.cancellation, on_save=saved,
                      inherited_ledger=store.state.get("inherited_ledger"), role_providers=role_providers)
    saved(hashlib.sha256((archive / "state.json").read_bytes()).hexdigest(), gateway.ledger)
    return gateway
