"""Deterministic compiler selection independent from Method and Solver identity."""

import ast
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import version, PackageNotFoundError
from typing import Any, Protocol, cast
import json
import jsonschema
from llm4om.contracts import RunError
from llm4om.linear import CompiledCode, compile_ir


class Compiler(Protocol):
    def compile(self, ir: dict[str, Any], target_backend: str) -> CompiledCode: ...


class LPIRPyomoCompiler:
    def compile(self, ir: dict[str, Any], target_backend: str) -> CompiledCode:
        from llm4om.plugins import discover_plugins
        backend = discover_plugins().get(("model_backend", target_backend))
        if backend is None or backend.manifest["capabilities"]["handle_profile"] != "pyomo_linear/0.1.0":
            raise RunError("capability_mismatch", "code", "This compiler requires the Pyomo Backend.")
        return compile_ir(ir)


class LPIRPyomoFactory:
    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.2.0", "plugin_id": "llm4om.compilers.lp_ir_to_pyomo", "kind": "compiler",
            "plugin_version": "0.1.0", "contract_range": ">=0.2.0,<0.3.0", "display_name": "Grounded LPIR to Pyomo",
            "description": "Deterministic grounded LP/MILP compilation with explicit decision symbols.",
            "capabilities": {"compiler_profile": "grounded_lpir_pyomo/0.1.0", "deterministic": True,
                "problem_types": ["lp", "milp"], "input_artifact_kinds": ["grounded_lpir"],
                "output_artifact_kinds": ["python_factory"], "ir_schema_versions": ["0.1.0"],
                "model_backends": ["llm4om.model_backends.pyomo_factory"]},
            "config_schema": {"type": "object", "additionalProperties": False}, "dependencies": {"python": []}, "source": None}

    def create(self, config: dict[str, Any]) -> Compiler:
        if config:
            raise RunError("invalid_config", "admission", "The built-in compiler has no configuration options.")
        return LPIRPyomoCompiler()


@dataclass(frozen=True)
class ResolvedCompiler:
    compiler: Compiler
    binding: dict[str, Any]
    target_backend: str

    def compile(self, ir: dict[str, Any]) -> CompiledCode:
        from llm4om.plugins import _quiet, _exception_details
        canonical = compile_ir(ir)
        if ir["problem_type"] not in self.binding["manifest"]["capabilities"]["problem_types"]:
            raise RunError("capability_mismatch", "code", "Compiler does not support the actual LPIR problem type.")
        try:
            with _quiet():
                result = self.compiler.compile(deepcopy(ir), self.target_backend)
            if not isinstance(result, CompiledCode) or not isinstance(result.source, str) or not result.source.strip() or len(result.source.encode()) > 8 * 1024 * 1024:
                raise ValueError("Compiler must return bounded source and explicit symbols.")
            ast.parse(result.source)
            symbols = result.symbol_map
            if (not isinstance(symbols, dict) or set(symbols) != {"variables", "constraints", "internal_variables"}
                    or set(symbols["variables"]) != set(canonical.symbol_map["variables"])
                    or set(symbols["constraints"]) != set(canonical.symbol_map["constraints"])
                    or sorted(symbols["variables"].values()) != list(range(len(ir["variables"])))
                    or any(type(value) is not int for value in symbols["variables"].values())
                    or sorted(symbols["constraints"].values()) != list(range(1, len(ir["constraints"]) + 1))
                    or any(type(value) is not int for value in symbols["constraints"].values())
                    or symbols["internal_variables"] != canonical.symbol_map["internal_variables"]):
                raise ValueError("Compiler symbols do not describe the admitted LPIR variables/rows.")
            json.dumps(symbols, allow_nan=False)
            return result
        except RunError as error:
            raise RunError(error.code, error.stage, "Registered compiler rejected the model.", details=_exception_details(error)) from error
        except (Exception, SystemExit) as error:
            raise RunError("compilation_error", "code", "Registered compiler returned invalid output or failed.", details=_exception_details(error)) from error


def resolve_compiler(selection: dict[str, Any], target_backend: str, *,
                     inventory: dict[Any, Any] | None = None, expected: dict[str, Any] | None = None) -> ResolvedCompiler:
    from llm4om.plugins import discover_plugins, _quiet, _exception_details
    inventory = discover_plugins() if inventory is None else inventory
    plugin = inventory.get(("compiler", selection["plugin_id"]))
    if plugin is None:
        raise RunError("checkpoint_incompatible" if expected else "unknown_plugin", "admission", "Requested compiler is not installed.")
    config = selection.get("config", {})
    try:
        jsonschema.Draft202012Validator(plugin.manifest["config_schema"]).validate(config)
    except (jsonschema.ValidationError, jsonschema.exceptions.RefResolutionError, RecursionError) as error:
        raise RunError("invalid_config", "admission", "Compiler config does not match its self-contained Manifest.") from error
    target = inventory.get(("model_backend", target_backend))
    declared_profiles = {inventory[("model_backend", key)].manifest["capabilities"]["handle_profile"]
        for key in plugin.manifest["capabilities"]["model_backends"] if ("model_backend", key) in inventory}
    if target is None or target.manifest["capabilities"]["handle_profile"] not in declared_profiles:
        raise RunError("capability_mismatch", "admission", "Compiler cannot target the selected Backend.")
    packages = {}
    for name in plugin.manifest["dependencies"].get("python", []):
        try:
            packages[name] = version(name)
        except PackageNotFoundError as error:
            raise RunError("dependency_missing", "admission", "A declared compiler dependency is not installed.") from error
    binding = {"manifest": plugin.manifest, "origin": plugin.origin, "config": deepcopy(config), "packages": packages}
    if expected is not None and binding != expected:
        raise RunError("checkpoint_incompatible", "admission", "Compiler package, Manifest or config differs from the saved identity.")
    try:
        with _quiet():
            instance = plugin.factory.create(deepcopy(config))
        if not callable(getattr(instance, "compile", None)):
            raise TypeError("Compiler requires compile(ir,target_backend).")
    except (Exception, SystemExit) as error:
        raise RunError("invalid_plugin_manifest", "admission", "Cannot construct the declared compiler.", details=_exception_details(error)) from error
    return ResolvedCompiler(cast(Compiler, instance), binding, target_backend)


def compiler_identity(binding: dict[str, Any]) -> dict[str, Any]:
    """Compare executable contents across host/Worker installation metadata."""
    origin = binding["origin"]
    return {"manifest": binding["manifest"], "config": binding["config"], "packages": binding["packages"],
            "origin": {key: origin[key] for key in ("kind", "value", "distribution", "distribution_version", "content_sha256") if key in origin}}
