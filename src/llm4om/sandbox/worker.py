"""Build and solve one generated model, or run one check script. Runs inside the sandbox; imports nothing from llm4om.

Reads {code, data, language, time_limit} as JSON on stdin and prints one result line prefixed with RESULT_MARKER.
`build_model(data)` returns the model in the chosen interface; the worker solves it with the selected backend through
its native API and reads the result. For supported infeasible models it also finds conflicting constraints for display.
"""

import contextlib
import io
import json
import linecache
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import timedelta

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


def solve_ortools(solver, time_limit, backend="SCIP"):
    from ortools.linear_solver import linear_solver_pb2, pywraplp

    _expect(solver, pywraplp.Solver, "pywraplp.Solver")
    integers = any(v.integer() for v in solver.variables())
    # MPSolver binds its engine at construction. Native protobuf transfer enforces the selected engine.
    proto = linear_solver_pb2.MPModelProto()
    solver.ExportModelToProto(proto)
    original = solver
    solver = original if backend == 'AUTO' else pywraplp.Solver.CreateSolver(backend)
    if solver is None:
        raise ModelError(f"OR-Tools MPSolver backend {backend!r} is not available in this installation.")
    if integers and not solver.IsMip():
        raise ModelError(f"{backend} does not support integer variables; refusing to relax the model.")
    error = solver.LoadModelFromProtoKeepNames(proto) if solver is not original else ''
    if error:
        raise ModelError(error)
    solver.SetTimeLimit(int(float(time_limit) * 1000))
    result = solver.Solve()
    status = {
        pywraplp.Solver.OPTIMAL: "optimal", pywraplp.Solver.FEASIBLE: "feasible",
        pywraplp.Solver.INFEASIBLE: "infeasible", pywraplp.Solver.UNBOUNDED: "unbounded",
    }.get(result, "error")
    if result not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        return status, None, None
    return status, solver.Objective().Value(), {variable.name(): variable.solution_value() for variable in solver.variables()}


def solve_cpmpy(model, time_limit, backend):
    """CPMpy Model and SolverInterface share its native result contract."""
    import cpmpy as cp
    from cpmpy.solvers.solver_interface import ExitStatus, SolverInterface
    from cpmpy.transformations.get_variables import get_variables_model

    _expect(model, (cp.Model, SolverInterface), "cp.Model or CPMpy SolverInterface")
    if isinstance(model, cp.Model):
        variables = get_variables_model(model)
        solver = cp.SolverLookup.get(backend, model)
    else:
        variables = model.user_vars
        solver = model
        if solver.name.split(':')[0] != backend.split(':')[0] or (':' in backend and solver.name != backend):
            raise ModelError(f"Returned CPMpy interface {solver.name!r} differs from selected backend {backend!r}.")
    no_interrupt = backend.startswith('pysat') and type(solver.pysat_solver.solver).__name__.startswith(('Cadical', 'Lingeling'))
    if backend == 'pysdd' or no_interrupt:
        solver.solve()  # these native APIs have no interrupt timer; the subprocess deadline still applies
    else:
        solver.solve(time_limit=float(time_limit))
    exit_status = solver.status().exitstatus
    status = {
        ExitStatus.OPTIMAL: "optimal", ExitStatus.FEASIBLE: "feasible", ExitStatus.UNSATISFIABLE: "infeasible",
        ExitStatus.UNKNOWN: "time_limit",
    }.get(exit_status, "error")
    if exit_status not in (ExitStatus.OPTIMAL, ExitStatus.FEASIBLE):
        return status, None, None
    if not solver.has_objective():
        status = "feasible"
    objective = solver.objective_value() if solver.has_objective() else None
    values = {var.name: var.value() for var in variables if var.value() is not None}
    return status, objective, values


