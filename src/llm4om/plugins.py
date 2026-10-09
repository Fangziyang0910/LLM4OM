"""Discover installed method factories through the declared entry-point seam."""

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
from typing import Any, Iterator
from pathlib import Path
import jsonschema

from llm4om.control import _supervise
from llm4om.methods import DirectFactory, MethodContext, MethodOutcome
from llm4om.optimus import OptimusFactory
from llm4om.contracts import RunError, parse_json, reject_additional_refs


@dataclass(frozen=True)
class MethodPlugin:
    manifest: dict[str, Any]
    origin: dict[str, Any]
    factory: Any

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
    plugins = {}
    for builtin in (DirectFactory(), OptimusFactory()):
        manifest = _manifest(builtin)
        plugins[(manifest["kind"], manifest["plugin_id"])] = MethodPlugin(manifest, {"kind": "builtin"}, builtin)
    for entry in sorted(entry_points(group="llm4om.plugins"), key=lambda item: (item.name, item.value)):
        try:
            with _quiet():
                factory = entry.load()
        except (Exception, SystemExit) as error:
            raise RunError("plugin_load_error", "admission", "Cannot import an installed method factory.",
                           details={"entry_point": entry.name, "value": entry.value, **_exception_details(error)}) from error
        try:
            manifest = _manifest(factory)
        except RunError as error:
            if error.details is not None:
                error.details.update(entry_point=entry.name, value=entry.value)
            raise
        origin = {"kind": "installed", "entry_point": entry.name, "value": entry.value,
                  "distribution": entry.dist.name if entry.dist else None,
                  "distribution_version": entry.dist.version if entry.dist else None,
                  "package_sha256": hashlib.sha256(b"".join(
                      str(file).encode() + Path(str(entry.dist.locate_file(file))).read_bytes()
                      for file in sorted(entry.dist.files or [], key=str) if file.suffix == ".py"
                  )).hexdigest() if entry.dist else None}
        key = (manifest["kind"], manifest["plugin_id"])
        if key in plugins:
            raise RunError("duplicate_plugin", "admission", "Two active methods share a registry key.")
        plugins[key] = MethodPlugin(manifest, origin, factory)
    return plugins


def _manifest(factory: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    stable_version = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    text = {"type": "string", "minLength": 1}
    strings = {"type": "array", "items": text, "uniqueItems": True}
    capabilities = {name: strings for name in ("problem_types", "input_artifact_kinds", "output_artifact_kinds",
                    "formulation_representations", "code_representations", "model_backends", "solvers", "llm_features",
                    "execution_modes", "oracle_requirements")}
    capabilities.update(method_profile=text, supports_checkpoint={"type": "boolean"}, supports_clarification={"type": "boolean"}, cancellation={"const": "cooperative/0.1.0"})
    fields = {"schema_version": {"const": "0.2.0"}, "plugin_id": {**text,
              "pattern": r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+$"}, "kind": {"const": "method"},
              "plugin_version": {"type": "string", "pattern": f"^{stable_version}$", "maxLength": 128},
              "contract_range": {**text, "maxLength": 256}, "display_name": text, "description": text,
              "capabilities": {"type": "object", "properties": capabilities,
                               "required": ["problem_types", "input_artifact_kinds", "output_artifact_kinds"],
                               "additionalProperties": False},
              "config_schema": {"type": "object"},
              "dependencies": {"type": "object", "properties": {"python": strings}, "additionalProperties": False},
              "source": {"type": ["object", "null"]}}
    try:
        with _quiet():
            value = factory.describe()
            if config is not None and callable(getattr(factory, "resolve_capabilities", None)):
                value["capabilities"] = factory.resolve_capabilities(config)
            manifest = parse_json(json.dumps(value, allow_nan=False).encode())
        jsonschema.Draft202012Validator({"type": "object", "properties": fields,
            "required": list(fields), "additionalProperties": False}).validate(manifest)
        jsonschema.Draft202012Validator.check_schema(manifest["config_schema"])
        _local_schema(manifest["config_schema"])
        reject_additional_refs(manifest["source"])
        if not callable(factory.create):
            raise TypeError("Factory must create a method.")
    except (Exception, SystemExit) as error:
        raise RunError("invalid_plugin_manifest", "admission", "Installed method Manifest or factory does not match the current profile.",
                       details=_exception_details(error)) from error
    interval = re.fullmatch(f">=(?P<lower>{stable_version}),\\s*<(?P<upper>{stable_version})", manifest["contract_range"])
    if interval is None or not (tuple(map(int, interval["lower"].split("."))) <= (0, 2, 0) < tuple(map(int, interval["upper"].split(".")))):
        raise RunError("incompatible_contract", "admission", "Method contract_range does not include core 0.2.0.")
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
