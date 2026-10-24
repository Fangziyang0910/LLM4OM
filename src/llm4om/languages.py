"""Nine modeling libraries and their native code contracts. API choice stays in the code."""

import re
from dataclasses import dataclass

from llm4om.code_prompts import REFERENCES

CONTRACT = """\
## Code contract
- Write Python code that defines `build_model(data)` and returns the {model_type}.
- `data` maps each attached data file name to its text content (CSV or JSON). Parse it yourself. \
When no file is attached, `data` is empty; take the numbers from the problem description.
- Do not solve the model and do not print the solution. The platform solves it with {solver} and reports the result.
- Do not read files, environment variables or the network.
- {objective} Python control flow must not depend on variable values.
- Where the native API supports explicit names, give variables readable indexed names. Otherwise use the native \
variable order and explain its components in the formulation; do not invent unsupported name arguments."""

PYOMO = """\
## Pyomo reference (solved with HiGHS)
```python
import pyomo.environ as pyo

def build_model(data):
    products = ["A", "B"]
    profit = {"A": 3, "B": 2}
    m = pyo.ConcreteModel()
    m.P = pyo.Set(initialize=products)
    m.x = pyo.Var(m.P, domain=pyo.NonNegativeIntegers)   # NonNegativeReals, Binary, Reals, bounds=(lo, hi)
    m.profit = pyo.Objective(expr=sum(profit[p] * m.x[p] for p in m.P), sense=pyo.maximize)
    m.cutting = pyo.Constraint(expr=2 * m.x["A"] + m.x["B"] <= 8)
    m.demand = pyo.Constraint(m.P, rule=lambda m, p: m.x[p] >= 0)  # indexed constraint
    return m
```
- Use `pyo.Constraint.Skip` inside a rule to omit an index.
- Use `pyo.quicksum` or `sum` for sums. Do not use `pyo.value()` on variables while building."""

GUROBIPY = """\
## gurobipy reference
```python
import gurobipy as gp
from gurobipy import GRB

def build_model(data):
    products = ["A", "B"]
    profit = {"A": 3, "B": 2}
    m = gp.Model("production")
    x = m.addVars(products, vtype=GRB.INTEGER, lb=0, name="x")   # GRB.CONTINUOUS, GRB.BINARY
    m.setObjective(gp.quicksum(profit[p] * x[p] for p in products), GRB.MAXIMIZE)
    m.addConstr(2 * x["A"] + x["B"] <= 8, name="cutting")
    m.addConstrs((x[p] >= 0 for p in products), name="demand")
    return m
```
- Do not call `m.optimize()`; the platform solves the model."""

ORTOOLS = """\
## OR-Tools pywraplp reference (solved with SCIP)
```python
from ortools.linear_solver import pywraplp

def build_model(data):
    products = ["A", "B"]
    profit = {"A": 3, "B": 2}
    solver = pywraplp.Solver.CreateSolver("SCIP")
    x = {p: solver.IntVar(0, solver.infinity(), f"x[{p}]") for p in products}   # NumVar, BoolVar(name)
    solver.Maximize(sum(profit[p] * x[p] for p in products))                      # solver.Minimize(...)
    solver.Add(2 * x["A"] + x["B"] <= 8, "cutting")
    for p in products:
        solver.Add(x[p] >= 0, f"demand[{p}]")
    return solver
```
- Return the `pywraplp.Solver`. Do not call `solver.Solve()`; the platform solves the model.
- Build sums with `sum(...)` or `solver.Sum(...)`. Variables are linear: no products of variables."""