def solve_pulp(problem, time_limit, backend):
    """PuLP owns its backend registry, command adapters and result conversion."""
    import pulp

    _expect(problem, pulp.LpProblem, "pulp.LpProblem")
    if problem.objective is None:
        raise ModelError("The model has no objective; add one with `problem += expression`.")
    if backend not in pulp.listSolvers():
        raise ModelError(f"Unknown PuLP backend {backend!r}.")
    seconds = max(1, int(time_limit)) if backend == 'GLPK_CMD' else float(time_limit)
    solver = pulp.getSolver(backend, msg=False, timeLimit=seconds)
    if not solver.available():
        raise ModelError(f"PuLP backend {backend!r} requires its optional package or executable.")
    if backend == 'CyLP':
        return solve_pulp_cylp(problem, time_limit)
    problem.solve(solver)
    status = {
        pulp.LpSolutionOptimal: "optimal", pulp.LpSolutionIntegerFeasible: "feasible",
        pulp.LpSolutionInfeasible: "infeasible", pulp.LpSolutionUnbounded: "unbounded",
    }.get(problem.sol_status) or ("time_limit" if problem.status == pulp.LpStatusNotSolved else "error")
    if status not in ("optimal", "feasible"):
        return status, None, None
    values = {variable.name: variable.varValue for variable in problem.variables() if variable.varValue is not None}
    return status, pulp.value(problem.objective), values


def solve_pulp_cylp(problem, time_limit):
    """PuLP's CyLP adapter omits status assignment and misreads pure LPs; use its native MPS writer and CLP/CBC."""
    import pulp
    from cylp.cy import CyClpSimplex

    native = CyClpSimplex()
    native.logLevel = 0
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'model.mps')
        variables = problem.writeMPS(path, mpsSense=pulp.LpMinimize)
        if native.readMps(path):
            raise ModelError('CyLP could not read the PuLP model.')
    if problem.isMIP():
        native = native.getCbcModel()
        native.logLevel = 0
        native.maximumSeconds = float(time_limit)
        native.solve()
        status = {'solution': 'optimal', 'problem proven infeasible': 'infeasible',
                  'linear relaxation unbounded': 'unbounded', 'relaxation infeasible': 'infeasible',
                  'stopped on time': 'time_limit'}.get(native.status, 'error')
        has_solution = status == 'optimal' or native.solutionCount > 0
    else:
        status = {'optimal': 'optimal', 'primal infeasible': 'infeasible', 'dual infeasible': 'unbounded',
                  'stopped on iterations or time': 'time_limit'}.get(native.initialSolve(), 'error')
        has_solution = status == 'optimal'
    if not has_solution:
        return status, None, None
    values = {v.name: float(value) for v, value in zip(variables, native.primalVariableSolution)}
    problem.assignVarsVals(values)
    return status, pulp.value(problem.objective), values


def solve_cvxpy(problem, time_limit, *, solver, interface="dcp"):
    """One CVXPY result reader, with each solver's own time-limit option."""
    import cvxpy as cp
    import numpy as np

    _expect(problem, cp.Problem, "cvxpy Problem")
    options = {
        "CLARABEL": {"time_limit": float(time_limit)},
        "OSQP": {"time_limit": float(time_limit)},
        "SCS": {"time_limit_secs": float(time_limit)},
        "MOSEK": {"mosek_params": {"MSK_DPAR_OPTIMIZER_MAX_TIME": float(time_limit)}},
        "GUROBI": {"TimeLimit": float(time_limit)},
        "SCIP": {"scip_params": {"limits/time": float(time_limit)}},
        "SCIPY": {"scipy_options": {"time_limit": float(time_limit)}},
        "HIGHS": {"time_limit": float(time_limit)},
        "CPLEX": {"cplex_params": {"timelimit": float(time_limit)}},
        "CBC": {"maximumSeconds": float(time_limit)},
        "GLPK": {"tm_lim": int(float(time_limit)*1000)},
        "GLPK_MI": {"tm_lim": int(float(time_limit)*1000)},
        "COPT": {"TimeLimit": float(time_limit)},
        "XPRESS": {"maxtime": max(1, int(time_limit))},
    }
    if solver != "AUTO" and solver not in cp.installed_solvers():
        raise ModelError(f"CVXPY backend {solver!r} is not installed or cannot load; install its optional dependency.")
    mode = {"dcp": {}, "dgp": {"gp": True}, "dqcp": {"qcp": True}}[interface]
    if solver == "AUTO":
        preference = ["CLARABEL", "OSQP", "SCIP", "SCS", "HIGHS", "SCIPY"]
        installed = cp.installed_solvers()
        path = [(name, {} if interface == 'dqcp' else options.get(name, {})) for name in dict.fromkeys(preference+installed) if name in installed]
        problem.solve(solver_path=path, **mode)
    else:
        # DQCP forwards kwargs to bisection, not to the inner solver; its subprocess has the outer deadline.
        problem.solve(solver=solver, **mode, **({} if interface == 'dqcp' else options.get(solver, {})))
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


