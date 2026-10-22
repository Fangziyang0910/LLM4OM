"""Describe attached data without putting its rows or array values in an LLM prompt."""

import csv
import io
import json
from typing import Any


def schema(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "properties": {key: schema(item) for key, item in value.items()}}
    if isinstance(value, list):
        # Describe every distinct shape, including ragged arrays and heterogeneous records.
        shapes = {json.dumps(schema(item), sort_keys=True) for item in value}
        return {"type": "array", "length": len(value), "items": [json.loads(item) for item in sorted(shapes)]}
    return {"type": {type(None): "null", bool: "boolean", int: "integer", float: "number", str: "string"}[type(value)]}


def describe_data(data: dict[str, str]) -> str:
    files = {}
    for name, content in data.items():
        if name.lower().endswith(".json"):
            files[name] = schema(json.loads(content))
        elif name.lower().endswith(".csv"):
            rows = csv.reader(io.StringIO(content))
            header = next(rows, [])
            if not header or len(set(header)) != len(header) or any(not key for key in header):
                raise ValueError(f"{name}: CSV requires a nonempty, unique header for each column.")
            count = 0
            for row in rows:
                if not row:
                    continue
                if len(row) != len(header):
                    raise ValueError(f"{name}: CSV line {rows.line_num} has {len(row)} fields; expected {len(header)}.")
                count += 1
            files[name] = {"type": "csv", "columns": header, "rows": count,
                           "note": "CSV cells are strings; convert numeric columns when loading."}
        else:
            raise ValueError(f"BIND expects JSON or CSV data; unsupported attachment: {name}.")
    return json.dumps(files, ensure_ascii=False, indent=2)