CPMPY = """\
## CPMpy reference (solved with OR-Tools CP-SAT)
```python
import cpmpy as cp

def build_model(data):
    products = ["A", "B"]
    profit = [3, 2]
    x = cp.intvar(0, 100, shape=len(products), name="x")   # cp.boolvar(shape=..., name=...); every intvar needs bounds
    m = cp.Model()
    m += 2 * x[0] + x[1] <= 8
    m += x[0] + 2 * x[1] <= 8
    m += cp.AllDifferent(x)                                  # global constraints: AllDifferent, Element, Table, Cumulative, ...
    m.maximize(cp.sum(profit[i] * x[i] for i in range(len(products))))
    return m
```
- Return the `cp.Model`. Do not call `m.solve()`; the platform solves the model.
- Variables are integers or Booleans with finite bounds; there are no continuous variables. Scale fractional data to \
integers. Use `a.implies(b)`, `&`, `|`, `~` for logic and index arrays of variables with variables for Element."""


PULP = """\
## PuLP reference (solved with CBC)
```python
import pulp

def build_model(data):
    products = ["A", "B"]
    profit = {"A": 3, "B": 2}
    problem = pulp.LpProblem("production", pulp.LpMaximize)                                 # pulp.LpMinimize
    x = pulp.LpVariable.dicts("x", products, lowBound=0, cat="Integer")                      # "Continuous", "Binary"
    problem += pulp.lpSum(profit[p] * x[p] for p in products)                                # the objective comes first
    problem += 2 * x["A"] + x["B"] <= 8, "cutting"                                           # (constraint, name)
    for p in products:
        problem += x[p] >= 0, f"demand_{p}"
    return problem
```
- Return the `pulp.LpProblem`. Do not call `problem.solve()`; the platform solves the model.
- The first expression added without a comparison is the objective. Constraint names must be unique and use letters, \
digits and `_`. Variables are linear: no products of variables."""


CVXPY = """\
## CVXPY reference (solved with {solver})
```python
import cvxpy as cp
import numpy as np

def build_model(data):
    target = np.array([1.0, 2.0])
    x = cp.Variable(2, name="x", nonneg=True)                        # shape (n,) or (m, n); name every variable
    objective = cp.Minimize(cp.sum_squares(x - target))               # cp.Maximize(concave expression)
    constraints = [cp.sum(x) <= 2, x[0] >= 0.2]
    return cp.Problem(objective, constraints)
```
- Return the `cp.Problem`. Do not call `problem.solve()`; the platform solves the model.
- {capability} The problem must follow CVXPY's disciplined convex programming rules.
- Use `@` for matrix products, `cp.sum`, `cp.norm`, `cp.quad_form` and other CVXPY atoms; do not use Python `max`, \
`abs` or `if` on expressions."""


PYSCIPOPT = """\
## Native SCIP through PySCIPOpt
```python
from pyscipopt import Model, quicksum

def build_model(data):
    model = Model("production")
    x = {p: model.addVar(name=f"x[{p}]", vtype="I", lb=0) for p in "AB"}
    model.setObjective(3*x["A"] + 2*x["B"], "maximize")
    model.addCons(2*x["A"] + x["B"] <= 8, name="cutting")
    model.addCons(x["A"] + 2*x["B"] <= 8, name="machining")
    return model
```
- Supports mixed integer linear and nonlinear constraints. Types: "C", "I", "B"; lb=None allows negative infinity.
- The objective must be linear. Express a nonlinear objective with an auxiliary variable and an epigraph/hypograph \
constraint with the correct direction. Do not call optimize()."""


CASADI = """\
## CasADi Opti with Ipopt (smooth continuous nonlinear optimization)
```python
import casadi as ca

def build_model(data):
    model = ca.Opti()
    x = model.variable(2)
    model.minimize((1-x[0])**2 + 100*(x[1]-x[0]**2)**2)
    model.subject_to(model.bounded(-2, x, 2))
    model.set_initial(x, [0, 0])
    return model
```
- This example returns ca.Opti. The native problem dictionaries described below are also supported. Do not call solve().
- Ipopt finds a local solution; it does not establish global optimality for nonconvex problems. Integer variables require a compatible plugin such as Bonmin, not Ipopt.
- Use smooth CasADi expressions. To maximize f minimize -f and return {"model": model, "objective_sign": -1}.
- Opti assigns variable names automatically (e.g. opti0_x_1); explain their components in the formulation.
- Set useful initial guesses and finite bounds when the problem gives them."""


