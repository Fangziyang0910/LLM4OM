"""Optional real Gurobi LP/MILP Solver; never execute supplied source here."""

import math
import base64
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from importlib import import_module
from importlib.metadata import version
from typing import Any, Mapping

from llm4om.backends import ModelHandle
from llm4om.contracts import RunError
from llm4om.linear import CompiledCode


def runtime_versions() -> dict[str, str]:
    try:
        import_module("pyomo.environ")
        import_module("gurobipy")
        packages = {name: version(name) for name in ("Pyomo", "gurobipy")}
        if packages["gurobipy"] != "13.0.3":
            raise RunError("solver_unavailable", "admission", "This adapter requires gurobipy 13.0.3.")
        return packages
    except (ImportError, OSError) as error:
        raise RunError("solver_unavailable", "admission", "Install the gurobi extra in the selected runtime.") from error


def environment() -> Any:
    import gurobipy as gp
    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 0)
    env.setParam("LogFile", "")
    try:
        env.start()
    except gp.GurobiError as error:
        env.dispose()
        raise RunError("solver_unavailable", "admission", "Gurobi environment initialization failed.",
                       details={"sdk_error_code": error.errno}) from error
    return env


def availability() -> dict[str, Any]:
    """Bounded local micro-probe; no license identity or SDK error messages."""
    import gurobipy as gp
    with environment() as env, gp.Model(env=env) as model:
        model.addVar(lb=0, ub=1)
        model.setParam("TimeLimit", 1)
        model.setParam("Threads", 1)
        model.optimize()
        if model.Status != gp.GRB.OPTIMAL:
            raise RunError("solver_unavailable", "admission", "Gurobi micro-model is unavailable.")
        model.addVars(2000, lb=0, ub=1)
        try:
            model.optimize()
        except gp.GurobiError as error:
            if error.errno == 10010:
                return {"availability": "size_limited", "micro_model_verified": True,
                        "size_boundary_error": 10010}
            raise RunError("solver_unavailable", "admission", "Gurobi availability probe failed.",
                           details={"sdk_error_code": error.errno}) from error
        return {"availability": "micro_model_available_size_limit_not_observed", "micro_model_verified": True,
                "size_boundary_error": None}


_INFINITE_BOUND = 1e20


def _finite_bound(value: float) -> None:
    if not math.isfinite(value) or abs(value) >= _INFINITE_BOUND:
        raise RunError("unsupported_numeric_range", "solve", "Finite bounds and row RHS must have magnitude below 1e20.")


def validate_native(handle: ModelHandle) -> None:
    import gurobipy as gp
    if not isinstance(handle.model, gp.Model):
        raise RunError("invalid_model_handle", "execution", "Native factory requires a Gurobi Model.")
    model = handle.model
    model.update()
    if (model.NumQNZs or model.NumQConstrs or model.NumGenConstrs or model.NumSOS
            or model.NumPWLObjVars or model.NumObj != 1 or model.NumScenarios or model.IsMultiObj):
        raise RunError("unsupported_native_structure", "execution", "Only single-objective linear LP/MILP models are supported.")
    variables = model.getVars()
    if (not isinstance(handle.decision_map, Mapping)
            or any(not isinstance(key, str) or not key for key in handle.decision_map)
            or len(handle.decision_map) != len(variables)
            or any(not isinstance(var, gp.Var) for var in handle.decision_map.values())
            or sorted(var.index for var in handle.decision_map.values()) != list(range(len(variables)))
            or any(not var.sameAs(variables[var.index]) for var in handle.decision_map.values())):
        raise RunError("invalid_decision_map", "execution", "Decision map must name every native variable exactly once.")
    if len({var.VarName for var in variables}) != len(variables) or any(not var.VarName for var in variables):
        raise RunError("invalid_decision_map", "execution", "Native variable names must be unique and nonempty.")
    for var in variables:
        if var.VType not in (gp.GRB.CONTINUOUS, gp.GRB.INTEGER, gp.GRB.BINARY):
            raise RunError("unsupported_native_structure", "execution", "Semicontinuous/semiinteger variables are unsupported.")
        for bound in (var.LB, var.UB):
            if math.isnan(bound):
                raise RunError("unsupported_numeric_range", "execution", "Native bounds cannot be NaN.")
    numbers = [model.ObjCon, *model.getAttr("Obj", variables)]
    for row in model.getConstrs():
        _finite_bound(row.RHS)
        expression = model.getRow(row)
        numbers.extend([row.RHS, *[expression.getCoeff(i) for i in range(expression.size())]])
    if any(not math.isfinite(value) or abs(value) >= gp.GRB.INFINITY for value in numbers):
        raise RunError("unsupported_numeric_range", "execution", "Native coefficients and row bounds must be finite supported values.")


