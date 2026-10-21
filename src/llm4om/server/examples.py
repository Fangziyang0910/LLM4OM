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


def cases(dataset_id: str, offset: int = 0, limit: int = 20) -> dict[str, Any]:
    """One page of problems. The bundled problems carry all numbers in their descriptions."""
    selected = _cases(dataset_id)[offset:offset + limit]
    return {"total": len(_cases(dataset_id)), "cases": [
        {"id": case["case_id"], "sample_id": case["sample_id"], "subset": case["subset"], "description": case["description"]}
        for case in selected]}
