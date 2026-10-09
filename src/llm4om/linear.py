"""Compile grounded linear models to a reproducible Pyomo factory."""

import json
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import jsonschema

from llm4om.contracts import RunError


@dataclass(frozen=True)
class CompiledCode:
    source: str
    symbol_map: dict[str, Any]


def compile_ir(ir: dict[str, Any]) -> CompiledCode:
    _validate_ir(ir)
    model = deepcopy({key: ir[key] for key in ("variables", "objective", "constraints")})
    expressions = [model["objective"]["expression"], *[row["expression"] for row in model["constraints"]]]
    for expression in expressions:
        groups: dict[str, list[int | float]] = {}
        for term in expression["terms"]:
            groups.setdefault(term["variable_id"], []).append(term["coefficient"])
        try:
            expression["terms"] = [{"variable_id": key,
                                    "coefficient": sum(values) if all(isinstance(value, int) for value in values) else math.fsum(values)}
                                   for key, values in groups.items()]
            for term in expression["terms"]:
                _finite(term["coefficient"])
        except (ValueError, OverflowError) as error:
            raise RunError("invalid_ir", "code", "Merged coefficients exceed supported solver numbers.") from error
    payload = json.dumps(model, ensure_ascii=False, allow_nan=False, sort_keys=True)
    source = '''"""Deterministically compiled grounded LPIR; data revision is fixed."""
import json
import pyomo.environ as pyo
from pyomo.core.expr.numeric_expr import LinearExpression

IR = json.loads(PAYLOAD)

def build_model(data):
    model = pyo.ConcreteModel()
    variables = IR["variables"]
    domains = {"continuous": pyo.Reals, "integer": pyo.Integers, "binary": pyo.Binary}
    model.variables = pyo.Var(
        range(max(1, len(variables))),
        domain=lambda m, i: domains[variables[i]["domain"]] if variables else pyo.Reals,
        bounds=lambda m, i: (variables[i]["lower_bound"], variables[i]["upper_bound"]) if variables else (0, 0),
    )
    indexes = {variable["id"]: i for i, variable in enumerate(variables)}
    def expression(value):
        return LinearExpression(
            constant=value["constant"],
            linear_coefs=[term["coefficient"] for term in value["terms"]],
            linear_vars=[model.variables[indexes[term["variable_id"]]] for term in value["terms"]],
        )
    model.objective = pyo.Objective(expr=expression(IR["objective"]["expression"]),
                                  sense=pyo.minimize if IR["objective"]["sense"] == "min" else pyo.maximize)
    model.constraints = pyo.ConstraintList()
    for row in IR["constraints"]:
        lower = row["rhs"] if row["sense"] in ("ge", "eq") else None
        upper = row["rhs"] if row["sense"] in ("le", "eq") else None
        model.constraints.add((lower, expression(row["expression"]), upper))
    return model
'''.replace("PAYLOAD", repr(payload))
    symbols = {"variables": {variable["id"]: index for index, variable in enumerate(ir["variables"])},
               "constraints": {row["id"]: index + 1 for index, row in enumerate(ir["constraints"])},
               "internal_variables": {} if ir["variables"] else {"constant_anchor": 0}}
    return CompiledCode(source, symbols)


def _record(fields: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": fields, "required": list(fields) if required is None else required,
            "additionalProperties": False}


def _validate_ir(ir: dict[str, Any]) -> None:
    text = {"type": "string", "minLength": 1}
    number = {"type": "number"}
    bound = {"type": ["number", "null"]}
    ids = {"type": "array", "items": text}
    expression = _record({"constant": number, "terms": {"type": "array", "items": _record({
        "variable_id": text, "coefficient": number})}})
    variable = _record({"id": text, "name": text, "domain": {"enum": ["continuous", "integer", "binary"]},
                        "lower_bound": bound, "upper_bound": bound, "requirement_ids": ids})
    row = _record({"id": text, "expression": expression, "sense": {"enum": ["le", "ge", "eq"]},
                   "rhs": number, "requirement_ids": ids})
    schema = _record({"schema_version": {"const": "0.1.0"}, "ir_kind": {"const": "grounded_lp"},
        "problem_type": {"enum": ["lp", "milp"]}, "model_id": text, "problem_id": text,
        "problem_revision": text, "data_bindings": {"type": "array", "items": {"type": "object"}},
        "variables": {"type": "array", "items": variable},
        "objective": _record({"sense": {"enum": ["min", "max"]}, "expression": expression, "requirement_ids": ids}),
        "constraints": {"type": "array", "items": row}, "assumptions": {"type": "array"},
        "provenance": {"type": "object"}})
    try:
        jsonschema.Draft202012Validator(schema).validate(ir)
        for key in ("variables", "constraints"):
            values = [item["id"] for item in ir[key]]
            if len(values) != len(set(values)):
                raise ValueError("Duplicate identifiers.")
        variables = {variable["id"] for variable in ir["variables"]}
        expressions = [ir["objective"]["expression"], *[row["expression"] for row in ir["constraints"]]]
        for value in expressions:
            _finite(value["constant"])
            for term in value["terms"]:
                _finite(term["coefficient"])
                if term["variable_id"] not in variables:
                    raise ValueError("Unknown variable reference.")
        for row in ir["constraints"]:
            _finite(row["rhs"])
            _finite(row["rhs"] - row["expression"]["constant"])
        for variable in ir["variables"]:
            lower, upper = variable["lower_bound"], variable["upper_bound"]
            for value in (lower, upper):
                if value is not None:
                    _finite(value)
            if variable["domain"] == "binary":
                lower = max(0, lower) if lower is not None else 0
                upper = min(1, upper) if upper is not None else 1
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("Contradictory bounds.")
            if ir["problem_type"] == "lp" and variable["domain"] != "continuous":
                raise ValueError("LP declares an integer variable.")
    except (jsonschema.ValidationError, ValueError, OverflowError) as error:
        raise RunError("invalid_ir", "code", "LPIR must have unique IDs, finite linear terms, supported domains and valid references/bounds.") from error


def _finite(value: int | float) -> None:
    number = float(value)
    if not math.isfinite(number) or isinstance(value, int) and number != value:
        raise ValueError("Solver numbers must be finite doubles without rounding integer literals.")
