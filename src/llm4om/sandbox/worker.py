"""Build and solve one generated model, or run one check script. Runs inside the sandbox; imports nothing from llm4om.

Reads {code, data, language, time_limit} as JSON on stdin and prints one result line prefixed with RESULT_MARKER.
`build_model(data)` returns the model in the chosen language (Pyomo, gurobipy, OR-Tools pywraplp or CPMpy); the worker
solves it with that language's solver (HiGHS, Gurobi, SCIP or CP-SAT) through its own interface and reads the result.
"""

import contextlib
import io
import json
import linecache
import math
import sys
import traceback

RESULT_MARKER = "@@LLM4OM_RESULT@@"
MAX_OUTPUT_CHARS = 20000
MAX_VARIABLES = 2000


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


# The language decides the solver.
SOLVERS = {"pyomo": solve_highs, "gurobipy": solve_gurobi, "pywraplp": solve_ortools, "cpmpy": solve_cpsat}


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
    result = {"status": "error", "objective": None, "variables": {}, "output": "", "error": None}
    output = io.StringIO()
    stage = "build"
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
        result["status"] = status
        if values is not None:
            result["objective"] = None if objective is None else clean(objective)
            mapped = {name: clean(value) for name, value in values.items()}
            result["variables"] = dict(list(mapped.items())[:MAX_VARIABLES])
            if len(mapped) > MAX_VARIABLES:
                print(f"[llm4om] Showing the first {MAX_VARIABLES} of {len(mapped)} variables.", file=output)
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