def pyomo_solver(backend):
    import pyomo.environ as pyo
    if backend == "cbc" and not shutil.which('cbc'):
        import pulp
        return pyo.SolverFactory(backend, executable=pulp.PULP_CBC_CMD().path)
    return pyo.SolverFactory(backend)


def solve_pyomo(model, time_limit, backend, interface):
    import pyomo.environ as pyo
    from pyomo.opt import SolverFactory
    from pyomo.solvers.plugins.solvers.persistent_solver import PersistentSolver

    if backend == "highs" and interface != "kernel":
        return solve_highs(model, time_limit)
    if backend not in SolverFactory:
        raise ModelError(f"Unknown Pyomo solver plugin {backend!r}.")
    solver = pyomo_solver(backend)
    if not solver.available(exception_flag=False):
        raise ModelError(f"Pyomo plugin {backend!r} requires its optional library, executable or license.")
    root = backend.removeprefix("appsi_").split('_')[0]
    option = {"gurobi": "TimeLimit", "cplex": "timelimit", "cbc": "seconds", "glpk": "tmlim",
              "ipopt": "max_cpu_time", "scip": "limits/time", "highs": "time_limit", "xpress": "maxtime"}.get(root)
    options = {option: max(1, int(time_limit)) if root == "glpk" else float(time_limit)} if option else {}
    if isinstance(solver, PersistentSolver):
        solver.set_instance(model)
    result = solver.solve(model, tee=False, load_solutions=False, options=options)
    termination = str(result.solver.termination_condition).lower()
    status = {"optimal": "optimal", "globallyoptimal": "optimal", "locallyoptimal": "locally_optimal",
              "infeasible": "infeasible", "unbounded": "unbounded", "infeasibleorunbounded": "infeasible_or_unbounded",
              "maxtimelimit": "time_limit", "maxiterations": "iteration_limit", "feasible": "feasible"}.get(termination, "error")
    if not result.solution:
        return status, None, None
    solution_status = str(result.solution[0].status).lower()
    if solution_status not in ("optimal", "feasible", "bestsofar", "stoppedbylimit"):
        return status, None, None
    if interface == "kernel":
        import pyomo.kernel as pmo
        model.load_solution(result.solution[0])
        variables = model.components(ctype=pmo.variable)
        objective = next(model.components(ctype=pmo.objective))
    else:
        _expect(model, pyo.Block, "instantiated Pyomo model")
        model.solutions.load_from(result)
        variables = model.component_data_objects(pyo.Var)
        objective = next(model.component_data_objects(pyo.Objective, active=True))
    values = {v.name: v.value for v in variables if v.value is not None}
    return "feasible" if status == "error" else status, pyo.value(objective), values


def solve_mathopt(model, time_limit, backend):
    from ortools.math_opt.python import mathopt

    _expect(model, mathopt.Model, "mathopt.Model")
    result = mathopt.solve(model, mathopt.SolverType[backend], params=mathopt.SolveParameters(time_limit=timedelta(seconds=float(time_limit))))
    reason = result.termination.reason.name
    status = {"OPTIMAL": "optimal", "FEASIBLE": "feasible", "INFEASIBLE": "infeasible", "UNBOUNDED": "unbounded",
              "INFEASIBLE_OR_UNBOUNDED": "infeasible_or_unbounded"}.get(reason, "error")
    if result.termination.limit and result.termination.limit.name == "TIME":
        status = "time_limit"
    if not result.has_primal_feasible_solution():
        return status, None, None
    return status, result.objective_value(), {v.name or f"x[{v.id}]": val for v, val in result.variable_values().items()}


