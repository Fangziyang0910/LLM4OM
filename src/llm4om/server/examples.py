"""Bundled public benchmark problems for browsing and trying out (no evaluation)."""

import json
from functools import cache
from importlib.resources import files
from typing import Any

ROOT = files("llm4om.server").joinpath("examples_data")


@cache
def datasets() -> list[dict[str, Any]]:
    catalog = json.loads(ROOT.joinpath("catalog.json").read_text("utf-8"))
    return [{"id": item["dataset_id"], "title": item["title"], "description": item["description"],
             "count": item["N_cases"], "license": item["license"], "source_url": item["source_url"]}
            for item in catalog["benchmarks"]]


@cache
def _cases(dataset_id: str) -> list[dict[str, Any]]:
    if dataset_id not in {item["id"] for item in datasets()}:
        raise KeyError(dataset_id)
    return json.loads(ROOT.joinpath(dataset_id + ".json").read_text("utf-8"))["cases"]


def cases(dataset_id: str, offset: int = 0, limit: int = 20, q: str = "") -> dict[str, Any]:
    """One page of problems, optionally filtered by substring query `q`."""
    all_cases = _cases(dataset_id)
    query = q.strip().lower()
    if query:
        tokens = query.split()
        filtered = [
            case for case in all_cases
            if all(tok in f"{case['sample_id']} {case['subset']} {case['description']}".lower() for tok in tokens)
        ]
    else:
        filtered = all_cases
    selected = filtered[offset:offset + limit]
    return {"total": len(filtered), "cases": [
        {"id": case["case_id"], "sample_id": case["sample_id"], "subset": case["subset"], "description": case["description"]}
        for case in selected]}
