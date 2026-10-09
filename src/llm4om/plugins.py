"""Discover installed method factories through the declared entry-point seam."""

from dataclasses import dataclass
import asyncio
import json
import re
import traceback
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from importlib.metadata import entry_points
from typing import Any, Iterator
from pathlib import Path
import jsonschema

from llm4om.methods import DirectFactory, MethodContext, MethodOutcome
from llm4om.contracts import RunError, parse_json, reject_additional_refs


@dataclass(frozen=True)
class MethodPlugin:
    manifest: dict[str, Any]
    origin: dict[str, Any]
    factory: Any

    def run(self, config: dict[str, Any], problem: dict[str, Any], context: MethodContext) -> MethodOutcome:
        async def invoke() -> MethodOutcome:
            try:
                with _quiet():
                    method = self.factory.create(config)
                    outcome = await method.run(problem, context, checkpoint=None)
                if not isinstance(outcome, MethodOutcome):
                    raise TypeError("Expected MethodOutcome.")
                return outcome
            except RunError as error:
                raise RunError(error.code, error.stage, "The modeling method or its public resource failed.") from error
            except (Exception, SystemExit) as error:
                details = {"plugin_id": self.manifest["plugin_id"], "exception_type": type(error).__name__,
                           "frames": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                                      for frame in traceback.extract_tb(error.__traceback__)]}
                raise RunError("method_error", "formulation", "The installed modeling method failed.", details=details) from error
        # A sync SDK can be called from an existing event loop.
        with ThreadPoolExecutor(max_workers=1) as worker:
            return worker.submit(asyncio.run, invoke()).result()


def discover_methods() -> dict[tuple[str, str], MethodPlugin]:
    builtin = DirectFactory()
    manifest = _manifest(builtin)
    plugins = {(manifest["kind"], manifest["plugin_id"]): MethodPlugin(manifest, {"kind": "builtin"}, builtin)}
    for entry in sorted(entry_points(group="llm4om.plugins"), key=lambda item: (item.name, item.value)):
        try:
            with _quiet():
                factory = entry.load()
        except (Exception, SystemExit) as error:
            raise RunError("plugin_load_error", "admission", "Cannot import an installed method factory.") from error
        manifest = _manifest(factory)
        origin = {"kind": "installed", "entry_point": entry.name, "value": entry.value,
                  "distribution": entry.dist.name if entry.dist else None,
                  "distribution_version": entry.dist.version if entry.dist else None}
        key = (manifest["kind"], manifest["plugin_id"])
        if key in plugins:
            raise RunError("duplicate_plugin", "admission", "Two active methods share a registry key.")
        plugins[key] = MethodPlugin(manifest, origin, factory)
    return plugins


def _manifest(factory: Any) -> dict[str, Any]:
    stable_version = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    text = {"type": "string", "minLength": 1}
    strings = {"type": "array", "items": text, "uniqueItems": True}
    capabilities = {name: strings for name in ("problem_types", "input_artifact_kinds", "output_artifact_kinds",
                    "formulation_representations", "code_representations", "model_backends", "solvers", "llm_features",
                    "execution_modes", "oracle_requirements")}
    capabilities.update(method_profile=text, supports_checkpoint={"type": "boolean"}, supports_clarification={"type": "boolean"})
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
            manifest = parse_json(json.dumps(factory.describe(), allow_nan=False).encode())
        jsonschema.Draft202012Validator({"type": "object", "properties": fields,
            "required": list(fields), "additionalProperties": False}).validate(manifest)
        jsonschema.Draft202012Validator.check_schema(manifest["config_schema"])
        _local_schema(manifest["config_schema"])
        reject_additional_refs(manifest["source"])
        if not callable(factory.create):
            raise TypeError("Factory must create a method.")
    except (Exception, SystemExit) as error:
        raise RunError("invalid_plugin_manifest", "admission", "Installed method Manifest or factory does not match the current profile.") from error
    interval = re.fullmatch(f">=(?P<lower>{stable_version}),\\s*<(?P<upper>{stable_version})", manifest["contract_range"])
    if interval is None or not (tuple(map(int, interval["lower"].split("."))) <= (0, 2, 0) < tuple(map(int, interval["upper"].split(".")))):
        raise RunError("incompatible_contract", "admission", "Method contract_range does not include core 0.2.0.")
    return manifest


def _local_schema(value: Any) -> None:
    if isinstance(value, dict):
        if "$id" in value or any(key in value and not str(value[key]).startswith("#") for key in ("$ref", "$dynamicRef")):
            raise ValueError("This profile requires self-contained configuration schemas.")
        for child in value.values():
            _local_schema(child)
    elif isinstance(value, list):
        for child in value:
            _local_schema(child)


@contextmanager
def _quiet() -> Iterator[None]:
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
        yield