def solve_native_cp_sat(model, time_limit):
    from ortools.sat.python import cp_model

    _expect(model, cp_model.CpModel, "cp_model.CpModel")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = 2
    code = solver.solve(model)
    status = {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "feasible", cp_model.INFEASIBLE: "infeasible",
              cp_model.UNKNOWN: "time_limit"}.get(code, "error")
    if code == cp_model.MODEL_INVALID:
        raise ModelError(model.validate() or solver.solution_info())
    if code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return status, None, None
    values = {variable.name or f"x[{i}]": solver.value(model.get_int_var_from_proto_index(i))
              for i, variable in enumerate(model.proto.variables)}
    return (status if model.has_objective() else "feasible"), (solver.objective_value if model.has_objective() else None), values


def solve_model_builder(model, time_limit, backend):
    from ortools.linear_solver.python import model_builder as mb

    _expect(model, mb.ModelBuilder, "model_builder.ModelBuilder")
    if backend.upper() in ('GLOP', 'PDLP', 'CLP', 'GUROBI_LP', 'GLPK_LP', 'CPLEX_LP', 'XPRESS_LP') and any(v.is_integral for v in model.get_variables()):
        raise ModelError(f"{backend} does not support integer variables; refusing to relax the model.")
    solver = mb.ModelSolver(backend)
    if not solver.solver_is_supported():
        raise ModelError(f"OR-Tools ModelBuilder backend {backend!r} is not available.")
    solver.set_time_limit_in_seconds(float(time_limit))
    code = solver.solve(model)
    status = {mb.SolveStatus.OPTIMAL: "optimal", mb.SolveStatus.FEASIBLE: "feasible", mb.SolveStatus.INFEASIBLE: "infeasible",
              mb.SolveStatus.UNBOUNDED: "unbounded"}.get(code, "error")
    if status not in ("optimal", "feasible"):
        return status, None, None
    return status, solver.objective_value, {v.name or f"x[{v.index}]": solver.value(v) for v in model.get_variables()}


def solve_routing(bundle, time_limit):
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    model, manager = bundle["model"], bundle["manager"]
    _expect(model, pywrapcp.RoutingModel, "RoutingModel")
    _expect(manager, pywrapcp.RoutingIndexManager, "RoutingIndexManager")
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.time_limit.FromMilliseconds(max(1, int(float(time_limit)*1000)))
    solution = model.SolveWithParameters(params)
    if solution is None:
        status = {routing_enums_pb2.RoutingSearchStatus.ROUTING_INFEASIBLE: "infeasible",
                  routing_enums_pb2.RoutingSearchStatus.ROUTING_FAIL_TIMEOUT: "time_limit"}.get(model.status(), "error")
        return status, None, None
    values = {}
    for vehicle in range(model.vehicles()):
        index, position = model.Start(vehicle), 0
        while not model.IsEnd(index):
            values[f"route[{vehicle},{position}]"] = manager.IndexToNode(index)
            index = solution.Value(model.NextVar(index))
            position += 1
        values[f"route[{vehicle},{position}]"] = manager.IndexToNode(index)
    status = "optimal" if model.status() == routing_enums_pb2.RoutingSearchStatus.ROUTING_OPTIMAL else "feasible"
    return status, solution.ObjectiveValue(), values


def solve_constraint(bundle, time_limit):
    from ortools.constraint_solver import pywrapcp

    model, variables = bundle["model"], bundle["variables"]
    _expect(model, pywrapcp.Solver, "pywrapcp.Solver")
    objective = bundle.get("objective")
    monitors, timed_out = [], False
    deadline = time.monotonic() + float(time_limit)

    def expired():
        nonlocal timed_out
        timed_out = time.monotonic() >= deadline
        return timed_out

    monitors.append(model.CustomLimit(expired))
    if objective is not None:
        monitors.append(model.Maximize(objective, 1) if bundle.get("sense", "min") == "max" else model.Minimize(objective, 1))
    decision = bundle.get("search") or model.Phase(variables, model.CHOOSE_FIRST_UNBOUND, model.ASSIGN_MIN_VALUE)
    model.NewSearch(decision, monitors)
    values, value = None, None
    try:
        while model.NextSolution():
            values = {v.Name() or f"x[{i}]": v.Value() for i, v in enumerate(variables)}
            value = objective.Value() if objective is not None else None
            if objective is None:
                break
    finally:
        model.EndSearch()
    if values is None:
        return ("time_limit" if timed_out else "infeasible"), None, None
    status = "time_limit" if timed_out else "optimal" if objective is not None else "feasible"
    return status, value, values


