"""Build and solve one generated model, or run one check script. Runs inside the sandbox; imports nothing from llm4om.

Reads {code, data, language, time_limit} as JSON on stdin and prints one result line prefixed with RESULT_MARKER.
`build_model(data)` returns the model in the chosen interface; the worker solves it with the paired solver through
its native API and reads the result. For supported infeasible models it also finds conflicting constraints for display.
"""

import contextlib
import io
import json
import linecache
import math
import sys
import traceback
from functools import partial

RESULT_MARKER = "@@LLM4OM_RESULT@@"
MAX_OUTPUT_CHARS = 20000


class ModelError(Exception):
    """The generated model is unusable; the message is shown to the method as feedback."""


def _expect(model, kind, name):
    if not isinstance(model, kind):
        raise ModelError(f"build_model(data) must return a {name}; it returned {type(model).__name__}.")


def solve_highs(model, time_limit):
    """Pyomo through its HiGHS interface."""
    import pyomo.environ as pyo
    from pyomo.contrib.solver.common.factory import SolverFactory
    from pyomo.contrib.solver.common.results import SolutionStatus, TerminationCondition

    _expect(model, pyo.Block, "pyo.ConcreteModel")
    objectives = list(model.component_data_objects(pyo.Objective, active=True))
    if len(objectives) != 1:
        raise ModelError(f"The model must have exactly one active objective; found {len(objectives)}.")
    solver = SolverFactory("highs")
    solver.config.time_limit = float(time_limit)
    result = solver.solve(model, load_solutions=False, raise_exception_on_nonoptimal_result=False)
    status = {
        TerminationCondition.provenInfeasible: "infeasible", TerminationCondition.locallyInfeasible: "infeasible",
        TerminationCondition.unbounded: "unbounded", TerminationCondition.infeasibleOrUnbounded: "infeasible_or_unbounded",
        TerminationCondition.maxTimeLimit: "time_limit",
    }.get(result.termination_condition, "error")
    if result.solution_status == SolutionStatus.optimal:
        status = "optimal"
    elif result.solution_status == SolutionStatus.feasible and status == "error":
        status = "feasible"
    if result.solution_status not in (SolutionStatus.optimal, SolutionStatus.feasible):
        return status, None, None
    result.solution_loader.load_vars()
    values = {var.name: var.value for var in model.component_data_objects(pyo.Var) if var.value is not None}
    return status, result.incumbent_objective, values


def solve_gurobi(model, time_limit):
    import gurobipy as gp

    _expect(model, gp.Model, "gurobipy Model")
    model.setParam("OutputFlag", 0)
    model.setParam("TimeLimit", float(time_limit))
    model.optimize()
    if model.Status == gp.GRB.INF_OR_UNBD:
        # Presolve's dual reductions can leave this open; solving without them tells infeasible from unbounded.
        model.setParam("DualReductions", 0)
        model.optimize()
    status = {
        gp.GRB.OPTIMAL: "optimal", gp.GRB.INFEASIBLE: "infeasible", gp.GRB.UNBOUNDED: "unbounded",
        gp.GRB.INF_OR_UNBD: "infeasible_or_unbounded", gp.GRB.TIME_LIMIT: "time_limit",
        gp.GRB.SUBOPTIMAL: "feasible",
    }.get(model.Status, "error")
    if model.SolCount == 0:
        return status, None, None
    return status, model.ObjVal, {variable.VarName: variable.X for variable in model.getVars()}


def solve_ortools(solver, time_limit):
    from ortools.linear_solver import pywraplp

    _expect(solver, pywraplp.Solver, "pywraplp.Solver")
    solver.SetTimeLimit(int(float(time_limit) * 1000))
    result = solver.Solve()
    status = {
        pywraplp.Solver.OPTIMAL: "optimal", pywraplp.Solver.FEASIBLE: "feasible",
        pywraplp.Solver.INFEASIBLE: "infeasible", pywraplp.Solver.UNBOUNDED: "unbounded",
    }.get(result, "error")
    if result not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return status, None, None
    return status, solver.Objective().Value(), {variable.name(): variable.solution_value() for variable in solver.variables()}