def _validate_options(options: dict[str, Any]) -> float:
    limit = options.get("time_limit_s", 0)
    try:
        seconds = float(limit) if not isinstance(limit, bool) and isinstance(limit, (int, float)) else math.nan
    except OverflowError:
        seconds = math.nan
    if set(options) - {"time_limit_s"} or not math.isfinite(seconds) or seconds < 0:
        raise RunError("invalid_solver_options", "admission", "Only finite nonnegative time_limit_s is supported.")
    return seconds


def solve_native(handle: ModelHandle, options: dict[str, Any], *, model_backend: str = "llm4om.model_backends.gurobipy") -> dict[str, Any]:
    import gurobipy as gp
    seconds = _validate_options(options)
    validate_native(handle)
    model = handle.model
    model.resetParams()
    for key, value in {"OutputFlag": 0, "LogFile": "", "Threads": 1, "DualReductions": 0}.items():
        model.setParam(key, value)
    if "time_limit_s" in options:
        model.setParam("TimeLimit", seconds)
    try:
        model.optimize()
    except gp.GurobiError as error:
        raise RunError("solver_error", "solve", "Gurobi rejected the solve operation.",
                       details={"sdk_error_code": error.errno}) from error
    raw = model.Status
    termination = {2: "optimal", 3: "infeasible", 4: "infeasible_or_unbounded", 5: "unbounded",
                   9: "time_limit", 11: "interrupted"}.get(raw, "unknown")
    primal = model.SolCount > 0
    def metric(name: str) -> float | None:
        try:
            value = float(model.getAttr(name))
            return value if math.isfinite(value) else None
        except (gp.GurobiError, AttributeError):
            return None
    return {"solver_id": "llm4om.solvers.gurobi", "solver_version": version("gurobipy"),
            "model_backend": model_backend, "raw_status": str(raw), "termination": termination,
            "has_primal_solution": primal,
            "variables": {key: float(var.X) for key, var in handle.decision_map.items()} if primal else None,
            "objective_value": metric("ObjVal") if primal else None,
            "objective_sense": "min" if model.ModelSense == 1 else "max",
            "best_bound": metric("ObjBound"), "reported_gap": metric("MIPGap") if primal and model.IsMIP else None,
            "solve_time_s": model.Runtime, "options": options,
            "effective_options": {key: model.getParamInfo(key)[2] for key in
                ("TimeLimit", "Threads", "FeasibilityTol", "IntFeasTol", "OptimalityTol", "MIPGap", "DualReductions")
                if key != "TimeLimit" or "time_limit_s" in options},
            "numerical_limits": {"infinite_bound": _INFINITE_BOUND, "infinity_sentinel": gp.GRB.INFINITY}, "diagnostics": [],
            "evidence_origin": "trusted_gurobi_api"}


def solve_gurobi(code: CompiledCode, options: dict[str, Any]) -> dict[str, Any]:
    _validate_options(options)
    from llm4om.backends import PyomoFactoryBackend
    return solve_gurobi_handle(PyomoFactoryBackend().load(code, {}), options)