def solve_graph(model, time_limit, interface, backend):
    from ortools.algorithms.python import knapsack_solver
    from ortools.graph.python import linear_sum_assignment, max_flow, min_cost_flow

    if interface == "knapsack":
        native = knapsack_solver.KnapsackSolver(getattr(knapsack_solver.SolverType, backend), 'knapsack')
        native.init(model['values'], model['weights'], model['capacities'])
        count = len(model['values'])
        native.set_time_limit(float(time_limit))
        objective = native.solve()
        return ("optimal" if native.is_solution_optimal() else "feasible"), objective, {f"selected[{i}]": int(native.best_solution_contains(i)) for i in range(count)}
    native = model["model"] if isinstance(model, dict) else model
    kind = {"max_flow": max_flow.SimpleMaxFlow, "min_cost_flow": min_cost_flow.SimpleMinCostFlow,
            "assignment": linear_sum_assignment.SimpleLinearSumAssignment}[interface]
    _expect(native, kind, kind.__name__)
    if interface == "max_flow":
        code = native.solve(model["source"], model["sink"])
    elif interface == "min_cost_flow" and isinstance(model, dict) and model.get("maximize_flow"):
        code = native.solve_max_flow_with_min_cost()
    else:
        code = native.solve()
    if code != native.OPTIMAL:
        return ("infeasible" if code == getattr(native, 'INFEASIBLE', None) else "error"), None, None
    if interface == "assignment":
        return "optimal", native.optimal_cost(), {f"assignment[{i}]": native.right_mate(i) for i in range(native.num_nodes())}
    values = {f"flow[{native.tail(i)},{native.head(i)},{i}]": native.flow(i) for i in range(native.num_arcs())}
    return "optimal", (native.optimal_flow() if interface == "max_flow" else native.optimal_cost()), values


def solve_casadi(model, time_limit, interface, backend):
    import casadi as ca

    objective_sign = model.get('objective_sign', 1) if isinstance(model, dict) else 1
    if objective_sign not in (-1, 1):
        raise ModelError('CasADi objective_sign must be 1 or -1.')

    if interface in ("opti", "opti_conic"):
        custom = {}
        if isinstance(model, dict):
            custom = dict(model.get('options') or {})
            model = model['model']
        _expect(model, ca.Opti, "ca.Opti")
        options = {"print_time": False}
        native_options = {**custom, "print_level": 0, "sb": "yes", "max_wall_time": float(time_limit)} if backend == "ipopt" else custom
        model.solver(backend, options, native_options)
        try:
            result = model.solve_limited()
        except RuntimeError as error:
            if model.stats().get("return_status") == "Infeasible_Problem_Detected":
                return "locally_infeasible", None, None
            raise error
        stats = result.stats()
        success = stats.get("success", False)
        status = ("optimal" if interface == "opti_conic" else "locally_optimal") if success else "time_limit" if "exceeded" in stats.get("return_status", "").lower() else "error"
        if not success:
            return status, None, None
        values = {}
        for variable in ca.symvar(model.x):
            for i in range(variable.numel()):
                values[f"{variable.name()}[{i}]"] = result.value(ca.vec(variable)[i])
        return status, objective_sign * result.value(model.f), values
    _expect(model, dict, "CasADi problem dictionary")
    options = dict(model.get("options") or {})
    if backend == "ipopt":
        options["ipopt.max_wall_time"] = float(time_limit)
        options.setdefault("ipopt.print_level", 0)
    constructor = {"nlpsol": ca.nlpsol, "qpsol": ca.qpsol, "conic": ca.conic}[interface]
    solver = constructor("llm4om", backend, model["problem"], options)
    result = solver(**(model.get("arguments") or {}))
    stats = solver.stats()
    if not stats.get("success", False):
        status = "locally_infeasible" if stats.get("return_status") == "Infeasible_Problem_Detected" else "error"
        return status, None, None
    x = result["x"].full().ravel()
    objective = result["cost"] if interface == "conic" else result["f"]
    return ("locally_optimal" if interface == "nlpsol" else "optimal"), objective_sign * float(objective), {f"x[{i}]": value for i, value in enumerate(x)}


