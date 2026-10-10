"""Admitted public bytes to a bounded, recorded modeling data view."""

import csv
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from io import StringIO
import json
from typing import Any, Protocol
import jsonschema

from llm4om.contracts import RunError, parse_json, validate_data

VIEW_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": {
    "mode": {"enum": ["preview", "full", "summary"]},
    "max_rows": {"type": "integer", "minimum": 1, "maximum": 10000},
    "max_columns": {"type": "integer", "minimum": 1, "maximum": 1024},
    "max_bytes": {"type": "integer", "minimum": 1, "maximum": 8 * 1024 * 1024},
    "columns": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}}}
DEFAULT_LIMITS = {"mode": "preview", "max_rows": 100, "max_columns": 32, "max_bytes": 65536}


@dataclass(frozen=True)
class DataContext:
    raw: bytes
    limits: dict[str, Any]


@dataclass(frozen=True)
class DataView:
    content: bytes
    format: str
    kind: str
    source_sha256: str
    total_rows: int | None
    rows: int | None
    columns: tuple[str, ...]
    complete: bool

    def metadata(self) -> dict[str, Any]:
        return {"format": self.format, "kind": self.kind, "source_sha256": self.source_sha256,
            "sha256": hashlib.sha256(self.content).hexdigest(), "size_bytes": len(self.content),
            "total_rows": self.total_rows, "rows": self.rows, "columns": list(self.columns), "complete": self.complete}


class DataLoader(Protocol):
    def load(self, ref: dict[str, Any], schema: dict[str, Any], context: DataContext) -> DataView: ...


class PublicDataLoader:
    def load(self, ref: dict[str, Any], schema: dict[str, Any], context: DataContext) -> DataView:
        raw, limits = context.raw, context.limits
        if ref["format"] == "csv":
            names = [column["name"] for column in schema["columns"]]
            records = list(csv.DictReader(StringIO(raw.decode()), strict=True))
            columns = [name for name in names if "columns" not in limits or name in limits["columns"]][:limits["max_columns"]]
            selected = records[:limits["max_rows"]]
            complete = len(selected) == len(records) and columns == names
            if limits["mode"] != "summary" and complete and len(raw) <= limits["max_bytes"]:
                return DataView(raw, "csv", "full", ref["sha256"], len(records), len(records), tuple(names), True)
            if limits["mode"] == "full":
                raise RunError("data_view_limit", "validation", "Full CSV exceeds its permitted modeling view.")
            if limits["mode"] == "summary" or not columns:
                content = json.dumps({"format": "csv", "total_rows": len(records), "columns": columns}).encode()
                return DataView(content, "json", "summary", ref["sha256"], len(records), 0, tuple(columns), False)
            stream = StringIO()
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            chunks = [stream.getvalue().encode()]
            size = len(chunks[0])
            if size > limits["max_bytes"]:
                raise RunError("data_view_limit", "validation", "CSV header exceeds its permitted modeling view.")
            for row in selected:
                stream.seek(0)
                stream.truncate(0)
                writer.writerow({name: row[name] for name in columns})
                chunk = stream.getvalue().encode()
                if size + len(chunk) > limits["max_bytes"]:
                    break
                chunks.append(chunk)
                size += len(chunk)
            return DataView(b"".join(chunks), "csv", "rows", ref["sha256"], len(records), len(chunks) - 1, tuple(columns), False)
        value = parse_json(raw)
        keys = list(value)
        permitted = [key for key in keys if "columns" not in limits or key in limits["columns"]][:limits["max_columns"]]
        if limits["mode"] != "summary" and permitted == keys and len(raw) <= limits["max_bytes"]:
            return DataView(raw, "json", "full", ref["sha256"], None, None, tuple(keys), True)
        if limits["mode"] == "full":
            raise RunError("data_view_limit", "validation", "Full JSON exceeds its permitted modeling view.")
        content = json.dumps({"format": "json", "total_keys": len(keys), "keys": permitted}).encode()
        return DataView(content, "json", "summary", ref["sha256"], None, None, tuple(permitted), False)


class PublicDataFactory:
    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.2.0", "plugin_id": "llm4om.data_loaders.public", "kind": "data_loader",
            "plugin_version": "0.1.0", "contract_range": ">=0.2.0,<0.3.0", "display_name": "Public CSV/JSON",
            "description": "Validate original public bytes and expose bounded full, row or schema-summary views.",
            "capabilities": {"problem_types": ["lp", "milp"], "input_artifact_kinds": ["public_data"],
                "output_artifact_kinds": ["data_view"], "data_loader_profile": "public_bytes/0.1.0",
                "data_formats": ["csv", "json"], "view_kinds": ["full", "rows", "summary"]},
            "config_schema": {"type": "object", "additionalProperties": False}, "dependencies": {"python": []}, "source": None}

    def create(self, config: dict[str, Any]) -> PublicDataLoader:
        return PublicDataLoader()