def solve_gurobi_handle(handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]:
    _validate_options(options)
    from llm4om.backends import PyomoFactoryBackend
    PyomoFactoryBackend().export(handle)
    import gurobipy as gp
    import pyomo.environ as pyo
    from pyomo.repn import generate_standard_repn
    source = handle.model
    objective = next(source.component_data_objects(pyo.Objective, active=True, descend_into=True), None)
    if objective is None:
        raise RunError("unsupported_factory_expression", "solve", "The model declares no active objective to solve.")
    with environment() as env, gp.Model(env=env) as model:
        variables = {}
        for index, var in enumerate(source.component_data_objects(pyo.Var, active=True, descend_into=True)):
            for bound in (var.lb, var.ub):
                if bound is not None:
                    _finite_bound(float(bound))
            variables[id(var)] = model.addVar(lb=var.lb if var.lb is not None else -gp.GRB.INFINITY,
                ub=var.ub if var.ub is not None else gp.GRB.INFINITY,
                vtype=gp.GRB.BINARY if var.is_binary() else gp.GRB.INTEGER if var.is_integer() else gp.GRB.CONTINUOUS,
                name=f"v{index}")
        def expression(value: Any) -> Any:
            repn = generate_standard_repn(value)
            for coefficient in repn.linear_coefs:
                if 0 < abs(float(coefficient)) < 1e-13 or abs(float(coefficient)) >= gp.GRB.INFINITY:
                    raise RunError("unsupported_numeric_range", "solve", "Gurobi would drop or reject a coefficient.")
            return gp.LinExpr(list(repn.linear_coefs), [variables[id(var)] for var in repn.linear_vars]) + float(repn.constant)
        model.setObjective(expression(objective.expr), gp.GRB.MINIMIZE if objective.sense == pyo.minimize else gp.GRB.MAXIMIZE)
        for row in source.component_data_objects(pyo.Constraint, active=True, descend_into=True):
            expr = expression(row.body)
            if row.lower is not None:
                _finite_bound(float(pyo.value(row.lower)) - expr.getConstant())
                model.addConstr(expr >= pyo.value(row.lower))
            if row.upper is not None:
                _finite_bound(float(pyo.value(row.upper)) - expr.getConstant())
                model.addConstr(expr <= pyo.value(row.upper))
        decisions = {key: variables[id(var)] for key, var in handle.decision_map.items()}
        model.remove([variables[id(var)] for var in handle.internal_variables])
        return solve_native(ModelHandle(model, decisions), options, model_backend="llm4om.model_backends.pyomo_factory")


def native_instance(handle: ModelHandle) -> dict[str, Any]:
    """Derived linear view from the independently read SDK model."""
    import gurobipy as gp
    validate_native(handle)
    model = handle.model
    ids = {var.index: key for key, var in handle.decision_map.items()}
    def expression(expr: Any) -> dict[str, Any]:
        return {"constant": expr.getConstant(), "terms": [
            {"variable_id": ids[expr.getVar(i).index], "coefficient": expr.getCoeff(i)} for i in range(expr.size())]}
    variables = [{"id": ids[var.index], "name": var.VarName,
        "domain": {gp.GRB.CONTINUOUS: "continuous", gp.GRB.INTEGER: "integer", gp.GRB.BINARY: "binary"}[var.VType],
        "lower_bound": None if var.LB <= -gp.GRB.INFINITY else var.LB,
        "upper_bound": None if var.UB >= gp.GRB.INFINITY else var.UB, "requirement_ids": []} for var in model.getVars()]
    objective = expression(model.getObjective())
    return {"variables": variables, "objective": {"sense": "min" if model.ModelSense == 1 else "max",
        "expression": objective, "requirement_ids": []}, "constraints": [
        {"id": f"row_{row.index}", "expression": expression(model.getRow(row)),
         "sense": {"<": "le", ">": "ge", "=": "eq"}[row.Sense], "rhs": row.RHS, "requirement_ids": []}
        for row in model.getConstrs()], "decision_map": {key: var.VarName for key, var in handle.decision_map.items()},
        "problem_type": "milp" if model.IsMIP else "lp"}


@contextmanager
def read_native(exported: dict[str, Any]) -> Iterator[ModelHandle]:
    """Read untrusted model bytes with a fresh SDK, never candidate Python/state."""
    import gurobipy as gp
    if set(exported) != {"model_mps", "decision_map"} or not isinstance(exported["model_mps"], str):
        raise RunError("invalid_factory_export", "execution", "Native export must contain MPS bytes and explicit mapping.")
    try:
        raw = base64.b64decode(exported["model_mps"], validate=True)
    except ValueError as error:
        raise RunError("invalid_factory_export", "execution", "Invalid native MPS encoding.") from error
    with tempfile.TemporaryDirectory() as directory, environment() as env:
        path = Path(directory) / "model.mps"
        path.write_bytes(raw)
        try:
            model = gp.read(str(path), env=env)
        except gp.GurobiError as error:
            raise RunError("invalid_factory_export", "execution", "SDK could not read the native model file.") from error
        with model:
            names = {var.VarName: var for var in model.getVars()}
            decisions = exported["decision_map"]
            if (not isinstance(decisions, dict) or any(not isinstance(key, str) or not key for key in decisions)
                    or any(not isinstance(name, str) or name not in names for name in decisions.values())):
                raise RunError("invalid_decision_map", "execution", "Native export references unknown variables.")
            handle = ModelHandle(model, {key: names[name] for key, name in decisions.items()})
            validate_native(handle)
            yield handle