def model_target(model, library, backend):
    """Recognize native model objects; API syntax is not a run configuration."""
    defaults = {"pyomo": "highs", "gurobipy": "gurobi", "cpmpy": "ortools", "pulp": "PULP_CBC_CMD",
                "pyscipopt": "scip", "casadi": "ipopt", "coptpy": "copt", "cvxpy": "AUTO", "ortools": "SCIP"}
    api = 'model'
    if library == 'ortools':
        from ortools.constraint_solver import pywrapcp
        from ortools.graph.python import linear_sum_assignment, max_flow, min_cost_flow
        from ortools.linear_solver import pywraplp
        from ortools.linear_solver.python import model_builder
        from ortools.math_opt.python import mathopt
        from ortools.sat.python import cp_model
        native = model.get('model') if isinstance(model, dict) else model
        kinds = [(pywraplp.Solver, 'linear', 'AUTO'), (mathopt.Model, 'mathopt', 'GSCIP'),
                 (model_builder.ModelBuilder, 'model_builder', 'SCIP'), (cp_model.CpModel, 'cp_sat', 'CP_SAT'),
                 (pywrapcp.RoutingModel, 'routing', 'ROUTING'), (pywrapcp.Solver, 'constraint', 'CP'),
                 (max_flow.SimpleMaxFlow, 'max_flow', 'MAX_FLOW'), (min_cost_flow.SimpleMinCostFlow, 'min_cost_flow', 'MIN_COST_FLOW'),
                 (linear_sum_assignment.SimpleLinearSumAssignment, 'assignment', 'ASSIGNMENT')]
        if isinstance(model, dict) and 'weights' in model and 'capacities' in model:
            api, defaults[library] = 'knapsack', 'KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER'
        else:
            for kind, api_name, default in kinds:
                if isinstance(native, kind):
                    api, defaults[library] = api_name, default
                    break
            else:
                raise ModelError(f'Return a native OR-Tools model, with search arguments when required; got {type(native).__name__}.')
        if api in ('cp_sat', 'routing', 'constraint', 'max_flow', 'min_cost_flow', 'assignment') and backend not in ('AUTO', defaults[library]):
            raise ModelError(f'{api} uses its native {defaults[library]} backend, not {backend}.')
    elif library == 'pyomo':
        import pyomo.kernel as pmo
        api = 'kernel' if isinstance(model, pmo.block) else 'algebraic'
        if api == 'kernel':
            defaults[library] = 'cbc'
    elif library == 'cpmpy' and hasattr(model, 'user_vars'):
        defaults[library] = model.name
    elif library == 'cvxpy':
        api = 'dcp' if model.is_dcp() else 'dgp' if model.is_dgp() else 'dqcp'
    elif library == 'casadi':
        import casadi as ca
        if backend == 'AUTO' and isinstance(model, dict):
            defaults[library] = model.get('solver', 'ipopt')
        chosen = defaults[library] if backend == 'AUTO' else backend
        conic = 'Conic::'+chosen in ca.CasadiMeta.plugins().split(';')
        native = model.get('model') if isinstance(model, dict) else model
        if isinstance(native, ca.Opti):
            api = 'opti_conic' if conic else 'opti'
        else:
            api = 'conic' if 'h' in model.get('problem', {}) else 'qpsol' if conic else 'nlpsol'
    return api, defaults[library] if backend == 'AUTO' else backend


