"""Persist public run evidence and content-addressed references."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


class RunStore:
    def __init__(self, root: Path) -> None:
        self.run_id = uuid4().hex
        self.path = root.resolve() / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        self.refs: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def write(self, name: str, content: bytes, artifact_id: str,
              schema_version: str | None = None) -> dict[str, Any]:
        destination = self.path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
        ref = {
            "artifact_id": artifact_id,
            "media_type": {".json": "application/json", ".csv": "text/csv", ".md": "text/markdown",
                           ".jsonl": "application/x-ndjson"}.get(destination.suffix, "application/octet-stream"),
            "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
            "namespace": "run_public", "relative_path": name, "schema_version": schema_version,
        }
        self.refs = [item for item in self.refs if item["relative_path"] != name] + [ref]
        return ref

    def json(self, name: str, value: dict[str, Any], artifact_id: str) -> dict[str, Any]:
        raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        return self.write(name, raw, artifact_id, value.get("schema_version"))

    def emit(self, kind: str, **fields: Any) -> None:
        self.events.append({"sequence_no": len(self.events) + 1, "kind": kind, **fields})
        raw = "".join(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
                      for event in self.events).encode()
        self.write("events.jsonl", raw, "events")