COPT = """\
## COPT through coptpy
```python
import coptpy as cp
from coptpy import COPT

def build_model(data):
    model = cp.Envr().createModel("production")
    x = model.addVars(["A", "B"], vtype=COPT.INTEGER, lb=0, nameprefix="x")
    model.setObjective(3*x["A"] + 2*x["B"], COPT.MAXIMIZE)
    model.addConstr(2*x["A"] + x["B"] <= 8, name="cutting")
    model.addConstr(x["A"] + 2*x["B"] <= 8, name="machining")
    return model
```
- Supports LP, MILP, convex quadratic and conic optimization. Use coptpy expressions, cp.quicksum, COPT.CONTINUOUS, \
COPT.BINARY and COPT.INFINITY. Do not call solve()."""


def cvxpy_reference(solver: str, capability: str) -> str:
    return CVXPY.format(solver=solver, capability=capability)


ONE_OBJECTIVE = "The model has exactly one objective."
CP_OBJECTIVE = "The model has at most one objective; without one it is a satisfaction problem."


@dataclass(frozen=True)
class Language:
    id: str
    name: str
    solver: str  # the default engine when code does not select one
    library: str
    reference: str
    model_type: str
    objective: str = ONE_OBJECTIVE


LANGUAGES = {
    "pyomo": Language("pyomo", "Pyomo", "highs", "Pyomo", PYOMO, "instantiated Pyomo model or kernel block"),
    "gurobipy": Language("gurobipy", "gurobipy", "gurobi", "Gurobi", GUROBIPY, "gp.Model"),
    "ortools": Language("ortools", "OR-Tools", "SCIP", "OR-Tools", ORTOOLS,
                        "native OR-Tools model (with search arguments when needed)", CP_OBJECTIVE),
    "cpmpy": Language("cpmpy", "CPMpy", "ortools", "CPMpy", CPMPY,
                      "cp.Model or native CPMpy SolverInterface", CP_OBJECTIVE),
    "pulp": Language("pulp", "PuLP", "PULP_CBC_CMD", "PuLP", PULP, "pulp.LpProblem"),
    "cvxpy": Language("cvxpy", "CVXPY", "AUTO", "CVXPY", CVXPY, "cp.Problem"),
    "pyscipopt": Language("pyscipopt", "PySCIPOpt", "scip", "PySCIPOpt", PYSCIPOPT,
                          "pyscipopt.Model"),
    "casadi": Language("casadi", "CasADi", "ipopt", "CasADi", CASADI, "ca.Opti or a native solver dictionary"),
    "coptpy": Language("coptpy", "coptpy", "copt", "COPT", COPT, "coptpy.Model"),
}
LEGACY_TARGETS = {"pywraplp": ("ortools", "SCIP"),
                  **{"cvxpy_"+solver.lower(): ("cvxpy", solver) for solver in ("OSQP", "SCS", "MOSEK")}}