def solve_selected(model, time_limit, library, interface, backend):
    if library == "pyomo":
        return solve_pyomo(model, time_limit, backend, interface)
    if library == "cpmpy":
        return solve_cpmpy(model, time_limit, backend)
    if library == "pulp":
        return solve_pulp(model, time_limit, backend)
    if library == "cvxpy":
        return solve_cvxpy(model, time_limit, solver=backend, interface=interface)
    if library == "casadi":
        return solve_casadi(model, time_limit, interface, backend)
    if library == "ortools":
        if interface == "linear":
            return solve_ortools(model, time_limit, backend)
        if interface == "mathopt":
            return solve_mathopt(model, time_limit, backend)
        if interface == "model_builder":
            return solve_model_builder(model, time_limit, backend)
        if interface == "cp_sat":
            return solve_native_cp_sat(model, time_limit)
        if interface == "routing":
            return solve_routing(model, time_limit)
        if interface == "constraint":
            return solve_constraint(model, time_limit)
        return solve_graph(model, time_limit, interface, backend)
    native = {"gurobipy": ("gurobi", solve_gurobi), "pyscipopt": ("scip", solve_scip), "coptpy": ("copt", solve_copt)}
    expected, solve = native[library]
    if backend != expected:
        raise ModelError(f"{library} uses its native {expected} backend; {backend!r} is not supported.")
    return solve(model, time_limit)


