"""Engineering source-format variant; preserves the canonical mathematical model."""

import ast
from typing import Any
from llm4om.compilers import LPIRPyomoFactory, LPIRPyomoCompiler
from llm4om.linear import CompiledCode


class FixtureCompiler:
    def __init__(self, marker: str) -> None:
        self.marker = marker

    def compile(self, ir: dict[str, Any], target_backend: str) -> CompiledCode:
        code = LPIRPyomoCompiler().compile(ir, target_backend)
        source = ast.unparse(ast.parse(code.source)) + "\nCOMPILER_MARKER = " + repr(self.marker) + "\n"
        return CompiledCode(source, code.symbol_map)


class FixtureFactory(LPIRPyomoFactory):
    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(plugin_id="llm4om.examples.ast_compiler", display_name="Independent AST source formatter",
            source={"kind": "engineering_fixture", "variant_id": "ast_source_format"},
            config_schema={"type": "object", "properties": {"marker": {"type": "string", "pattern": "^[a-zA-Z0-9_-]{1,64}$"}},
                "required": ["marker"], "additionalProperties": False})
        return manifest

    def create(self, config: dict[str, Any]) -> FixtureCompiler:
        return FixtureCompiler(config["marker"])


plugin = FixtureFactory()
