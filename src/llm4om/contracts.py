"""Validate public inputs before methods see them."""

import json
import hashlib
import math
import csv
from pathlib import Path
from collections.abc import Hashable
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any
from urllib.parse import urlsplit

import jsonschema
import yaml


class RunError(ValueError):
    def __init__(self, code: str, stage: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.details = details


class _ConfigLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        self.flatten_mapping(node)
        return {key: value for key, value in _unique_object(self.construct_pairs(node, deep=deep)).items()}


def read_config(path: Path) -> dict[str, Any]:
    try:
        value = (parse_json(path.read_bytes()) if path.suffix == ".json"
                 else yaml.load(path.read_text(encoding="utf-8"), Loader=_ConfigLoader))
        if not isinstance(value, dict):
            raise ValueError("Expected an object.")
        _finite_numbers(value)
        _reject_private_fields(value)
        json.dumps(value, allow_nan=False)
        return value
    except RunError:
        raise
    except (yaml.YAMLError, ValueError, TypeError, RecursionError) as error:
        raise RunError("invalid_config", "admission", "YAML must have unique keys and finite JSON values without recursive aliases.") from error


def parse_json(raw: bytes) -> dict[str, Any]:
    value = parse_reference_json(raw)
    _reject_private_fields(value)
    return value


def parse_reference_json(raw: bytes) -> dict[str, Any]:
    """Strict JSON parsing for privileged import/evaluation boundaries only."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        _finite_numbers(value)
    except RunError:
        raise
    except (ValueError, RecursionError) as error:
        raise RunError("invalid_json", "validation", "JSON must have unique keys and finite numbers.") from error
    if not isinstance(value, dict):
        raise RunError("invalid_object", "validation", "Expected a JSON object.")
    return value


def read_public_bytes(path: Path, *, max_bytes: int | None = None) -> bytes:
    try:
        with path.open("rb") as stream:
            raw = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
        if max_bytes is not None and len(raw) > max_bytes:
            raise RunError("invalid_data", "validation", "Public data exceed the permitted per-file size.")
        return raw
    except OSError as error:
        raise RunError("input_unavailable", "validation", "Cannot read an explicit public input file.") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise ValueError("Object keys must be strings.")
        if key in result:
            raise ValueError("Duplicate key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Nonfinite number.")


def _finite_numbers(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite number.")
    if isinstance(value, (dict, list)):
        for item in (value.values() if isinstance(value, dict) else value):
            _finite_numbers(item)


def _reject_private_fields(value: Any) -> None:
    if isinstance(value, dict):
        private = {"apikey", "accesstoken", "refreshtoken", "clientsecret", "token", "authorization",
                   "password", "secret", "secrets", "credentials", "headers", "authheader", "authorizationheader",
                   "oracle", "oracleref", "oraclepath",
                   "referenceobjective", "referencesolution", "referencecode", "referencemodel",
                   "referencevariables", "independentchecker", "expertreview"}
        for key, item in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in private or (normalized == "containsoracle" and item is not False):
                raise RunError("private_input", "validation", "Public inputs cannot contain oracle fields or credentials.")
            if normalized == "baseurl" and isinstance(item, str):
                address = urlsplit(item)
                if address.username or address.password or address.query or address.fragment:
                    raise RunError("private_input", "validation", "Provider URLs cannot contain credentials or query fields.")
            _reject_private_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_private_fields(item)


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "additionalProperties": False,
            "required": list(properties) if required is None else required}


def reject_additional_refs(value: Any) -> None:
    if isinstance(value, dict):
        if "relative_path" in value or "namespace" in value:
            raise RunError("unsupported_reference", "validation", "S01 cannot project additional artifact references.")
        for item in value.values():
            reject_additional_refs(item)
    elif isinstance(value, list):
        for item in value:
            reject_additional_refs(item)


TEXT = {"type": "string", "minLength": 1, "pattern": "\\S"}
POSITIVE = {"type": "integer", "minimum": 1}
NONNEGATIVE = {"type": "integer", "minimum": 0}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}


def public_path(root: Path, relative: str, *, require_file: bool = True) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise RunError("unsafe_path", "validation", "Public references must stay inside their source directory.")
    try:
        resolved = (root / path).resolve()
        contained = resolved.is_relative_to(root.resolve()) and (not require_file or resolved.is_file())
    except (RuntimeError, OSError, ValueError) as error:
        raise RunError("unsafe_path", "validation", "Cannot resolve a public reference inside its source directory.") from error
    if not contained:
        raise RunError("unsafe_path", "validation", "Public reference escapes its source directory or is not a file.")
    return resolved


def read_artifact(root: Path, ref: dict[str, Any], version: str, id_key: str) -> dict[str, Any]:
    schema = _object({"artifact_id": TEXT, "media_type": {"const": "application/json"},
                      "sha256": HASH, "size_bytes": POSITIVE,
                      "namespace": {"const": "fixture_public"}, "relative_path": TEXT,
                      "schema_version": {"const": version}})
    try:
        jsonschema.Draft202012Validator(schema).validate(ref)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_artifact_ref", "formulation", "Mock artifact reference has an unsupported shape or version.") from error
    path = public_path(root, ref["relative_path"])
    raw = read_public_bytes(path)
    if hashlib.sha256(raw).hexdigest() != ref["sha256"] or len(raw) != ref["size_bytes"]:
        raise RunError("artifact_hash_mismatch", "formulation", "Mock artifact does not match its declared hash or size.")
    value = parse_json(raw)
    if value.get("schema_version") != version or value.get(id_key) != ref["artifact_id"]:
        raise RunError("invalid_artifact_ref", "formulation", "Mock artifact identity does not match its reference.")
    return value


def validate_problem(problem: dict[str, Any]) -> None:
    reject_additional_refs(problem)
    column = _object({"name": TEXT, "type": {"enum": ["string", "number", "integer"]},
                      "nullable": {"type": "boolean"}})
    schema = _object({
        "schema_version": {"enum": ["0.2.0", "0.3.0"]}, "problem_id": TEXT, "revision": TEXT,
        "description": {**TEXT, "pattern": "\\S"}, "language": TEXT,
        "problem_type_hint": {"enum": ["lp", "milp", "unknown"]},
        "requirements": {"type": "array", "items": _object({
            "id": TEXT, "text": TEXT, "category": {"enum": ["objective", "domain", "constraint", "data", "other"]},
            "source_span": {"type": ["null", "object", "array"]}})},
        "data_refs": {"type": "array", "items": {"oneOf": [_object({"data_id": TEXT, "path": TEXT,
            "format": {"const": "csv"}, "sha256": {"anyOf": [HASH, {"type": "null"}, {"const": ""}]},
            "schema": _object({"columns": {"type": "array", "items": column, "minItems": 1},
                               "unique_by": {"type": "array", "items": TEXT, "uniqueItems": True}})}),
            _object({"data_id": TEXT, "path": TEXT, "format": {"const": "json"},
                     "sha256": {"anyOf": [HASH, {"type": "null"}, {"const": ""}]},
                     "schema": _object({"type": {"const": "object"}})})]}},
        "assumptions": {"type": "array", "items": _object({"id": TEXT, "text": TEXT, "origin": TEXT,
            "status": {"enum": ["explicit", "proposed", "confirmed"]}})},
        "source": {"type": "object"},
        "metadata": _object({"purpose": TEXT, "contains_oracle": {"const": False}}, []),
    }, ["schema_version", "problem_id", "revision", "description", "language", "problem_type_hint",
        "requirements", "data_refs", "assumptions", "source"])
    try:
        jsonschema.Draft202012Validator(schema).validate(problem)
        if problem["schema_version"] == "0.2.0" and any(ref["format"] != "csv" for ref in problem["data_refs"]):
            raise ValueError("JSON data require ProblemSpec 0.3.0.")
        for key in ["requirements", "assumptions", "data_refs"]:
            id_key = "data_id" if key == "data_refs" else "id"
            ids = [item[id_key] for item in problem[key]]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate IDs.")
    except (jsonschema.ValidationError, ValueError) as error:
        raise RunError("invalid_problem", "validation", "ProblemSpec does not match its public data contract.") from error


def validate_data(raw: bytes, ref: dict[str, Any]) -> None:
    """Validate admitted public bytes without transforming their values."""
    if len(raw) > 8 * 1024 * 1024:
        raise RunError("invalid_data", "validation", "Public data exceed the 8 MiB per-file limit.")
    if ref["format"] == "csv":
        validate_csv(raw, ref["schema"])
    elif ref["format"] == "json" and ref["schema"] == {"type": "object"}:
        parse_json(raw)
    else:
        raise RunError("invalid_data", "validation", "Unsupported public data format or schema.")


def validate_csv(raw: bytes, schema: dict[str, Any]) -> None:
    diagnostic: dict[str, Any] = {"row": 1, "column": None, "reason": "columns_or_keys"}
    try:
        columns = schema["columns"]
        names = [column["name"] for column in columns]
        keys = schema["unique_by"]
        rows = csv.DictReader(StringIO(raw.decode("utf-8")), strict=True)
        if len(set(names)) != len(names) or rows.fieldnames != names or not set(keys) <= set(names):
            raise ValueError("Invalid columns or keys.")
        seen = set()
        for row_index, row in enumerate(rows, start=2):
            diagnostic.update(row=row_index, line=rows.line_num, column=None, reason="cell_count")
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Incorrect number of cells.")
            typed: dict[str, str | Decimal | None] = {}
            for column in columns:
                diagnostic.update(column=column["name"], reason="nullability")
                value = row[column["name"]]
                typed[column["name"]] = value
                if value == "":
                    if not column["nullable"]:
                        raise ValueError("Missing non-nullable cell.")
                    typed[column["name"]] = None
                elif column["type"] in {"number", "integer"}:
                    diagnostic["reason"] = "finite_numeric_type"
                    number = Decimal(value)
                    if not number.is_finite() or (column["type"] == "integer" and number != number.to_integral_value()):
                        raise ValueError("Invalid numeric cell.")
                    typed[column["name"]] = number
            if keys:
                diagnostic.update(column=None, columns=keys, reason="duplicate_key")
                key = tuple(typed[name] for name in keys)
                if key in seen:
                    raise ValueError("Duplicate data key.")
                seen.add(key)
    except (ValueError, InvalidOperation, csv.Error) as error:
        raise RunError("invalid_data", "validation", "CSV does not match its columns, finite types, nullability or unique keys.",
                       details=diagnostic) from error


def validate_model_artifact(artifact: dict[str, Any]) -> None:
    reject_additional_refs({key: value for key, value in artifact.items()
                            if key not in {"problem_ref", "formulation_ref"}})
    arrays = {name: {"type": "array"} for name in
              ["data_bindings", "assumptions", "requirement_traces", "diagnostics", "warnings", "optional_views"]}
    schema = _object({"schema_version": {"const": "0.2.0"}, "artifact_id": TEXT,
        "problem_ref": {"type": "object"}, "formulation_ref": {"type": ["object", "null"]},
        "code_ref": {"type": "null"}, "provenance": {"type": "object"}, **arrays,
        "stage_status": _object({
            "formulation": {"anyOf": [_object({"status": {"const": "available"}, "reason": {"type": "null"}}),
                _object({"status": {"const": "not_available"}, "reason": TEXT})]},
            "code": _object({"status": {"enum": ["pending", "not_available"]}, "reason": TEXT})})})
    try:
        jsonschema.Draft202012Validator(schema).validate(artifact)
        if (artifact["formulation_ref"] is None) != (artifact["stage_status"]["formulation"]["status"] == "not_available"):
            raise ValueError("Formulation reference and availability differ.")
    except (jsonschema.ValidationError, ValueError) as error:
        raise RunError("invalid_model_artifact", "formulation", "Artifact stage availability and references must agree.") from error


def validate_bindings(artifact: dict[str, Any], public: dict[str, Any]) -> None:
    expected = {ref["data_id"]: ref["sha256"] for ref in public["data_refs"]}
    bindings = artifact.get("data_bindings")
    binding_schema = {"type": "array", "items": {"type": "object", "required": ["data_id", "sha256"],
                                                 "properties": {"data_id": TEXT, "sha256": HASH}}}
    try:
        jsonschema.Draft202012Validator(binding_schema).validate(bindings)
    except jsonschema.ValidationError as error:
        raise RunError("artifact_data_mismatch", "formulation", "Data bindings must name the public data revision.") from error
    if not isinstance(bindings, list):
        raise RunError("artifact_data_mismatch", "formulation", "Data bindings must name the public data revision.")
    actual = {item.get("data_id"): item.get("sha256") for item in bindings}
    if len(actual) != len(bindings) or actual != expected:
        raise RunError("artifact_data_mismatch", "formulation", "Mock artifact data bindings do not match the public input.")


def validate_formulation(formulation: dict[str, Any], public: dict[str, Any]) -> None:
    reject_additional_refs({key: value for key, value in formulation.items() if key != "structured_ir_ref"})
    if formulation.get("representation_kind") == "native_formulation":
        schema = _object({"schema_version": {"const": "0.3.0"}, "formulation_id": TEXT,
            "problem_id": {"const": public["problem_id"]}, "problem_revision": {"const": public["revision"]},
            "representation_kind": {"const": "native_formulation"},
            "representation": _object({"schema": TEXT, "state": {"type": "object"}}),
            "data_bindings": {"type": "array"}, "provenance": {"type": "object"},
            "structured_ir_ref": {"type": "null"}})
        try:
            jsonschema.Draft202012Validator(schema).validate(formulation)
            parse_json(json.dumps(formulation, allow_nan=False).encode())
        except (jsonschema.ValidationError, ValueError) as error:
            raise RunError("invalid_formulation", "formulation", "Native Formulation requires a declared schema and original JSON state.") from error
        validate_bindings(formulation, public)
        return
    indexes = {"type": "array", "items": TEXT, "uniqueItems": True}
    set_entry = {"type": "object", "required": ["id"], "anyOf": [{"required": ["elements"]}, {"required": ["source"]}],
                 "properties": {"id": TEXT, "elements": {"type": "array", "uniqueItems": True},
                                "source": {"type": "object", "required": ["data_id", "column"]}}}
    parameter_entry = {"type": "object", "required": ["id", "index_sets"],
                       "anyOf": [{"required": ["source"]}, {"required": ["value"]}, {"required": ["expression_text"]}],
                       "properties": {"id": TEXT, "index_sets": indexes, "expression_text": TEXT,
                                      "value": {"$ref": "#/$defs/parameter_value"},
                                      "source": {"type": "object", "required": ["data_id"],
                                                 "anyOf": [{"required": ["column"]}, {"required": ["columns"]}]}}}
    variable_entry = {"type": "object", "required": ["id", "index_sets", "domain", "lower_bound", "upper_bound"],
                      "properties": {"id": TEXT, "index_sets": indexes, "domain": TEXT,
                                     "lower_bound": {"type": ["number", "string", "null"]},
                                     "upper_bound": {"type": ["number", "string", "null"]}}}
    constraint_entry = {"type": "object", "required": ["id", "expression_text"],
                        "properties": {"id": TEXT, "expression_text": TEXT}}
    schema = _object({"schema_version": {"const": "0.2.0"}, "formulation_id": TEXT,
        "problem_id": {"const": public["problem_id"]}, "problem_revision": {"const": public["revision"]},
        "representation_kind": {"const": "five_element"}, "representation": _object({
            **{name: {"type": "array", "items": entry} for name, entry in {
                "sets": set_entry, "parameters": parameter_entry, "variables": variable_entry,
                "constraints": constraint_entry}.items()},
            "objective": {"type": "object", "required": ["sense", "expression_text"], "properties": {
                "sense": {"enum": ["min", "max"]}, "expression_text": TEXT}}}),
        "data_bindings": {"type": "array"}, "provenance": {"type": "object"},
        "structured_ir_ref": {"type": ["object", "null"]},
    })
    schema["$defs"] = {"parameter_value": {"anyOf": [
        {"type": "number"},
        {"type": "array", "items": {"$ref": "#/$defs/parameter_value"}},
        {"type": "object", "additionalProperties": {"$ref": "#/$defs/parameter_value"}},
    ]}}
    try:
        jsonschema.Draft202012Validator(schema).validate(formulation)
        for key in ["sets", "parameters", "variables", "constraints"]:
            ids = [item["id"] for item in formulation["representation"][key]]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate IDs.")
        set_ids = {item["id"] for item in formulation["representation"]["sets"]}
        data = {ref["data_id"]: {column["name"] for column in ref["schema"]["columns"]}
                for ref in public["data_refs"] if ref["format"] == "csv"}
        for key in ["sets", "parameters", "variables"]:
            for item in formulation["representation"][key]:
                if not set(item.get("index_sets", [])) <= set_ids:
                    raise ValueError("Unknown index set.")
                if "source" in item:
                    source = item["source"]
                    columns = source.get("columns", [source.get("column")])
                    if (not isinstance(source.get("data_id"), str) or source["data_id"] not in data
                            or not isinstance(columns, list) or not columns):
                        raise ValueError("Unknown data source.")
                    names = [*columns, *([source["key_column"]] if "key_column" in source else [])]
                    if any(not isinstance(name, str) or name not in data[source["data_id"]] for name in names):
                        raise ValueError("Unknown source column.")
    except (jsonschema.ValidationError, ValueError) as error:
        raise RunError("invalid_formulation", "formulation", "Mock output must supply five elements for the public problem revision.") from error
    validate_bindings(formulation, public)


def validate_worker_response(payload: dict[str, Any], expected_runtime: dict[str, Any], *,
                             solver_id: str = "llm4om.solvers.highs",
                             model_backend: str = "llm4om.model_backends.pyomo_factory",
                             result_profile: str | None = None) -> None:
    result_profile = result_profile or ("gurobi_api/0.1.0" if solver_id == "llm4om.solvers.gurobi" else "highs_api/0.1.0")
    if result_profile not in ("highs_api/0.1.0", "gurobi_api/0.1.0"):
        raise RunError("worker_protocol_error", "execution", "Unsupported declared Solver result profile.")
    gurobi = result_profile == "gurobi_api/0.1.0"
    number = {"type": ["number", "null"]}
    result = _object({
        "solver_id": {"const": solver_id},
        "solver_version": {"const": expected_runtime["packages"]["gurobipy" if gurobi else "highspy"]},
        "model_backend": {"const": model_backend},
        "raw_status": TEXT, "termination": {"enum": ["optimal", "feasible", "infeasible", "unbounded",
            "infeasible_or_unbounded", "time_limit", "interrupted", "error", "unknown"]},
        "has_primal_solution": {"type": "boolean"},
        "variables": {"anyOf": [{"type": "object", "additionalProperties": {"type": "number"}}, {"type": "null"}]},
        "objective_value": number, "objective_sense": {"enum": ["min", "max"]}, "best_bound": number,
        "reported_gap": {"type": ["number", "null"], "minimum": 0},
        "solve_time_s": {"type": "number", "minimum": 0},
        "options": _object({"time_limit_s": {"type": "number", "minimum": 0}}, []),
        "effective_options": {"type": "object"}, "numerical_limits": {"type": "object"},
        "diagnostics": {"type": "array"}, "evidence_origin": {"const": "trusted_gurobi_api" if gurobi else "trusted_highs_api"},
    })
    schema = {"oneOf": [
        _object({"schema_version": {"const": "0.2.0"}, "error": _object({"code": TEXT, "stage": TEXT, "message": TEXT})}),
        _object({"schema_version": {"const": "0.2.0"}, "runtime": {"const": expected_runtime}, "result": result,
                 "resources": _object({"cpu_time_s": {"type": "number", "minimum": 0}, "peak_memory_bytes": NONNEGATIVE}),
                 "factory": _object({"instance": {"type": "object"}, "decision_map": {"type": "object"}, "source_sha256": HASH, "model_mps": TEXT},
                                    ["instance", "decision_map", "source_sha256"])},
                 ["schema_version", "runtime", "result", "resources"]),
    ]}
    try:
        jsonschema.Draft202012Validator(schema).validate(payload)
        if "result" in payload:
            solve = payload["result"]
            if (solve["has_primal_solution"] != (solve["variables"] is not None)
                    or solve["has_primal_solution"] != (solve["objective_value"] is not None)):
                raise ValueError("Primal availability and values disagree.")
    except (jsonschema.ValidationError, ValueError) as error:
        raise RunError("worker_protocol_error", "execution", "Worker response does not match the supported result protocol.") from error


def validate_config(settings: dict[str, Any]) -> None:
    from llm4om.data_loaders import VIEW_SCHEMA
    llm_selection = _object({"provider_plugin_id": TEXT, "model": TEXT, "config": {"type": "object"}})
    schema = _object({
        "schema_version": {"const": "0.2.0"},
        "method": _object({"plugin_id": TEXT, "config": {"type": "object"}}),
        "llm": _object({**llm_selection["properties"], "role_models": {"type": "object", "propertyNames": TEXT,
            "additionalProperties": llm_selection}}, ["provider_plugin_id", "model", "config"]),
        "compiler": _object({"plugin_id": TEXT, "config": {"type": "object"}}, ["plugin_id"]),
        "data_loader": _object({"plugin_id": TEXT, "config": {"type": "object"}}, ["plugin_id"]),
        "data_view": VIEW_SCHEMA,
        "model_backend": _object({"plugin_id": TEXT, "config": {"type": "object"}}, ["plugin_id"]),
        "solver": _object({"plugin_id": TEXT, "config": {"type": "object"}, "options": _object({
            "time_limit_s": {"type": "number", "minimum": 0}}, [])}, ["plugin_id"]),
        "executor": {"anyOf": [
            _object({"plugin_id": {"const": "llm4om.executors.container"}, "config": _object({
                "network": {"const": False}, "cpu_limit": POSITIVE, "memory_limit_mb": POSITIVE,
                "wall_time_s": {"type": "number", "exclusiveMinimum": 0},
                "image": TEXT, "output_limit_bytes": POSITIVE, "pids_limit": POSITIVE},
                ["network", "cpu_limit", "memory_limit_mb", "wall_time_s"])}),
            _object({"plugin_id": {"const": "llm4om.executors.trusted_local"}, "config": _object({})}),
        ]},
        "budget": _object({name: ({"type": "number", "exclusiveMinimum": 0} if name == "wall_time_s"
                                 else POSITIVE if name == "max_concurrency" else NONNEGATIVE)
                           for name in ["max_llm_attempts", "max_total_tokens", "max_candidates",
                                        "max_repairs", "max_solver_calls", "wall_time_s", "max_concurrency"]}),
        "store": _object({"plugin_id": {"const": "llm4om.stores.filesystem"},
                          "config": _object({"root": TEXT})}),
        "reporters": {"type": "array", "maxItems": 32, "items": _object({"plugin_id": TEXT,
            "config": {"type": "object"}}, ["plugin_id"])},
        "evaluation": _object({"protocol_id": {"const": "llm4om.eval.public-v0.1"},
                               "evaluator_plugin_id": {"const": "llm4om.evaluators.structural"}}),
        "allowed_problem_types": {"type": "array", "minItems": 1, "uniqueItems": True,
                                  "items": {"enum": ["lp", "milp"]}},
    }, ["schema_version", "method", "llm", "model_backend", "solver", "executor", "budget", "store"])
    try:
        jsonschema.Draft202012Validator(schema).validate(settings)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_config", "admission", "RunConfig is outside the supported text/grounded-LPIR profile.") from error
    if settings["budget"]["max_llm_attempts"] < 1 or settings["budget"]["max_candidates"] < 1:
        raise RunError("unsupported_config", "admission", "Offline replay requires one Mock attempt and one candidate slot.")
