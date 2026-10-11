"""Trusted, independently authored original-business solution checkers."""

from collections.abc import Mapping
import csv
from decimal import Decimal
from io import StringIO
import math
import hashlib
import inspect
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol
import json

import jsonschema

from llm4om.contracts import RunError
from llm4om.plugins import _quiet


def _validate(value: Any, schema: dict[str, Any], code: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
        jsonschema.Draft202012Validator(schema).validate(value)
    except (ValueError, TypeError, jsonschema.ValidationError) as error:
        raise RunError(code, "evaluation", "Invalid independent-checker contract.") from error


def validate_checker_output(value: dict[str, Any], manifest: dict[str, Any]) -> None:
    strings = {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}
    _validate(value, {"type": "object", "additionalProperties": False,
        "required": ["schema_version", "independent_feasibility", "original_objective", "objective_sense"],
        "properties": {"schema_version": {"const": "0.1.0"}, "original_objective": {"type": "number"},
            "objective_sense": {"const": manifest["objective_sense"]}, "independent_feasibility": {
                "type": "object", "additionalProperties": False, "required": ["status", "violations", "coverage", "level"],
                "properties": {"status": {"enum": ["pass", "fail"]}, "violations": strings,
                    "coverage": {**strings, "minItems": 1}, "level": {"const": "independent_original_business_rules"}}}}},
        "invalid_checker_output")
    feasibility = value["independent_feasibility"]
    if (feasibility["status"] == "pass") != (not feasibility["violations"]):
        raise RunError("invalid_checker_output", "evaluation", "Checker violations contradict its feasibility status.")
    if not set(feasibility["violations"]) <= set(feasibility["coverage"]):
        raise RunError("invalid_checker_output", "evaluation", "Checker violations must belong to its actual coverage.")


class SolutionChecker(Protocol):
    def describe(self) -> dict[str, Any]: ...
    def check(self, problem: dict[str, Any], data: Mapping[str, bytes],
              decisions: Mapping[str, int | float]) -> dict[str, Any]: ...


def _number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise RunError("invalid_checker_input", "evaluation", "Checker quantities must be finite numbers.")
    result = Decimal(str(value))
    if not result.is_finite():
        raise RunError("invalid_checker_input", "evaluation", "Checker quantities must be finite numbers.")
    return result


def _outcome(violations: list[str], objective: Decimal, coverage: list[str]) -> dict[str, Any]:
    value = float(objective)
    if not math.isfinite(value):
        raise RunError("invalid_checker_input", "evaluation", "Original objective exceeds finite result range.")
    return {"schema_version": "0.1.0", "independent_feasibility": {
        "status": "fail" if violations else "pass", "violations": violations,
        "coverage": coverage, "level": "independent_original_business_rules"},
        "original_objective": value, "objective_sense": "max"}


class ProductionChecker:
    """Two nonnegative integer products with original CSV costs/capacities."""

    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.1.0", "checker_id": "llm4om.checkers.production", "version": "0.1.0",
            "required_decisions": ["A", "B"], "public_data_ids": ["products", "capacities"],
            "scope": "two_product_integer_production_from_original_public_csv", "objective_sense": "max",
            "coverage": ["nonnegative_domain", "integer_domain", "original_profit", "capacity:<resource_id>"]}

    def check(self, problem: dict[str, Any], data: Mapping[str, bytes],
              decisions: Mapping[str, int | float]) -> dict[str, Any]:
        if set(decisions) != {"A", "B"}:
            raise RunError("decision_mapping_unavailable", "evaluation", "Checker requires an explicit complete A/B mapping.")
        products = list(csv.DictReader(StringIO(data["products"].decode())))
        capacities = list(csv.DictReader(StringIO(data["capacities"].decode())))
        if len(products) != 2 or {row["product_id"] for row in products} != {"A", "B"} or not capacities:
            raise RunError("unsupported_checker_input", "evaluation", "This checker requires the declared two-product profile.")
        quantities = {name: _number(value) for name, value in decisions.items()}
        violations = []
        if any(value < Decimal("-0.0000001") for value in quantities.values()):
            violations.append("nonnegative_domain")
        if any(abs(value - value.to_integral_value()) > Decimal("0.000001") for value in quantities.values()):
            violations.append("integer_domain")
        coverage = ["nonnegative_domain", "integer_domain", "original_profit"]
        seen = set()
        for row in capacities:
            resource = row["resource_id"]
            if resource in seen:
                raise RunError("invalid_checker_input", "evaluation", "Resource keys must be unique.")
            seen.add(resource)
            capacity = _number(row["capacity"])
            used = sum((_number(product[resource]) * quantities[product["product_id"]] for product in products), Decimal(0))
            rule = "capacity:" + resource
            coverage.append(rule)
            if used > capacity + Decimal("0.0000001"):
                violations.append(rule)
        objective = sum((_number(product["profit"]) * quantities[product["product_id"]] for product in products), Decimal(0))
        return _outcome(violations, objective, coverage)


