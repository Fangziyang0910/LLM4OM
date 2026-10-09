"""A trusted engineering method that exposes a visible objective-offset variant."""

import json
from importlib.resources import files
from typing import Any

from llm4om.methods import MethodContext, MethodOutcome, ModelProposal


class FixtureMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.offset = config["objective_offset"]

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        response = await context.llm.complete({"messages": [{"role": "user", "content": problem["description"]}]})
        value = json.loads(response.text)
        value["structured_ir"]["objective"]["expression"]["constant"] += self.offset
        value["formulation"]["representation"]["objective"]["expression_text"] += f" + {self.offset}"
        value["artifact"]["provenance"]["method_variant"] = "engineering_objective_offset"
        return MethodOutcome("candidate_selected", "001", ModelProposal(value["artifact"], value["formulation"], value["structured_ir"]))


class FixtureFactory:
    def describe(self) -> dict[str, Any]:
        return json.loads(files(__package__).joinpath("manifest.json").read_text())

    def create(self, config: dict[str, Any]) -> FixtureMethod:
        return FixtureMethod(config)


plugin = FixtureFactory()
