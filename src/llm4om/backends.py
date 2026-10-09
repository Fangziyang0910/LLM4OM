"""Worker-local Pyomo factory handle and linear instance export."""

from dataclasses import dataclass
import hashlib
import json
import math
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Mapping

from llm4om.contracts import RunError, parse_json, read_public_bytes


@dataclass(frozen=True)
class ModelHandle:
    model: Any
    decision_map: Mapping[str, Any]


class PyomoFactoryBackend:
    """Construction only, inside the untrusted factory child, never the collector."""

    def load(self, source: str, data: Mapping[str, bytes]) -> ModelHandle:
        namespace: dict[str, Any] = {}
        exec(compile(source, "<method-factory>", "exec"), namespace)
        handle = namespace["build_model"](data)
        if not isinstance(handle, ModelHandle):
            raise RunError("invalid_model_handle", "execution", "build_model must return a Worker-local ModelHandle.")
        return handle

    def export(self, handle: ModelHandle) -> dict[str, Any]:
        import pyomo.environ as pyo
        from pyomo.repn import generate_standard_repn
        if not isinstance(handle.model, pyo.ConcreteModel) or not handle.model.is_constructed():
            raise RunError("invalid_model_handle", "execution", "Factory must return a constructed concrete Pyomo model.")
        model = handle.model
        variables = list(model.component_data_objects(pyo.Var, active=True, descend_into=True))
        if (not isinstance(handle.decision_map, Mapping)
                or any(not isinstance(key, str) or not key for key in handle.decision_map)
                or len(handle.decision_map) != len(variables)
                or {id(value) for value in handle.decision_map.values()} != {id(value) for value in variables}):
            raise RunError("invalid_decision_map", "execution", "Decision map must name every model variable exactly once.")
        ids = {id(value): key for key, value in handle.decision_map.items()}
        records = []
        symbols = {}
        for variable in variables:
            interval = variable.domain.get_interval()
            if (interval is None or interval[2] not in (0, 1) or variable.fixed
                    or any(bound is not None and bound not in variable.domain for bound in interval[:2])):
                raise RunError("unsupported_factory_domain", "execution", "Only unfixed real/integer interval domains are supported.")
            domain = "binary" if variable.is_binary() else "integer" if variable.is_integer() else "continuous" if variable.is_continuous() else None
            if domain is None:
                raise RunError("unsupported_factory_domain", "execution", "Factory variable domain is unsupported.")
            key = ids[id(variable)]
            records.append({"id": key, "name": variable.name, "domain": domain,
                            "lower_bound": pyo.value(variable.lb), "upper_bound": pyo.value(variable.ub), "requirement_ids": []})
            symbols[key] = variable.name
        allowed = {pyo.Block, pyo.Var, pyo.Param, pyo.Set, pyo.RangeSet, pyo.Objective, pyo.Constraint, pyo.Expression, pyo.Suffix}
        if any(component.ctype not in allowed for component in model.component_objects(active=True, descend_into=True)):
            raise RunError("unsupported_factory_component", "execution", "Factory contains unsupported active Pyomo components.")
        objectives = list(model.component_data_objects(pyo.Objective, active=True, descend_into=True))
        if len(objectives) != 1:
            raise RunError("invalid_factory_objective", "execution", "Factory requires exactly one active objective.")
        def number(value: Any) -> float:
            numeric = pyo.value(value)
            result = float(numeric)
            if not math.isfinite(result) or isinstance(numeric, int) and result != numeric:
                raise RunError("unsupported_numeric_range", "execution", "Factory numbers must be finite doubles without rounding integer values.")
            return result
        def expression(value: Any) -> dict[str, Any]:
            repn = generate_standard_repn(value, compute_values=True)
            if not repn.is_linear() or any(id(var) not in ids for var in repn.linear_vars):
                raise RunError("unsupported_factory_expression", "execution", "Only linear expressions over mapped variables are supported.")
            return {"constant": number(repn.constant), "terms": [
                {"variable_id": ids[id(var)], "coefficient": number(coef)}
                for var, coef in zip(repn.linear_vars, repn.linear_coefs)]}
        rows = []
        for index, row in enumerate(model.component_data_objects(pyo.Constraint, active=True, descend_into=True)):
            body = expression(row.body)
            if row.lower is None and row.upper is None:
                raise RunError("unsupported_factory_expression", "execution", "An active constraint must have a bound.")
            bounds = [("eq", row.lower)] if row.equality else [("ge", row.lower), ("le", row.upper)]
            for sense, bound in bounds:
                if bound is not None:
                    rows.append({"id": f"row_{index}_{sense}", "expression": body, "sense": sense,
                                 "rhs": number(bound), "requirement_ids": []})
        return {"variables": records, "objective": {"sense": "min" if objectives[0].sense == pyo.minimize else "max",
                "expression": expression(objectives[0].expr), "requirement_ids": []}, "constraints": rows,
                "decision_map": symbols, "problem_type": "milp" if any(row["domain"] != "continuous" for row in records) else "lp"}


def _main() -> int:
    try:
        path = Path(sys.argv[1])
        request = parse_json(read_public_bytes(path))
        source = read_public_bytes(path.parent / "model.py")
        if hashlib.sha256(source).hexdigest() != request["source_sha256"]:
            raise RunError("code_hash_mismatch", "execution", "Factory source hash does not match the proposal.")
        data = {}
        for ref in request["data_refs"]:
            raw = read_public_bytes(path.parent / ref["path"])
            if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                raise RunError("data_hash_mismatch", "execution", "Factory data bytes do not match the binding.")
            data[ref["data_id"]] = raw
        from llm4om.backends import PyomoFactoryBackend as FactoryBackend
        backend = FactoryBackend()
        with redirect_stdout(sys.stderr):
            exported = backend.export(backend.load(source.decode("utf-8"), data))
        print(json.dumps({"instance": exported}, allow_nan=False))
        return 0
    except RunError as error:
        print(json.dumps({"error": {"code": error.code, "stage": error.stage, "message": str(error)}}))
    except (Exception, SystemExit) as error:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": {"code": "factory_exception", "stage": "execution", "message": "Factory construction/export failed: " + type(error).__name__}}))
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