def solve_cpsat(model, time_limit):
    """CPMpy on OR-Tools CP-SAT. A model without an objective is a satisfaction problem."""
    import cpmpy as cp
    from cpmpy.solvers.solver_interface import ExitStatus
    from cpmpy.transformations.get_variables import get_variables_model

    _expect(model, cp.Model, "cp.Model")
    solver = cp.SolverLookup.get("ortools", model)
    solver.solve(time_limit=float(time_limit))
    exit_status = solver.status().exitstatus
    status = {
        ExitStatus.OPTIMAL: "optimal", ExitStatus.FEASIBLE: "feasible", ExitStatus.UNSATISFIABLE: "infeasible",
        ExitStatus.UNKNOWN: "time_limit",
    }.get(exit_status, "error")
    if exit_status not in (ExitStatus.OPTIMAL, ExitStatus.FEASIBLE):
        return status, None, None
    if not model.has_objective():
        status = "feasible"
    objective = solver.objective_value() if model.has_objective() else None
    values = {var.name: var.value() for var in get_variables_model(model) if var.value() is not None}
    return status, objective, values


def solve_cbc(problem, time_limit):
    """PuLP with the CBC binary it bundles."""
    import pulp

    _expect(problem, pulp.LpProblem, "pulp.LpProblem")
    if problem.objective is None:
        raise ModelError("The model has no objective; add one with `problem += expression`.")
    problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=float(time_limit)))
    status = {
        pulp.LpSolutionOptimal: "optimal", pulp.LpSolutionIntegerFeasible: "feasible",
        pulp.LpSolutionInfeasible: "infeasible", pulp.LpSolutionUnbounded: "unbounded",
    }.get(problem.sol_status) or ("time_limit" if problem.status == pulp.LpStatusNotSolved else "error")
    if status not in ("optimal", "feasible"):
        return status, None, None
    values = {variable.name: variable.varValue for variable in problem.variables() if variable.varValue is not None}
    return status, pulp.value(problem.objective), values


def solve_cvxpy(problem, time_limit, *, solver):
    """One CVXPY result reader, with each solver's own time-limit option."""
    import cvxpy as cp
    import numpy as np

    _expect(problem, cp.Problem, "cvxpy Problem")
    options = {
        "CLARABEL": {"time_limit": float(time_limit)},
        "OSQP": {"time_limit": float(time_limit)},
        "SCS": {"time_limit_secs": float(time_limit)},
        "MOSEK": {"mosek_params": {"MSK_DPAR_OPTIMIZER_MAX_TIME": float(time_limit)}},
    }
    problem.solve(solver=solver, **options[solver])
    status = {
        cp.OPTIMAL: "optimal", cp.OPTIMAL_INACCURATE: "feasible", cp.INFEASIBLE: "infeasible",
        cp.INFEASIBLE_INACCURATE: "infeasible", cp.UNBOUNDED: "unbounded", cp.UNBOUNDED_INACCURATE: "unbounded",
        cp.USER_LIMIT: "time_limit",
    }.get(problem.status, "error")
    if status not in ("optimal", "feasible"):
        return status, None, None
    values = {}
    for variable in problem.variables():
        value = variable.value
        if value is None:
            continue
        if np.ndim(value) == 0:
            values[variable.name()] = value
        else:
            for index in np.ndindex(np.shape(value)):
                values[f"{variable.name()}[{','.join(map(str, index))}]"] = value[index]
    return status, problem.value, values


def solve_scip(model, time_limit):
    from pyscipopt import Model

    _expect(model, Model, "pyscipopt.Model")
    model.hideOutput()
    model.setRealParam("limits/time", float(time_limit))
    model.optimize()
    status = {"optimal": "optimal", "infeasible": "infeasible", "unbounded": "unbounded",
              "inforunbd": "infeasible_or_unbounded", "timelimit": "time_limit"}.get(str(model.getStatus()))
    solution = model.getBestSol()
    if solution is None:
        return status or "error", None, None
    return status or "feasible", model.getSolObjVal(solution), {v.name: model.getSolVal(solution, v) for v in model.getVars()}


def solve_ipopt(model, time_limit):
    import casadi as ca

    _expect(model, ca.Opti, "casadi.Opti")
    model.solver("ipopt", {"print_time": False}, {"print_level": 0, "sb": "yes", "max_wall_time": float(time_limit)})
    try:
        solution = model.solve_limited()
    except RuntimeError as error:
        try:
            status = model.stats()["return_status"]
        except RuntimeError:
            raise error
        if status == "Infeasible_Problem_Detected":
            return "locally_infeasible", None, None
        raise
    status = {"Solve_Succeeded": "locally_optimal", "Solved_To_Acceptable_Level": "feasible",
              "Maximum_WallTime_Exceeded": "time_limit", "Maximum_CpuTime_Exceeded": "time_limit",
              "Maximum_Iterations_Exceeded": "iteration_limit"}.get(solution.stats()["return_status"], "error")
    if status not in ("locally_optimal", "feasible"):
        return status, None, None  # an unfinished NLP iterate is not necessarily feasible
    values = {}
    for variable in ca.symvar(model.x):
        for row in range(variable.size1()):
            for col in range(variable.size2()):
                index = f"[{row},{col}]" if variable.size2() > 1 else f"[{row}]" if variable.size1() > 1 else ""
                values[variable.name() + index] = solution.value(variable[row, col])
    return status, solution.value(model.f), values


