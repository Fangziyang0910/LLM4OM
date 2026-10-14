"""Read immutable public run references and their admitted reference graph."""

import hashlib
from pathlib import Path
from typing import Any

from llm4om.contracts import RunError, parse_json, public_path, read_public_bytes
from llm4om.storage import RunStore


def read_run_ref(run: Path, ref: dict[str, Any], *, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    if ref.get("namespace") != "run_public":
        raise RunError("private_reference", "storage", "Only public run references are readable.")
    raw = read_public_bytes(public_path(run, ref["relative_path"]), max_bytes=max_bytes)
    if len(raw) != ref["size_bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise RunError("artifact_hash_mismatch", "storage", "Public artifact differs from its immutable reference.")
    return raw


def load_run_record(store: RunStore, ref: dict[str, Any]) -> dict[str, Any]:
    visited: dict[str, Any] = {}
    def load(reference: dict[str, Any]) -> Any:
        if reference not in store.refs:
            raise RunError("checkpoint_incompatible", "storage", "Result refers to an unverified artifact.")
        name = reference["relative_path"]
        if name not in visited:
            raw = read_run_ref(store.path, reference)
            value = parse_json(raw) if reference["media_type"] == "application/json" else None
            visited[name] = value
            verify(value)
        return visited[name]
    def verify(value: Any) -> None:
        if isinstance(value, dict):
            if {"relative_path", "namespace", "sha256"} <= value.keys():
                load(value)
            else:
                for item in value.values():
                    verify(item)
        elif isinstance(value, list):
            for item in value:
                verify(item)
    value = load(ref)
    if not isinstance(value, dict):
        raise RunError("checkpoint_incompatible", "storage", "Run record must be a JSON object.")
    return value
