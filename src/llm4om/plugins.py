"""Discover trusted factories through the common installed entry-point seam."""

from dataclasses import dataclass
from copy import deepcopy
import asyncio
import json
import hashlib
import re
import traceback
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from importlib.metadata import entry_points
from importlib.metadata import version, PackageNotFoundError
from typing import Any, Iterator
from pathlib import Path
import jsonschema

from llm4om.control import _supervise
from llm4om.methods import DirectFactory, MethodContext, MethodOutcome
from llm4om.optimus import OptimusFactory
from llm4om.contracts import RunError, parse_json, reject_additional_refs


@dataclass(frozen=True)
class Plugin:
    manifest: dict[str, Any]
    origin: dict[str, Any]
    factory: Any


@dataclass(frozen=True)
class MethodPlugin(Plugin):
    def resolve(self, config: dict[str, Any]) -> "MethodPlugin":
        return MethodPlugin(_manifest(self.factory, config), self.origin, self.factory)

    def run(self, config: dict[str, Any], problem: dict[str, Any], context: MethodContext,
            *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if checkpoint is not None and not self.manifest["capabilities"].get("supports_checkpoint"):
            raise RunError("checkpoint_unsupported", "admission", "Method has no internal checkpoint contract.")
        async def invoke() -> MethodOutcome:
            try:
                with _quiet():
                    method = self.factory.create(config)
            except (Exception, SystemExit) as error:
                code = "dependency_missing" if isinstance(error, (ImportError, OSError)) else "invalid_config"
                raise RunError(code, "admission", "Cannot construct the method with this configuration and environment.",
                               details={"plugin_id": self.manifest["plugin_id"], **_exception_details(error)}) from error
            try:
                async def method_task() -> MethodOutcome:
                    try:
                        result: MethodOutcome = await method.run(problem, context, checkpoint=deepcopy(checkpoint))
                        return result
                    except SystemExit as error:
                        raise RunError("method_error", "formulation", "The installed modeling method failed.",
                                       details=_exception_details(error)) from error
                with _quiet():
                    outcome = await _supervise(method_task(), context.cancellation)
                if not isinstance(outcome, MethodOutcome):
                    raise TypeError("Expected MethodOutcome.")
                return outcome
            except RunError as error:
                raise RunError(error.code, error.stage, "The modeling method or its public resource failed.", details=error.details) from error
            except (Exception, SystemExit) as error:
                details = {"plugin_id": self.manifest["plugin_id"], **_exception_details(error)}
                raise RunError("method_error", "formulation", "The installed modeling method failed.", details=details) from error
        # A sync SDK can be called from an existing event loop.
        with ThreadPoolExecutor(max_workers=1) as worker:
            return worker.submit(asyncio.run, invoke()).result()


def discover_methods() -> dict[tuple[str, str], MethodPlugin]:
    return {key: plugin for key, plugin in discover_plugins().items() if isinstance(plugin, MethodPlugin)}


def resolve_configured_plugin(kind: str, selection: dict[str, Any], *,
        inventory: dict[tuple[str, str], Plugin] | None = None,
        expected: dict[str, Any] | None = None, check_dependencies: bool = True) -> tuple[Any, dict[str, Any]]:
    inventory = discover_plugins() if inventory is None else inventory
    plugin = inventory.get((kind, selection["plugin_id"]))
    if plugin is None:
        raise RunError("checkpoint_incompatible" if expected else "unknown_plugin", "admission", "Requested execution plugin is not installed.")
    config = selection.get("config", {})
    try:
        jsonschema.Draft202012Validator(plugin.manifest["config_schema"]).validate(config)
    except (jsonschema.ValidationError, jsonschema.exceptions.RefResolutionError, RecursionError) as error:
        raise RunError("invalid_config", "admission", "Execution plugin config does not match its Manifest.") from error
    packages = {}
    for name in plugin.manifest["dependencies"].get("python", []) if check_dependencies else []:
        try:
            packages[name] = version(name)
        except PackageNotFoundError as error:
            raise RunError("dependency_missing", "admission", "A declared execution dependency is not installed.") from error
    binding = {"manifest": plugin.manifest, "origin": plugin.origin, "config": deepcopy(config), "packages": packages}
    if expected is not None and binding != expected:
        raise RunError("checkpoint_incompatible", "admission", "Execution plugin Manifest/package/config differs from the saved identity.")
    try:
        with _quiet():
            instance = plugin.factory.create(deepcopy(config))
    except (Exception, SystemExit) as error:
        raise RunError("invalid_plugin_manifest", "admission", "Cannot construct the declared execution plugin.", details=_exception_details(error)) from error
    return instance, binding


def discover_plugins() -> dict[tuple[str, str], Plugin]:
    from llm4om.coe import CoEFactory
    from llm4om.feedback_repair import FeedbackRepairFactory
    from llm4om.providers import MockFactory, OpenAICompatibleFactory, AnthropicFactory
    from llm4om.task_plugins import builtin_factories
    from llm4om.compilers import LPIRPyomoFactory
    from llm4om.backends import PyomoBackendFactory, GurobiBackendFactory
    from llm4om.solvers import HighsSolverFactory, GurobiSolverFactory
    from llm4om.data_loaders import PublicDataFactory
    from llm4om.assisted import AssistedFactory
    plugins: dict[tuple[str, str], Plugin] = {}
    for builtin in (DirectFactory(), OptimusFactory(), CoEFactory(), FeedbackRepairFactory(), AssistedFactory(),
                    MockFactory(), OpenAICompatibleFactory(), AnthropicFactory(), *builtin_factories(), LPIRPyomoFactory(),
                    PyomoBackendFactory(), GurobiBackendFactory(), HighsSolverFactory(), GurobiSolverFactory(), PublicDataFactory()):
        manifest = _manifest(builtin)
        plugin_type = MethodPlugin if manifest["kind"] == "method" else Plugin
        plugins[(manifest["kind"], manifest["plugin_id"])] = plugin_type(manifest, {"kind": "builtin"}, builtin)
    for entry in sorted(entry_points(group="llm4om.plugins"), key=lambda item: (item.name, item.value)):
        try:
            with _quiet():
                factory = entry.load()
        except (Exception, SystemExit) as error:
            raise RunError("plugin_load_error", "admission", "Cannot import an installed plugin factory.",
                           details={"entry_point": entry.name, "value": entry.value, **_exception_details(error)}) from error
        try:
            manifest = _manifest(factory)
        except RunError as error:
            if error.details is not None:
                error.details.update(entry_point=entry.name, value=entry.value)
            raise
        try:
            digest = hashlib.sha256()
            content_digest = hashlib.sha256()
            if entry.dist is not None:
                for file in sorted(entry.dist.files or [], key=str):
                    if file.suffix == ".pyc":
                        continue
                    digest.update(str(file).encode())
                    portable = not any(part.endswith(".dist-info") for part in file.parts)
                    if portable:
                        content_digest.update(str(file).encode())
                    with Path(str(entry.dist.locate_file(file))).open("rb") as stream:
                        for chunk in iter(lambda: stream.read(65536), b""):
                            digest.update(chunk)
                            if portable:
                                content_digest.update(chunk)
            origin = {"kind": "installed", "entry_point": entry.name, "value": entry.value,
                  "distribution": entry.dist.name if entry.dist else None,
                  "distribution_version": entry.dist.version if entry.dist else None,
                  "package_sha256": digest.hexdigest() if entry.dist else None,
                  "content_sha256": content_digest.hexdigest() if entry.dist else None}
        except (Exception, SystemExit) as error:
            raise RunError("plugin_load_error", "admission", "Cannot verify installed plugin distribution files.",
                           details={"entry_point": entry.name, **_exception_details(error)}) from error
        key = (manifest["kind"], manifest["plugin_id"])
        if key in plugins:
            raise RunError("duplicate_plugin", "admission", "Two active plugins share a registry key.")
        plugin_type = MethodPlugin if manifest["kind"] == "method" else Plugin
        plugins[key] = plugin_type(manifest, origin, factory)
    return plugins


def _manifest(factory: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    stable_version = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    text = {"type": "string", "minLength": 1}
    strings = {"type": "array", "items": text, "uniqueItems": True}
    capabilities = {name: strings for name in ("problem_types", "input_artifact_kinds", "output_artifact_kinds",
                    "formulation_representations", "code_representations", "model_backends", "solvers", "llm_features",
                    "execution_modes", "oracle_requirements")}
    capabilities.update(method_profile=text, supports_checkpoint={"type": "boolean"}, human_assisted={"type": "boolean"}, supports_clarification={"type": "boolean"}, cancellation={"const": "cooperative/0.1.0"})
    capabilities.update(provider_profile={"enum": ["http_text/0.1.0", "mock_text/0.1.0"]})
    capabilities.update(usage_semantics=text)
    capabilities.update(data_loader_profile={"const": "public_bytes/0.1.0"},
        data_formats={"type": "array", "items": {"enum": ["csv", "json"]}, "minItems": 1, "uniqueItems": True},
        view_kinds={"type": "array", "items": {"enum": ["full", "rows", "summary"]}, "minItems": 1, "uniqueItems": True},
        data_access={"enum": ["full", "views"]})
    capabilities.update(task_profile={"const": "frozen_task/0.1.0"}, evaluator_profile={"const": "frozen_evaluation/0.1.0"},
        protocol_ids=strings, default_evaluator_id=text, oracle_separation={"const": "separate_public_private/0.1.0"}, evidence_levels=strings)
    capabilities.update(compiler_profile={"const": "grounded_lpir_pyomo/0.1.0"}, deterministic={"const": True}, ir_schema_versions=strings)
    handle_profiles: dict[str, Any] = {"type": "array", "items": {"enum": ["pyomo_linear/0.1.0", "gurobipy_linear/0.1.0"]}, "minItems": 1, "uniqueItems": True}
    capabilities.update(backend_profile={"const": "model_handle/0.1.0"}, handle_profile=handle_profiles["items"],
        solver_profile={"const": "model_handle/0.1.0"}, handle_profiles=handle_profiles,
        result_profile={"enum": ["highs_api/0.1.0", "gurobi_api/0.1.0"]})
    fields = {"schema_version": {"const": "0.2.0"}, "plugin_id": {**text,
              "pattern": r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+$"}, "kind": {"enum": ["method", "llm_provider", "task_adapter", "evaluator", "compiler", "model_backend", "solver_backend", "data_loader"]},
              "plugin_version": {"type": "string", "pattern": f"^{stable_version}$", "maxLength": 128},
              "contract_range": {**text, "maxLength": 256}, "display_name": text, "description": text,
              "capabilities": {"type": "object", "properties": capabilities,
                               "required": ["problem_types", "input_artifact_kinds", "output_artifact_kinds"],
                               "additionalProperties": False},
              "config_schema": {"type": "object"}, "options_schema": {"type": "object"},
              "dependencies": {"type": "object", "properties": {"python": strings}, "additionalProperties": False},
              "source": {"type": ["object", "null"]}}
    try:
        with _quiet():
            value = factory.describe()
            if config is not None and callable(getattr(factory, "resolve_capabilities", None)):
                value["capabilities"] = factory.resolve_capabilities(config)
            manifest = parse_json(json.dumps(value, allow_nan=False).encode())
        jsonschema.Draft202012Validator({"type": "object", "properties": fields,
            "required": [name for name in fields if name != "options_schema"], "additionalProperties": False}).validate(manifest)
        jsonschema.Draft202012Validator.check_schema(manifest["config_schema"])
        _local_schema(manifest["config_schema"])
        reject_additional_refs(manifest["source"])
        if "options_schema" in manifest:
            jsonschema.Draft202012Validator.check_schema(manifest["options_schema"])
            _local_schema(manifest["options_schema"])
        if not callable(factory.create):
            raise TypeError("Factory must create a plugin.")
        if manifest["kind"] == "data_loader":
            caps = manifest["capabilities"]
            if (caps.get("data_loader_profile") != "public_bytes/0.1.0" or not caps.get("data_formats")
                    or not caps.get("view_kinds") or caps["input_artifact_kinds"] != ["public_data"]
                    or caps["output_artifact_kinds"] != ["data_view"]):
                raise ValueError("Unsupported DataLoader profile.")
        if manifest["kind"] == "model_backend":
            caps = manifest["capabilities"]
            if (caps.get("backend_profile") != "model_handle/0.1.0" or not caps.get("handle_profile")
                    or caps.get("output_artifact_kinds") != ["model_handle"]
                    or not caps.get("input_artifact_kinds")):
                raise ValueError("Unsupported Backend profile.")
        if manifest["kind"] == "solver_backend":
            caps = manifest["capabilities"]
            if (caps.get("solver_profile") != "model_handle/0.1.0" or not caps.get("handle_profiles")
                    or not caps.get("result_profile") or "options_schema" not in manifest
                    or caps.get("input_artifact_kinds") != ["model_handle"] or caps.get("output_artifact_kinds") != ["solve_result"]):
                raise ValueError("Unsupported Solver profile.")
        if manifest["kind"] == "compiler":
            caps = manifest["capabilities"]
            if (caps.get("compiler_profile") != "grounded_lpir_pyomo/0.1.0" or caps.get("deterministic") is not True
                    or caps.get("ir_schema_versions") != ["0.1.0"]
                    or caps.get("input_artifact_kinds") != ["grounded_lpir"] or caps.get("output_artifact_kinds") != ["python_factory"]
                    or caps.get("model_backends") != ["llm4om.model_backends.pyomo_factory"]):
                raise ValueError("Unsupported compiler profile.")
        if manifest["kind"] in {"task_adapter", "evaluator"}:
            caps = manifest["capabilities"]
            if not caps.get("protocol_ids"):
                raise ValueError("Frozen tasks and evaluation require explicit protocols.")
            if manifest["kind"] == "task_adapter" and (
                caps.get("task_profile") != "frozen_task/0.1.0" or not caps.get("default_evaluator_id")
                or caps.get("oracle_separation") != "separate_public_private/0.1.0"):
                raise ValueError("Unsupported Task profile.")
            if manifest["kind"] == "evaluator" and (caps.get("evaluator_profile") != "frozen_evaluation/0.1.0"
                    or not caps.get("evidence_levels")):
                raise ValueError("Unsupported Evaluator profile.")
        if manifest["kind"] == "llm_provider":
            from llm4om.providers import HTTPTextFactory, MockFactory, HTTPTextProvider
            profile = manifest["capabilities"].get("provider_profile")
            if isinstance(factory, HTTPTextFactory):
                if (profile != "http_text/0.1.0" or not issubclass(factory.provider_type, HTTPTextProvider)
                        or factory.provider_type.plugin_id != manifest["plugin_id"]
                        or factory.provider_type._request is HTTPTextProvider._request
                        or factory.provider_type.decode_reply is HTTPTextProvider.decode_reply):
                    raise ValueError("Unsupported HTTP Provider profile.")
            elif not isinstance(factory, MockFactory) or profile != "mock_text/0.1.0":
                raise ValueError("Unsupported Provider factory.")
            if not set(manifest["capabilities"].get("llm_features", [])) <= {"text"}:
                raise ValueError("This Provider profile supports only text.")
    except (Exception, SystemExit) as error:
        raise RunError("invalid_plugin_manifest", "admission", "Plugin Manifest or factory does not match a supported profile.",
                       details=_exception_details(error)) from error
    interval = re.fullmatch(f">=(?P<lower>{stable_version}),\\s*<(?P<upper>{stable_version})", manifest["contract_range"])
    if interval is None or not (tuple(map(int, interval["lower"].split("."))) <= (0, 2, 0) < tuple(map(int, interval["upper"].split(".")))):
        raise RunError("incompatible_contract", "admission", "Plugin contract_range does not include core 0.2.0.")
    return manifest


def _local_schema(value: Any, resolver: jsonschema.RefResolver | None = None) -> None:
    if resolver is None:
        resolver = jsonschema.RefResolver.from_schema(value)
    if isinstance(value, dict):
        if "$id" in value or any(key in value and not str(value[key]).startswith("#") for key in ("$ref", "$dynamicRef")):
            raise ValueError("This profile requires self-contained configuration schemas.")
        for key in ("$ref", "$dynamicRef"):
            if key in value and not isinstance(resolver.resolve(value[key])[1], (dict, bool)):
                raise ValueError("A configuration reference must resolve to a local schema.")
        for child in value.values():
            _local_schema(child, resolver)
    elif isinstance(value, list):
        for child in value:
            _local_schema(child, resolver)


@contextmanager
def _quiet() -> Iterator[None]:
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
        yield


def _exception_details(error: BaseException) -> dict[str, Any]:
    return {"exception_type": type(error).__name__,
            "frames": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                       for frame in traceback.extract_tb(error.__traceback__)]}