def solve_copt(model, time_limit):
    import coptpy as cp

    _expect(model, cp.Model, "coptpy.Model")
    model.setParam("Logging", 0)
    model.setParam("TimeLimit", float(time_limit))
    model.solve()
    status = {cp.COPT.OPTIMAL: "optimal", cp.COPT.INFEASIBLE: "infeasible", cp.COPT.UNBOUNDED: "unbounded",
              cp.COPT.INF_OR_UNB: "infeasible_or_unbounded", cp.COPT.TIMEOUT: "time_limit",
              cp.COPT.LOCAL_OPTIMAL: "locally_optimal", cp.COPT.LOCAL_INFEASIBLE: "locally_infeasible"}.get(model.status)
    if not model.hasSol:
        return status or "error", None, None
    return status or "feasible", model.objval, {v.name: v.x for v in model.getVars()}


# The language decides the solver.
SOLVERS = {"pyomo": solve_highs, "gurobipy": solve_gurobi, "pywraplp": solve_ortools, "cpmpy": solve_cpsat,
           "pulp": solve_cbc, "pyscipopt": solve_scip, "casadi": solve_ipopt, "coptpy": solve_copt,
           **{key: partial(solve_cvxpy, solver=solver) for key, solver in
              [("cvxpy", "CLARABEL"), ("cvxpy_osqp", "OSQP"), ("cvxpy_scs", "SCS"), ("cvxpy_mosek", "MOSEK")]}}
# Imported before the code runs: CVXPY logs a warning for every optional solver it cannot load, which is not output.
PRELOAD = {key: "cvxpy" for key in SOLVERS if key.startswith("cvxpy")}


IIS_TIME_LIMIT = 20  # seconds for finding the conflict of an infeasible model, after solving it
MAX_CONFLICT = 60  # constraints and bounds shown


def _linear(terms):
    """`(coefficient, name)` pairs as a readable sum, shortened after 12 terms."""
    text = " ".join(f"{'-' if coefficient < 0 else '+'} {'' if abs(coefficient) == 1 else f'{abs(coefficient):g} '}{name}"
                    for coefficient, name in terms[:12])
    text = text[2:] if text.startswith("+ ") else text
    return text + (" + ..." if len(terms) > 12 else "") if terms else "0"


def _pyomo_label(name):
    """Pyomo's LP label of a component (c_u_cap_, x(A_B)) shown close to its name (cap, x[A_B])."""
    import re

    name = re.sub(r"^c_[ulei]_(.*)_$", r"\1", name)
    return re.sub(r"\(([^()]*)\)", r"[\1]", name)


def gurobi_iis(model):
    """The constraints and bounds of an irreducible infeasible subsystem of a gurobipy model, found by Gurobi."""
    model.setParam("OutputFlag", 0)
    model.setParam("TimeLimit", float(IIS_TIME_LIMIT))
    model.computeIIS()
    sense = {"<": "<=", ">": ">=", "=": "="}
    items = []
    for constraint in model.getConstrs():
        if constraint.IISConstr:
            row = model.getRow(constraint)
            terms = [(row.getCoeff(i), row.getVar(i).VarName) for i in range(row.size())]
            items.append(f"{constraint.ConstrName}: {_linear(terms)} {sense[constraint.Sense]} {constraint.RHS:g}")
    items += [f"{constraint.QCName} (quadratic)" for constraint in model.getQConstrs() if constraint.IISQConstr]
    items += [f"{constraint.GenConstrName} (general)" for constraint in model.getGenConstrs() if constraint.IISGenConstr]
    for variable in model.getVars():
        if variable.IISLB:
            items.append(f"{variable.VarName} >= {variable.LB:g}")
        if variable.IISUB:
            items.append(f"{variable.VarName} <= {variable.UB:g}")
    return items


def _read_with_gurobi(write):
    """A gurobipy copy of a model that `write(path)` saves as an LP file."""
    import os
    import tempfile

    import gurobipy as gp

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "model.lp")
        write(path)
        return gp.read(path, env=gp.Env(params={"OutputFlag": 0}))


def _write_text(text):
    def write(path):
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)

    return write


def pyomo_iis(model):
    """Gurobi's IIS of a Pyomo model, with Pyomo's LP labels turned back towards the component names."""
    import re

    copy = _read_with_gurobi(lambda path: model.write(path, io_options={"symbolic_solver_labels": True}))
    return [re.sub(r"[A-Za-z_][\w()]*", lambda match: _pyomo_label(match.group()), item) for item in gurobi_iis(copy)]


