"""Change the actual admitted CSV view without changing original cell values."""

import csv
from dataclasses import replace
from io import StringIO
from typing import Any

from llm4om.data_loaders import DataContext, DataView, PublicDataFactory, PublicDataLoader


class FixtureLoader:
    def __init__(self, reverse_columns: bool) -> None:
        self.reverse_columns = reverse_columns

    def load(self, ref: dict[str, Any], schema: dict[str, Any], context: DataContext) -> DataView:
        if "path" in ref or "namespace" in ref or "oracle" in ref:
            raise ValueError("Only admitted public bytes are expected.")
        view = PublicDataLoader().load(ref, schema, context)
        if view.format != "csv" or not self.reverse_columns:
            return view
        columns = tuple(reversed(view.columns))
        stream = StringIO()
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(csv.DictReader(StringIO(view.content.decode()), strict=True))
        return replace(view, content=stream.getvalue().encode(), columns=columns, kind="rows", complete=False)


class FixtureFactory:
    @staticmethod
    def describe() -> dict[str, Any]:
        manifest = PublicDataFactory().describe()
        manifest.update(plugin_id="llm4om.examples.reversed_columns", display_name="Reversed CSV view",
            description="A separate installed adapter reverses exposed columns, preserving original cells and raw binding.")
        manifest["config_schema"] = {"type": "object", "additionalProperties": False,
            "required": ["reverse_columns"], "properties": {"reverse_columns": {"type": "boolean"}}}
        return manifest

    @staticmethod
    def create(config: dict[str, Any]) -> FixtureLoader:
        return FixtureLoader(config["reverse_columns"])
