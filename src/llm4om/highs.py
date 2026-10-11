"""Solve a trusted compiler-produced Pyomo model with the native HiGHS API."""

import math
from importlib import import_module
from importlib.metadata import version
from typing import Any

from llm4om.linear import CompiledCode
from llm4om.contracts import RunError
from llm4om.backends import ModelHandle, PyomoFactoryBackend


def runtime_versions() -> dict[str, str]:
    try:
        import_module("pyomo.environ")
        import_module("highspy")
        return {name: version(name) for name in ("Pyomo", "highspy")}
    except (ImportError, OSError) as error:
        raise RunError("solver_unavailable", "admission", "Install the solve extra to use Pyomo and HiGHS.") from error


def _time_limit(options: dict[str, Any]) -> float:
    limit = options.get("time_limit_s", 0)
    try:
        seconds = float(limit) if not isinstance(limit, bool) and isinstance(limit, (int, float)) else math.nan
    except OverflowError:
        seconds = math.nan
    if (set(options) - {"time_limit_s"} or isinstance(limit, bool)
            or not math.isfinite(seconds) or seconds < 0):
        raise RunError("invalid_solver_options", "admission", "Only a finite nonnegative time_limit_s is supported.")
    return seconds


def solve_highs(code: CompiledCode, options: dict[str, Any]) -> dict[str, Any]:
    _time_limit(options)
    return solve_highs_handle(PyomoFactoryBackend().load(code, {}), options)


def solve_highs_handle(handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]:
    seconds = _time_limit(options)
    # The re-export validates the linear structure and decision coverage before the solver consumes the handle.
    PyomoFactoryBackend().export(handle)
    import highspy
    import pyomo.environ as pyo
    from pyomo.repn import generate_standard_repn

    model = handle.model
    variables = list(model.component_data_objects(pyo.Var, active=True, descend_into=True))
    objectives = list(model.component_data_objects(pyo.Objective, active=True, descend_into=True))
    if len(objectives) != 1:
        raise RunError("invalid_factory_objective", "solve", "HiGHS requires exactly one active objective.")
    objective_model = objectives[0]
    solver = highspy.Highs()  # type: ignore[no-untyped-call]
    def checked(status: Any) -> None:
        if status == highspy.HighsStatus.kError:
            raise RunError("solver_error", "solve", "HiGHS rejected a model or option operation.")
    checked(solver.setOptionValue("output_flag", False))
    checked(solver.setOptionValue("threads", 1))
    if "time_limit_s" in options:
        checked(solver.setOptionValue("time_limit", seconds))
    limits = {name: float(solver.getOptionValue(name)[1]) for name in
              ("infinite_bound", "infinite_cost", "small_matrix_value", "large_matrix_value", "dual_feasibility_tolerance")}
    def finite_bound(value: Any) -> float:
        result = float(value)
        if not math.isfinite(result) or abs(result) >= limits["infinite_bound"]:
            raise RunError("unsupported_numeric_range", "solve", "A finite bound exceeds HiGHS numerical limits.")
        return result
    columns = {}
    for index, variable in enumerate(variables):
        columns[id(variable)] = index
        checked(solver.addVar(finite_bound(variable.lb) if variable.lb is not None else -highspy.kHighsInf,
                             finite_bound(variable.ub) if variable.ub is not None else highspy.kHighsInf))
        if variable.is_integer():
            checked(solver.changeColIntegrality(index, highspy.HighsVarType.kInteger))
    objective = generate_standard_repn(objective_model.expr)
    checked(solver.changeObjectiveOffset(float(objective.constant)))
    for variable, coefficient in zip(objective.linear_vars, objective.linear_coefs):
        if (not math.isfinite(float(coefficient)) or abs(coefficient) >= limits["infinite_cost"]
                or 0 < abs(coefficient) <= limits["dual_feasibility_tolerance"]):
            raise RunError("unsupported_numeric_range", "solve", "A cost is outside the supported HiGHS numerical range.")
        checked(solver.changeColCost(columns[id(variable)], float(coefficient)))
    checked(solver.changeObjectiveSense(highspy.ObjSense.kMinimize if objective_model.sense == pyo.minimize else highspy.ObjSense.kMaximize))
    for row in model.component_data_objects(pyo.Constraint, active=True, descend_into=True):
        expression = generate_standard_repn(row.body)
        indexes = [columns[id(variable)] for variable in expression.linear_vars]
        lower = finite_bound(pyo.value(row.lower) - expression.constant) if row.lower is not None else -highspy.kHighsInf
        upper = finite_bound(pyo.value(row.upper) - expression.constant) if row.upper is not None else highspy.kHighsInf
        if any(not math.isfinite(float(value)) or abs(value) >= limits["large_matrix_value"]
               or 0 < abs(value) <= limits["small_matrix_value"] for value in expression.linear_coefs):
            raise RunError("unsupported_numeric_range", "solve", "HiGHS would reject or drop a matrix coefficient.")
        checked(solver.addRow(lower, upper, len(indexes), indexes, list(expression.linear_coefs)))
    checked(solver.run())
    raw_status = solver.getModelStatus().name
    termination = {"kOptimal": "optimal", "kInfeasible": "infeasible", "kUnbounded": "unbounded",
                   "kUnboundedOrInfeasible": "infeasible_or_unbounded", "kTimeLimit": "time_limit",
                   "kHighsInterrupt": "interrupted", "kInterrupt": "interrupted",
                   "kLoadError": "error", "kModelError": "error", "kPresolveError": "error",
                   "kSolveError": "error", "kPostsolveError": "error", "kMemoryLimit": "error"}.get(raw_status, "unknown")
    info = solver.getInfo()
    primal = solver.getSolution()
    has_primal = info.valid and primal.value_valid and info.primal_solution_status == highspy.SolutionStatus.kSolutionStatusFeasible
    values = {name: float(primal.col_value[columns[id(variable)]]) for name, variable in handle.decision_map.items()} if has_primal else None
    objective_value = float(info.objective_function_value) if has_primal else None
    mip = any(variable.is_integer() for variable in variables)
    mip_stats = info.valid and mip and info.mip_node_count >= 0 and termination in ("optimal", "time_limit", "interrupted", "feasible")
    bound = float(info.mip_dual_bound) if mip_stats else objective_value if termination == "optimal" else None
    gap = float(info.mip_gap) if mip_stats and has_primal else None
    effective = {name: solver.getOptionValue(name)[1] for name in
                 ("threads", "primal_feasibility_tolerance", "dual_feasibility_tolerance", "mip_feasibility_tolerance", "mip_rel_gap")}
    return {"solver_id": "llm4om.solvers.highs", "solver_version": solver.version(),
            "model_backend": "llm4om.model_backends.pyomo_factory", "raw_status": raw_status,
            "termination": termination, "has_primal_solution": bool(has_primal), "variables": values,
            "objective_value": objective_value, "objective_sense": "min" if objective_model.sense == pyo.minimize else "max",
            "best_bound": bound if bound is not None and math.isfinite(bound) else None,
            "reported_gap": gap if gap is not None and math.isfinite(gap) else None,
            "solve_time_s": solver.getRunTime(), "options": options, "effective_options": effective,
            "numerical_limits": limits, "diagnostics": [],
            "evidence_origin": "trusted_highs_api"}
