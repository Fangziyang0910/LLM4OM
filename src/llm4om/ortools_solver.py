"""Trusted LP/MILP solving with the OR-Tools MPSolver SCIP engine."""

import math
from importlib import import_module
from importlib.metadata import version
from typing import Any

from llm4om.backends import ModelHandle, PyomoFactoryBackend
from llm4om.contracts import RunError
from llm4om.highs import validated_time_limit


def runtime_versions() -> dict[str, str]:
    try:
        import_module("pyomo.environ")
        api = import_module("ortools.linear_solver.pywraplp")
        if api.Solver.CreateSolver("SCIP") is None:
            raise ImportError("SCIP is unavailable in this OR-Tools build.")
        return {name: version(name) for name in ("Pyomo", "ortools")}
    except (ImportError, OSError) as error:
        raise RunError("solver_unavailable", "admission", "Install the ortools extra to use OR-Tools/SCIP.") from error


def solve_ortools_handle(handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]:
    seconds = validated_time_limit(options)
    instance = PyomoFactoryBackend().export(handle)
    from ortools.linear_solver import pywraplp

    solver = pywraplp.Solver.CreateSolver("SCIP")
    if solver is None:
        raise RunError("solver_unavailable", "solve", "This OR-Tools build has no SCIP engine.")
    if not solver.SetNumThreads(1):
        raise RunError("solver_error", "solve", "SCIP rejected the single-thread limit.")
    if "time_limit_s" in options:
        if seconds * 1000 >= 2**63:
            raise RunError("invalid_solver_options", "admission", "The time limit exceeds OR-Tools milliseconds range.")
        solver.SetTimeLimit(max(1, math.ceil(seconds * 1000)))
    # Disable ambiguous infeasible-or-unbounded presolve conclusions.
    if not solver.SetSolverSpecificParametersAsString("presolving/maxrounds = 0"):
        raise RunError("solver_error", "solve", "SCIP rejected its declared presolve setting.")
    variables = {}
    for entry in instance["variables"]:
        lower = entry["lower_bound"] if entry["lower_bound"] is not None else -solver.infinity()
        upper = entry["upper_bound"] if entry["upper_bound"] is not None else solver.infinity()
        construct = solver.NumVar if entry["domain"] == "continuous" else solver.IntVar
        variables[entry["id"]] = construct(lower, upper, entry["id"])
    for entry in instance["constraints"]:
        expression = entry["expression"]
        bound = entry["rhs"] - expression["constant"]
        if not math.isfinite(bound):
            raise RunError("unsupported_numeric_range", "solve", "Constraint constant shift overflowed.")
        row = solver.RowConstraint(bound if entry["sense"] != "le" else -solver.infinity(),
            bound if entry["sense"] != "ge" else solver.infinity(), entry["id"])
        coefficients: dict[str, float] = {}
        for term in expression["terms"]:
            key = term["variable_id"]
            coefficients[key] = coefficients.get(key, 0) + term["coefficient"]
        for key, coefficient in coefficients.items():
            row.SetCoefficient(variables[key], coefficient)
    objective = solver.Objective()
    objective.SetOffset(instance["objective"]["expression"]["constant"])
    for term in instance["objective"]["expression"]["terms"]:
        objective.SetCoefficient(variables[term["variable_id"]], term["coefficient"])
    sense = instance["objective"]["sense"]
    objective.SetMaximization() if sense == "max" else objective.SetMinimization()
    status = solver.NOT_SOLVED if "time_limit_s" in options and seconds == 0 else solver.Solve()
    names = {solver.OPTIMAL: "optimal", solver.FEASIBLE: "feasible", solver.INFEASIBLE: "infeasible",
        solver.UNBOUNDED: "unbounded", solver.ABNORMAL: "error", solver.MODEL_INVALID: "error",
        solver.NOT_SOLVED: "time_limit" if "time_limit_s" in options else "unknown"}
    termination = names.get(status, "unknown")
    primal = status in (solver.OPTIMAL, solver.FEASIBLE)
    if primal and not solver.VerifySolution(1e-7, False):
        raise RunError("solver_error", "solve", "OR-Tools returned a primal that failed its independent numeric check.")
    bound = objective.Value() if status == solver.OPTIMAL else objective.BestBound() if primal else None
    return {"solver_id": "llm4om.solvers.ortools", "solver_version": version("ortools"),
        "model_backend": "llm4om.model_backends.pyomo_factory", "raw_status": str(status),
        "termination": termination, "has_primal_solution": primal,
        "variables": {key: variable.solution_value() for key, variable in variables.items()} if primal else None,
        "objective_value": objective.Value() if primal else None, "objective_sense": sense,
        "best_bound": bound if bound is not None and math.isfinite(bound) else None, "reported_gap": None,
        "solve_time_s": solver.WallTime() / 1000, "options": options,
        "effective_options": {"engine": solver.SolverVersion(), "threads": 1, "presolving/maxrounds": 0,
            "time_limit_ms": max(1, math.ceil(seconds * 1000)) if "time_limit_s" in options else None},
        "numerical_limits": {}, "diagnostics": [], "evidence_origin": "trusted_ortools_api"}