def cpmpy_mus(model):
    """A minimal unsatisfiable subset of the constraints, found by CPMpy with CP-SAT."""
    from cpmpy.tools.explain import mus
    from cpmpy.transformations.normalize import toplevel_list

    return [str(constraint) for constraint in mus(toplevel_list(model.constraints), solver="ortools")]


# How each language finds the conflict of an infeasible model. Linear models go to Gurobi through an LP file, so the
# bundled size-limited license covers small models only. CVXPY has none: Clarabel reports no conflict.
CONFLICTS = {
    "gurobipy": ("Gurobi IIS", gurobi_iis),
    "pyomo": ("Gurobi IIS", pyomo_iis),
    "pywraplp": ("Gurobi IIS", lambda solver: gurobi_iis(_read_with_gurobi(_write_text(solver.ExportModelAsLpFormat(False))))),
    "pulp": ("Gurobi IIS", lambda problem: gurobi_iis(_read_with_gurobi(problem.writeLP))),
    "cpmpy": ("CPMpy MUS", cpmpy_mus),
}


def diagnose(language, model):
    """The conflict of an infeasible model, for display only: a method's feedback never includes it. None when the
    language has no way to find one."""
    import signal

    if language not in CONFLICTS:
        return None
    tool, find = CONFLICTS[language]

    def stop(*_):
        raise TimeoutError(f"No conflict found within {IIS_TIME_LIMIT} seconds.")

    previous = signal.signal(signal.SIGALRM, stop)
    signal.alarm(IIS_TIME_LIMIT + 5)  # Gurobi stops itself at IIS_TIME_LIMIT; this bounds the rest
    try:
        items = find(model)
        return {"tool": tool, "items": items[:MAX_CONFLICT], "total": len(items), "error": None}
    except BaseException as error:
        lines = str(error).strip().splitlines()
        return {"tool": tool, "items": [], "total": 0, "error": lines[0] if lines else type(error).__name__}
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def clean(value):
    value = float(value)
    if not math.isfinite(value):
        return None
    return 0.0 if value == 0 else value


def describe_error(error):
    """Keep the generated code's frames so feedback points at the model, not at the worker."""
    frames = traceback.extract_tb(error.__traceback__)
    own = [frame for frame in frames if frame.filename == "model.py"] or frames[-2:]
    return "".join(traceback.format_list(own) + traceback.format_exception_only(error)).rstrip()


def run(request):
    result = {"status": "error", "objective": None, "variables": {}, "output": "", "error": None, "diagnosis": None}
    output = io.StringIO()
    stage = "build"
    if request["language"] in PRELOAD:
        __import__(PRELOAD[request["language"]])
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            namespace = {"__name__": "generated_model"}
            linecache.cache["model.py"] = (len(request["code"]), None, request["code"].splitlines(True), "model.py")
            exec(compile(request["code"], "model.py", "exec"), namespace)
            build_model = namespace.get("build_model")
            if not callable(build_model):
                raise ModelError("The code must define build_model(data) and return the model object.")
            model = build_model(request.get("data") or {})
            if model is None:
                raise ModelError("build_model(data) returned None; it must return the model object.")
            stage = "solve"
            status, objective, values = SOLVERS[request["language"]](model, request.get("time_limit", 60))
            if status == "infeasible":
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result["diagnosis"] = diagnose(request["language"], model)
        result["status"] = status
        if values is not None:
            result["objective"] = None if objective is None else clean(objective)
            mapped = {name: clean(value) for name, value in values.items()}
            result["variables"] = mapped
    except ModelError as error:
        result["error"] = f"[{stage}] {error}"
    except BaseException as error:
        result["error"] = f"[{stage}] " + describe_error(error)
    result["output"] = output.getvalue()[-MAX_OUTPUT_CHARS:]
    return result


def run_script(request):
    """Run a method's own check script as __main__; stdout and the traceback form its output, like `python script.py`."""
    output = io.StringIO()
    error = None
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            exec(compile(request["script"], "script.py", "exec"), {"__name__": "__main__"})
        except BaseException as caught:
            traceback.print_exception(caught)
            error = describe_error(caught)
    return {"status": "error" if error else "executed", "objective": None, "variables": {},
            "output": output.getvalue()[-MAX_OUTPUT_CHARS:], "error": error}


def main():
    request = json.loads(sys.stdin.read())
    result = run_script(request) if "script" in request else run(request)
    sys.stdout.write("\n" + RESULT_MARKER + json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