# Native APIs are code choices, not another run setting.
API_NOTES = {
    "pyomo": "ConcreteModel, instantiated AbstractModel and pyomo.kernel blocks are supported. Return the native object.",
    "gurobipy": "Both scalar/expression and matrix APIs return the same gp.Model; use either or combine them.",
    "pulp": "Both row-oriented and column-oriented modeling return the same LpProblem; use either.",
    "pyscipopt": "Scalar and matrix APIs return the same Model; use either or combine them.",
    "coptpy": "Scalar and matrix APIs return the same Model; use either or combine them.",
    "cpmpy": "Scalar/array expressions and a direct SolverLookup interface are supported. Return Model or SolverInterface.",
    "cvxpy": "DCP, DGP and DQCP are detected from the Problem. Use explicit sign attributes for geometric/quasiconvex expressions.",
    "ortools": """Use MPSolver, MathOpt Model, CpModel or ModelBuilder as appropriate; return the native object.
For Routing return {"model": RoutingModel, "manager": RoutingIndexManager}.
For the original constraint solver return {"model": Solver, "variables": [IntVar, ...], "objective": optional IntVar, "sense": "min"/"max"}; search is an optional native DecisionBuilder.
For maximum flow return {"model": SimpleMaxFlow, "source": int, "sink": int}.
Return SimpleMinCostFlow (or {"model": model, "maximize_flow": True}) or SimpleLinearSumAssignment directly.
For knapsack return {"values": [...], "weights": [[...], ...], "capacities": [...]}.
The platform recognizes the returned model; there is no separate interface setting.""",
    "casadi": """Opti supports integer variables with set_domain(x, "integer") and a mixed-integer plugin such as Bonmin. Return {"model": opti, "solver": "bonmin"} for these models.
For maximization minimize -f and include "objective_sign": -1 in the returned dictionary to report the original objective.
Opti and Opti('conic') are supported. For Opti('conic'), return {"model": opti, "solver": "qrqp"}; optional native options use "options".
For nlpsol/qpsol/conic return {"problem": the native symbolic problem or sparsity structure, "arguments": its native numerical arguments, "solver": the plugin name, "options": optional native options}.
The platform uses the selected native plugin; do not call it to solve. Result variables follow native decision-vector order x[i].""",
}


@dataclass(frozen=True)
class CodeTarget:
    language: str
    solver: str | None = None

    def __post_init__(self) -> None:
        if self.language in LEGACY_TARGETS:
            library, solver = LEGACY_TARGETS[self.language]
            object.__setattr__(self, "language", library)
            object.__setattr__(self, "solver", self.solver or solver)
        if self.language not in LANGUAGES:
            raise ValueError(f"Unknown code language {self.language!r}; choose one of {sorted(LANGUAGES)}.")
        object.__setattr__(self, "solver", self.solver or "AUTO")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", self.solver):
            raise ValueError("Use a native solver identifier, not a path or command.")

    @property
    def prompt(self) -> str:
        definition = LANGUAGES[self.language]
        backend = definition.solver if self.solver == "AUTO" else self.solver
        reference = definition.reference.replace("{solver}", backend)
        if self.language == "cvxpy":
            mip = backend.upper() in {"AUTO", "SCIP", "SCIPY", "GUROBI", "CPLEX", "COPT", "MOSEK", "CBC", "GLPK_MI", "ECOS_BB", "XPRESS", "HIGHS"}
            capability = "Integer/Boolean variables require a compatible mixed-integer backend." if mip else "Continuous variables only; no integer or Boolean variables."
            if backend == "OSQP":
                capability += " Only quadratic objectives and linear constraints; no other cones."
            reference = cvxpy_reference(backend, capability).replace("The problem must follow CVXPY's disciplined convex programming rules.", "Use the native DCP, DGP or DQCP rules as appropriate.")
        elif self.language == "ortools":
            key = {"GSCIP": "mathopt", "HIGHS": "mathopt", "CP_SAT": "cp_sat", "ROUTING": "routing", "CP": "constraint",
                   "MAX_FLOW": "max_flow", "MIN_COST_FLOW": "min_cost_flow", "ASSIGNMENT": "assignment"}.get(backend)
            if backend.startswith("KNAPSACK_"):
                key = "knapsack"
            reference = REFERENCES["ortools."+key].replace("{solver}", backend) if key else reference.replace('"SCIP"', '"'+backend+'"').replace("with SCIP", "with "+backend)
        elif self.language == "pyomo":
            reference = reference.replace("with HiGHS", "with "+backend)
        elif self.language == "cpmpy":
            reference = reference.replace("with OR-Tools CP-SAT", "with "+("OR-Tools CP-SAT" if backend == "ortools" else backend))
        elif self.language == "pulp":
            reference = reference.replace("with CBC", "with "+backend)
        elif self.language == "casadi":
            reference = reference.replace("with Ipopt", "with "+backend)
        return CONTRACT.format(model_type=definition.model_type, solver=self.solver, objective=definition.objective) + "\n\n" + reference + "\n" + API_NOTES[self.language]

    @property
    def library(self) -> str:
        return LANGUAGES[self.language].library
