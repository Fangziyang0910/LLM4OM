"""Worker-local Pyomo/native handles and isolated model export."""

from dataclasses import dataclass
import hashlib
import json
import math
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Mapping, Protocol, ContextManager

from llm4om.contracts import RunError, parse_json, read_public_bytes
from llm4om.linear import CompiledCode


@dataclass(frozen=True)
class ModelHandle:
    model: Any
    decision_map: Mapping[str, Any]
    internal_variables: tuple[Any, ...] = ()


class ModelBackend(Protocol):
    def load(self, build: str | CompiledCode, data: Mapping[str, bytes]) -> ModelHandle: ...
    def export(self, handle: ModelHandle) -> dict[str, Any]: ...


class NativeModelBackend(ModelBackend, Protocol):
    def read_transport(self, exported: dict[str, Any]) -> ContextManager[ModelHandle]: ...


class PyomoFactoryBackend:
    """Construction only, inside the untrusted factory child, never the collector."""

    def load(self, build: str | CompiledCode, data: Mapping[str, bytes]) -> ModelHandle:
        source = build.source if isinstance(build, CompiledCode) else build
        namespace: dict[str, Any] = {}
        exec(compile(source, "<method-factory>", "exec"), namespace)
        handle = namespace["build_model"](data)
        if isinstance(build, CompiledCode):
            return ModelHandle(handle, {key: handle.variables[index] for key, index in build.symbol_map["variables"].items()},
                tuple(handle.variables[index] for index in build.symbol_map["internal_variables"].values()))
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
        if not isinstance(handle.decision_map, Mapping) or not isinstance(handle.internal_variables, tuple):
            raise RunError("invalid_decision_map", "execution", "ModelHandle requires a decision mapping and explicit internal variables.")
        internal_ids = {id(variable) for variable in handle.internal_variables}
        mapped = [*handle.decision_map.values(), *handle.internal_variables]
        if (not isinstance(handle.decision_map, Mapping)
                or any(not isinstance(key, str) or not key for key in handle.decision_map)
                or len(mapped) != len(variables)
                or {id(value) for value in mapped} != {id(value) for value in variables}
                or any(variable.lb != 0 or variable.ub != 0 for variable in handle.internal_variables)):
            raise RunError("invalid_decision_map", "execution", "Decision map must name every model variable exactly once.")
        ids = {id(value): key for key, value in handle.decision_map.items()}
        records = []
        symbols = {}
        for variable in variables:
            if id(variable) in internal_ids:
                continue
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
            if not repn.is_linear() or any(id(var) not in ids and id(var) not in internal_ids for var in repn.linear_vars):
                raise RunError("unsupported_factory_expression", "execution", "Only linear expressions over mapped variables are supported.")
            return {"constant": number(repn.constant), "terms": [
                {"variable_id": ids[id(var)], "coefficient": number(coef)}
                for var, coef in zip(repn.linear_vars, repn.linear_coefs) if id(var) not in internal_ids]}
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


class GurobiFactoryBackend(PyomoFactoryBackend):
    """Native construction child; SDK model file contains no solution or options."""

    def read_transport(self, exported: dict[str, Any]) -> ContextManager[ModelHandle]:
        from llm4om.gurobi import read_native
        return read_native(exported)

    def export(self, handle: ModelHandle) -> dict[str, Any]:
        import base64
        import tempfile
        from llm4om.gurobi import validate_native
        validate_native(handle)
        names = {key: var.VarName for key, var in handle.decision_map.items()}
        if any(any(char.isspace() for char in name) for name in names.values()):
            raise RunError("invalid_decision_map", "execution", "Native MPS transport requires names without whitespace.")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.mps"
            handle.model.write(str(path))
            return {"model_mps": base64.b64encode(read_public_bytes(path)).decode("ascii"), "decision_map": names}


class PyomoBackendFactory:
    plugin_id = "llm4om.model_backends.pyomo_factory"
    handle_profile = "pyomo_linear/0.1.0"
    representations = ["python_factory"]
    dependencies = ["Pyomo"]
    code_generation = {"representation_kind": "python_factory",
        "instruction": "Build a concrete Pyomo model using pyomo.environ. Use real/integer/binary interval domains. "
            "The decision_map values are scalar Pyomo variables."}

    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.2.0", "plugin_id": self.plugin_id, "kind": "model_backend",
            "plugin_version": "0.1.0", "contract_range": ">=0.2.0,<0.3.0", "display_name": self.plugin_id,
            "description": "Worker-local linear model construction and validated export.",
            "capabilities": {"backend_profile": "model_handle/0.1.0", "handle_profile": self.handle_profile,
                "problem_types": ["lp", "milp"], "input_artifact_kinds": self.representations,
                "output_artifact_kinds": ["model_handle"], "code_generation": self.code_generation},
            "config_schema": {"type": "object", "additionalProperties": False},
            "dependencies": {"python": self.dependencies}, "source": None}

    def create(self, config: dict[str, Any]) -> ModelBackend:
        if config:
            raise RunError("invalid_config", "admission", "The built-in Backend has no configuration options.")
        return PyomoFactoryBackend()


class GurobiBackendFactory(PyomoBackendFactory):
    plugin_id = "llm4om.model_backends.gurobipy"
    handle_profile = "gurobipy_linear/0.1.0"
    representations = ["native_code"]
    dependencies = ["gurobipy"]
    code_generation = {"representation_kind": "native_code",
        "instruction": "Build a native gurobipy model. Use gp.Env(empty=True), OutputFlag=0, LogFile='', "
            "env.start() and gp.Model(env=env). The decision_map values are Gurobi variables, including range slack variables."}

    def create(self, config: dict[str, Any]) -> ModelBackend:
        if config:
            raise RunError("invalid_config", "admission", "The built-in Backend has no configuration options.")
        return GurobiFactoryBackend()


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
        if "execution" in request:
            from llm4om.plugins import resolve_configured_plugin
            from llm4om.compilers import compiler_identity
            backend, binding = resolve_configured_plugin("model_backend", request["execution"]["model_backend"])
            identity = {key: value for key, value in compiler_identity(binding).items() if key != "packages"}
            if identity != request["execution_identity"]["model_backend"]:
                raise RunError("checkpoint_incompatible", "execution", "Factory child Backend differs from the admitted identity.")
        else:
            backend = GurobiFactoryBackend() if request["kind"] == "native_gurobipy/0.1.0" else PyomoFactoryBackend()
        with redirect_stdout(sys.stderr):
            exported = backend.export(backend.load(source.decode("utf-8"), data))
        print(json.dumps({"instance": exported}, allow_nan=False))
        return 0
    except RunError as error:
        print(json.dumps({"error": {"code": error.code, "stage": error.stage, "message": str(error)}}))
    except (Exception, SystemExit) as error:
        if not type(error).__module__.startswith("gurobipy"):
            traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": {"code": "factory_exception", "stage": "execution", "message": "Factory construction/export failed: " + type(error).__name__}}))
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
