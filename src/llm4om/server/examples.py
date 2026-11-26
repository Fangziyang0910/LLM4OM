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


# Common business terms used to find the source-language problem descriptions.
_SEARCH_TERMS = {
    "运输": ("transport", "shipping", "shipment", "freight"), "物流": ("logistics", "transport", "delivery"),
    "配送": ("delivery", "routing", "distribution"), "路径": ("routing", "route", "path"),
    "排班": ("shift", "schedul"), "排程": ("schedul",), "调度": ("schedul", "dispatch"),
    "生产制造": ("produc", "manufactur"), "仓储物流": ("warehouse", "logistics", "storage"),
    "排班调度": ("shift", "schedul"), "生产": ("produc", "manufactur"), "库存": ("inventor", "stock"), "仓储": ("warehouse", "storage"),
    "选址": ("location", "locate"), "背包": ("knapsack",), "分配": ("assign", "allocat"),
}


def _alternatives(word: str) -> tuple[str, ...]:
    # Keep literal matching; Chinese users also enter the scenario names printed in the library.
    for suffix in ("问题", "案例", "优化"):
        word_without_suffix = word.removesuffix(suffix)
        if word_without_suffix in _SEARCH_TERMS:
            return (word, *_SEARCH_TERMS[word_without_suffix])
    return (word, *_SEARCH_TERMS.get(word, ()))


def cases(dataset_id: str | None = None, offset: int = 0, limit: int = 20, q: str = "") -> dict[str, Any]:
    """Search the selected collections before paginating, retaining the source for translation."""
    sources = [dataset_id] if dataset_id is not None else [item["id"] for item in datasets()]
    terms = [_alternatives(word) for word in q.casefold().split()]
    page = []
    total = 0
    for source in sources:
        for item in _cases(source):
            if terms:
                text = f"{item['sample_id']} {item['subset']} {item['description']}".casefold()
                if not all(any(word in text for word in alternatives) for alternatives in terms):
                    continue
            if offset <= total < offset + limit:
                page.append({"dataset": source, "id": item["case_id"], "sample_id": item["sample_id"],
                             "subset": item["subset"], "description": item["description"]})
            total += 1
    return {"total": total, "cases": page}


def case(dataset_id: str, case_id: str) -> dict[str, Any]:
    """Look up a bundled case without accepting client-supplied source text."""
    for item in _cases(dataset_id):
        if item["case_id"] == case_id:
            return item
    raise KeyError(case_id)