def backend_catalog():
    """Discover native plugins in the execution environment, including optional unavailable backends."""
    import casadi as ca
    import cpmpy as cp
    import cvxpy as cvx
    import pulp
    import pyomo.environ as pyo
    from ortools.algorithms.python import knapsack_solver
    from ortools.linear_solver import pywraplp
    from ortools.linear_solver.python import model_builder
    from ortools.math_opt.python import mathopt

    def entry(name, check, detail=""):
        try:
            available = bool(check())
        except Exception as error:
            available = False
            detail = str(error)[-350:]
        return {"id": name, "available": available, "detail": detail if detail else "" if available else "Optional package, executable or license is unavailable."}

    pyomo = []
    for name in pyo.SolverFactory:
        module = pyo.SolverFactory.get_class(name).__module__
        # Root finders and decomposition algorithms are not execution engines.
        if name.startswith('_') or name in ('py', 'asl') or not (module.startswith(('pyomo.solvers.plugins.solvers', 'pyomo.contrib.solver.', 'pyomo.contrib.appsi.')) or name == 'cyipopt'):
            continue
        pyomo.append(entry(name, lambda n=name: pyomo_solver(n).available(exception_flag=False)))
    cpmpy = []
    for name, cls in cp.SolverLookup.base_solvers():
        item = entry(name, cls.supported)
        cpmpy.append(item)
        if item["available"] and hasattr(cls, "solvernames"):
            for subname in cls.solvernames(installed=True):
                cpmpy.append({"id": name+":"+subname, "available": True, "detail": ""})
    pulp_backends = [entry(name, lambda n=name: pulp.getSolver(n, msg=False).available()) for name in dict.fromkeys(pulp.listSolvers())]
    installed = set(cvx.installed_solvers())
    # CVXPY's GLOP/PDLP adapters require OR-Tools <9.15. Only those solves use the separately installed version.
    if os.path.isdir("/opt/ortools-cvxpy"):
        installed.update(("GLOP", "PDLP"))
    cvxpy = [{"id": name, "available": name in installed, "detail": "" if name in installed else "Install the optional CVXPY backend and its runtime dependencies."}
             for name in dict.fromkeys(cvx.settings.SOLVERS)]
    cvxpy.insert(0, {"id": "AUTO", "available": True, "detail": "CVXPY selects a compatible installed solver."})
    mpsolvers = []
    for name in dir(pywraplp.Solver):
        if not name.endswith('_PROGRAMMING'):
            continue
        alias = name.replace('_MIXED_INTEGER_PROGRAMMING', '').replace('_INTEGER_PROGRAMMING', '').replace('_LINEAR_PROGRAMMING', '')
        if name.startswith(('GUROBI_', 'GLPK_', 'CPLEX_', 'XPRESS_')):
            alias += '_LP' if '_LINEAR_' in name else '_MIP'
        mpsolvers.append(entry(alias, lambda n=name: pywraplp.Solver.SupportsProblemType(getattr(pywraplp.Solver, n))))
    mathopt_solvers = []
    for value in mathopt.SolverType:
        def supported(value=value):
            mathopt.solve(mathopt.Model(), value, params=mathopt.SolveParameters(time_limit=timedelta(seconds=1)))
            return True
        mathopt_solvers.append(entry(value.name, supported))
    builder_names = list(dict.fromkeys([item['id'] for item in mpsolvers]+['HIGHS', 'GUROBI', 'CP_SAT', 'SAT']))
    builders = [entry(name, lambda n=name: model_builder.ModelSolver(n).solver_is_supported()) for name in builder_names]
    casadi = {"Nlpsol": [], "Conic": []}
    for plugin in ca.CasadiMeta.plugins().split(';'):
        family, name = plugin.split('::', 1)
        if family not in casadi:
            continue

        def loadable(family=family, name=name):
            # Some optional native plugins abort instead of raising when an external library is missing.
            code = f"import casadi as ca; print(ca.has_{'nlpsol' if family == 'Nlpsol' else 'conic'}({name!r}))"
            probe = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, timeout=5,
                                   env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
            return probe.returncode == 0 and probe.stdout.rstrip().endswith(b'True')

        casadi[family].append(entry(name, loadable))
    def native(name):
        return [{"id": name, "available": True, "detail": ""}]
    knapsack = []
    for name in dir(knapsack_solver):
        if name.startswith('KNAPSACK_'):
            def supported(name=name):
                solver = knapsack_solver.KnapsackSolver(getattr(knapsack_solver, name), 'probe')
                solver.init([1], [[1]], [1])
                return solver.solve() == 1
            knapsack.append(entry(name, supported))
    def unique(rows):
        found = {}
        for row in rows:
            if row['id'] not in found or row['available']:
                found[row['id']] = row
        return [dict(id='AUTO', available=True, detail='Use the native model/backend defaults.')]+[row for row in found.values() if row['id'] != 'AUTO']

    return {"libraries": {
        "pyomo": unique(pyomo), "gurobipy": unique(native('gurobi')),
        "ortools": unique(mpsolvers+mathopt_solvers+builders+knapsack+[
            row for name in ('CP_SAT', 'ROUTING', 'CP', 'MAX_FLOW', 'MIN_COST_FLOW', 'ASSIGNMENT') for row in native(name)]),
        "cpmpy": unique(cpmpy), "pulp": unique(pulp_backends), "cvxpy": unique(cvxpy),
        "pyscipopt": unique(native('scip')), "casadi": unique(casadi['Nlpsol']+casadi['Conic']),
        "coptpy": unique(native('copt')),
    }}


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
    library, backend = request['language'], request['solver']
    result = {"status": "error", "objective": None, "variables": {}, "output": "", "error": None, "diagnosis": None,
              "solver": backend}
    output = io.StringIO()
    stage = "build"
    if library == "cvxpy":
        if backend in ("GLOP", "PDLP") and os.path.isdir("/opt/ortools-cvxpy"):
            sys.path.insert(0, "/opt/ortools-cvxpy")
        __import__('cvxpy')
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
            interface, backend = model_target(model, library, backend)
            result["solver"] = model.SolverVersion().split()[0].upper() if library == "ortools" and interface == "linear" and backend == "AUTO" else backend
            status, objective, values = solve_selected(model, request.get("time_limit", 60), library, interface, backend)
            if library == 'cvxpy' and model.solver_stats:
                result['solver'] = model.solver_stats.solver_name
            if status == "infeasible":
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result["diagnosis"] = diagnose('pywraplp' if library == 'ortools' and interface == 'linear' else library, model)
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
    if request.get('catalog'):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = backend_catalog()
        except Exception as error:
            result = {"error": describe_error(error)}
    else:
        result = run_script(request) if "script" in request else run(request)
    sys.stdout.write("\n" + RESULT_MARKER + json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