class UnitCapChecker:
    """Original integer quantity in [0, 1] with constant-zero objective."""

    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.1.0", "checker_id": "llm4om.checkers.unit_cap", "version": "0.1.0",
            "required_decisions": ["Q"], "public_data_ids": [], "scope": "integer_unit_interval_constant_zero",
            "objective_sense": "max", "coverage": ["nonnegative_domain", "integer_domain", "unit_cap", "zero_objective"]}

    def check(self, problem: dict[str, Any], data: Mapping[str, bytes],
              decisions: Mapping[str, int | float]) -> dict[str, Any]:
        if set(decisions) != {"Q"} or problem["source"].get("profile") != "integer_unit_interval_constant_zero":
            raise RunError("unsupported_checker_input", "evaluation", "Unit-cap checker requires its declared original profile.")
        value = _number(decisions["Q"])
        violations = []
        if value < Decimal("-0.0000001"):
            violations.append("nonnegative_domain")
        if abs(value - value.to_integral_value()) > Decimal("0.000001"):
            violations.append("integer_domain")
        if value > Decimal("1.0000001"):
            violations.append("unit_cap")
        return _outcome(violations, Decimal(0), self.describe()["coverage"])


def load_checker(selector: dict[str, Any]) -> tuple[SolutionChecker, dict[str, Any]]:
    """Load a trusted installed checker, never a file supplied by a dataset."""
    checker_id = selector["plugin_id"]
    builtins: dict[str, type[ProductionChecker] | type[UnitCapChecker]] = {
        "llm4om.checkers.production": ProductionChecker, "llm4om.checkers.unit_cap": UnitCapChecker}
    if checker_id in builtins:
        if selector["config"]:
            raise RunError("invalid_checker_config", "evaluation", "Built-in original checkers have no configurable rules.")
        checker: SolutionChecker = builtins[checker_id]()
        origin = {"kind": "builtin", "entry_point": None, "package": "llm4om"}
    else:
        entries = [entry for entry in entry_points(group="llm4om.checkers") if entry.name == checker_id]
        if not entries:
            raise RunError("checker_unavailable", "evaluation", "Declared checker is not installed.")
        if len(entries) != 1:
            raise RunError("ambiguous_checker", "evaluation", "Checker entry point must be unique.")
        try:
            with _quiet():
                factory = entries[0].load()
                checker = factory(selector["config"])
        except (Exception, SystemExit) as error:
            raise RunError("checker_load_error", "evaluation", "Installed trusted checker could not load.") from error
        origin = {"kind": "installed_trusted", "entry_point": entries[0].value,
                  "package": entries[0].dist.metadata["Name"] if entries[0].dist is not None else None,
                  "package_version": entries[0].dist.version if entries[0].dist is not None else None}
    try:
        with _quiet():
            manifest = checker.describe()
    except (Exception, SystemExit) as error:
        raise RunError("invalid_checker_manifest", "evaluation", "Checker could not describe its contract.") from error
    names = {"type": "array", "uniqueItems": True, "items": {"type": "string", "minLength": 1}}
    _validate(manifest, {"type": "object", "additionalProperties": False,
        "required": ["schema_version", "checker_id", "version", "required_decisions", "public_data_ids", "scope", "objective_sense", "coverage"],
        "properties": {"schema_version": {"const": "0.1.0"}, "checker_id": {"const": checker_id},
            "version": {"const": selector["version"]}, "required_decisions": {**names, "minItems": 1},
            "public_data_ids": names, "scope": {"type": "string", "minLength": 1},
            "objective_sense": {"enum": ["min", "max"]}, "coverage": {**names, "minItems": 1}}}, "invalid_checker_manifest")
    source = inspect.getsourcefile(type(checker))
    if source is None:
        raise RunError("checker_source_unavailable", "evaluation", "Checker source identity cannot be recorded.")
    manifest = {**manifest, "origin": origin, "source_sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        "sdk_checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return checker, manifest


def checked_solution(checker: SolutionChecker, manifest: dict[str, Any], problem: dict[str, Any],
                     data: Mapping[str, bytes], decisions: Mapping[str, int | float]) -> dict[str, Any]:
    with _quiet():
        result = checker.check(problem, data, decisions)
    validate_checker_output(result, manifest)
    return result