@dataclass(frozen=True)
class ResolvedDataLoader:
    instance: DataLoader
    binding: dict[str, Any]
    limits: dict[str, Any]

    def load(self, raw: bytes, ref: dict[str, Any]) -> DataView:
        from llm4om.plugins import _quiet, _exception_details
        validate_data(raw, ref)
        source_hash = hashlib.sha256(raw).hexdigest()
        if ref.get("sha256") and ref["sha256"] != source_hash:
            raise RunError("data_hash_mismatch", "validation", "Public data do not match the declared original SHA-256.")
        caps = self.binding["manifest"]["capabilities"]
        if ref["format"] not in caps["data_formats"]:
            raise RunError("capability_mismatch", "validation", "Loader cannot read the declared public data format.")
        public_ref = {"data_id": ref["data_id"], "format": ref["format"],
            "sha256": source_hash, "size_bytes": len(raw)}
        try:
            with _quiet():
                view = self.instance.load(deepcopy(public_ref), deepcopy(ref["schema"]), DataContext(raw, deepcopy(self.limits)))
                if (not isinstance(view, DataView) or type(view.content) is not bytes or type(view.complete) is not bool
                        or view.source_sha256 != public_ref["sha256"] or view.kind not in caps["view_kinds"]
                        or view.format not in {"csv", "json"} or len(view.content) > self.limits["max_bytes"]
                        or len(view.columns) > self.limits["max_columns"]
                        or (view.rows is not None and (type(view.rows) is not int or not 0 <= view.rows <= self.limits["max_rows"]))
                        or (view.complete and (view.content != raw or view.kind != "full"))):
                    raise ValueError("Invalid bounded DataView.")
                view.content.decode("utf-8")
                parse_json(json.dumps(view.metadata(), allow_nan=False).encode())
                _validate_view(view, raw, ref, self.limits)
        except RunError as error:
            code = "data_view_limit" if error.code == "data_view_limit" else "invalid_data_view"
            raise RunError(code, "validation", "Public data could not produce its permitted modeling view.",
                           details=_exception_details(error)) from error
        except (Exception, SystemExit) as error:
            raise RunError("invalid_data_view", "validation", "Loader returned an invalid or excessive public view.", details=_exception_details(error)) from error
        return view


def _validate_view(view: DataView, raw: bytes, ref: dict[str, Any], limits: dict[str, Any]) -> None:
    if type(view.columns) is not tuple or any(type(name) is not str for name in view.columns) or len(set(view.columns)) != len(view.columns):
        raise ValueError("Invalid view columns.")
    if limits["mode"] == "full" and not view.complete:
        raise ValueError("A full exposure needs unchanged complete original bytes.")
    if view.kind == "full" and (not view.complete or view.format != ref["format"]):
        raise ValueError("Full view metadata must match the original representation.")
    if ref["format"] == "csv":
        source_rows = list(csv.DictReader(StringIO(raw.decode()), strict=True))
        source_names = [column["name"] for column in ref["schema"]["columns"]]
        if type(view.total_rows) is not int or view.total_rows != len(source_rows):
            raise ValueError("View total rows differ from original data.")
        if view.kind != "summary":
            if view.format != "csv":
                raise ValueError("CSV row views require CSV content.")
            reader = csv.DictReader(StringIO(view.content.decode()), strict=True)
            rows = list(reader)
            if reader.fieldnames != list(view.columns) or type(view.rows) is not int or len(rows) != view.rows:
                raise ValueError("Reported view rows or columns differ from actual content.")
            selected_schema = {"columns": [next(column for column in ref["schema"]["columns"] if column["name"] == name)
                for name in view.columns], "unique_by": []}
            validate_data(view.content, {"format": "csv", "schema": selected_schema})
            original = Counter(tuple(row[name] for name in view.columns) for row in source_rows)
            actual = Counter(tuple(row[name] for name in view.columns) for row in rows)
            if actual - original:
                raise ValueError("A row view must preserve original cell values and multiplicity.")
        else:
            if view.rows != 0 or view.format != "json" or parse_json(view.content) != {
                    "format": "csv", "total_rows": len(source_rows), "columns": list(view.columns)}:
                raise ValueError("CSV schema summary differs from its declared exposure.")
    else:
        source_names = list(parse_json(raw))
        if view.total_rows is not None or view.rows is not None or view.kind == "rows":
            raise ValueError("The object JSON profile supports full or schema-summary exposure.")
        if view.kind == "summary" and (view.format != "json" or parse_json(view.content) != {
                "format": "json", "total_keys": len(source_names), "keys": list(view.columns)}):
            raise ValueError("JSON schema summary differs from its declared exposure.")
    allowed = set(source_names) & set(limits.get("columns", source_names))
    if not set(view.columns) <= allowed or (view.complete and list(view.columns) != source_names):
        raise ValueError("View includes undeclared or incomplete columns.")


def resolve_data_loader(settings: dict[str, Any], *, inventory: dict[Any, Any] | None = None,
                        expected: dict[str, Any] | None = None) -> ResolvedDataLoader:
    from llm4om.plugins import resolve_configured_plugin
    try:
        jsonschema.Draft202012Validator(VIEW_SCHEMA).validate(settings.get("data_view", {}))
    except jsonschema.ValidationError as error:
        raise RunError("invalid_config", "admission", "Invalid public data exposure limits.") from error
    selection = settings.get("data_loader", {"plugin_id": "llm4om.data_loaders.public", "config": {}})
    instance, binding = resolve_configured_plugin("data_loader", selection, inventory=inventory, expected=expected)
    if not callable(getattr(instance, "load", None)):
        raise RunError("invalid_plugin_manifest", "admission", "Factory does not implement the declared DataLoader profile.")
    return ResolvedDataLoader(instance, binding, {**DEFAULT_LIMITS, **settings.get("data_view", {})})
