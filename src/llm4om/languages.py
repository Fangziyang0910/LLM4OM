"""Each code target pairs a modeling interface with its solver; generated code only builds the model."""

from dataclasses import dataclass

CONTRACT = """\
## Code contract
- Write Python code that defines `build_model(data)` and returns the {model_type}.
- `data` maps each attached data file name to its text content (CSV or JSON). Parse it yourself. \
When no file is attached, `data` is empty; take the numbers from the problem description.
- Do not solve the model and do not print the solution. The platform solves it with {solver} and reports the result.
- Do not read files, environment variables or the network.
- {objective} Python control flow must not depend on variable values.
- Give variables readable names that include their indices, because results are reported by variable name."""

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
- Return ca.Opti, not an NLP dictionary or a solver function. Do not call solver() or solve().
- Ipopt finds a local solution; it does not establish global optimality for nonconvex problems. No integer variables.
- Use smooth CasADi expressions. Maximize f by minimizing -f; state clearly that the reported objective is -f.
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


STARTER = '''{imports}

def build_model(data):
    """
    Args:
        data: dict, maps each attached data file name to its text content (CSV or JSON); empty when no file is attached
    Returns:
        model: {model_type}. Do not solve it; the platform solves it with {solver}.
    """
    model = {constructor}
    # To be implemented
    return model
'''


ONE_OBJECTIVE = "The model has exactly one objective."
CP_OBJECTIVE = "The model has at most one objective; without one it is a satisfaction problem."


@dataclass(frozen=True)
class Language:
    id: str
    name: str  # the library as users know it
    solver: str  # the solver that runs this language
    library: str  # the name prompts use for the code, e.g. "Gurobi" in "write Gurobi code"
    reference: str
    imports: str  # the rest feeds the starter code
    model_type: str
    constructor: str
    objective: str = ONE_OBJECTIVE


LANGUAGES = {
    "pyomo": Language("pyomo", "Pyomo", "HiGHS", "Pyomo", PYOMO, "import pyomo.environ as pyo",
                      "pyo.ConcreteModel", "pyo.ConcreteModel()"),
    "gurobipy": Language("gurobipy", "gurobipy", "Gurobi", "Gurobi", GUROBIPY,
                         "import gurobipy as gp\nfrom gurobipy import GRB", "gp.Model", 'gp.Model("model")'),
    "pywraplp": Language("pywraplp", "OR-Tools pywraplp", "SCIP", "OR-Tools", ORTOOLS,
                         "from ortools.linear_solver import pywraplp", "pywraplp.Solver",
                         'pywraplp.Solver.CreateSolver("SCIP")'),
    "cpmpy": Language("cpmpy", "CPMpy", "OR-Tools CP-SAT", "CPMpy", CPMPY, "import cpmpy as cp",
                      "cp.Model", "cp.Model()", CP_OBJECTIVE),
    "pulp": Language("pulp", "PuLP", "CBC", "PuLP", PULP, "import pulp", "pulp.LpProblem",
                     'pulp.LpProblem("model", pulp.LpMinimize)'),
    "cvxpy": Language("cvxpy", "CVXPY", "Clarabel", "CVXPY", cvxpy_reference("Clarabel",
                      "Continuous convex LP, QP, SOCP, exponential/power cones and SDP; no integer or Boolean variables."),
                      "import cvxpy as cp\nimport numpy as np",
                      "cp.Problem", "cp.Problem(cp.Minimize(0))"),
    "pyscipopt": Language("pyscipopt", "PySCIPOpt", "SCIP", "PySCIPOpt", PYSCIPOPT,
                          "from pyscipopt import Model, quicksum", "pyscipopt.Model", 'Model("model")'),
    "casadi": Language("casadi", "CasADi", "Ipopt", "CasADi", CASADI, "import casadi as ca", "ca.Opti", "ca.Opti()"),
    "coptpy": Language("coptpy", "coptpy", "COPT", "COPT", COPT, "import coptpy as cp\nfrom coptpy import COPT",
                        "coptpy.Model", 'cp.Envr().createModel("model")'),
    **{key: Language(key, "CVXPY", solver, "CVXPY", cvxpy_reference(solver, capability),
                     "import cvxpy as cp\nimport numpy as np", "cp.Problem", "cp.Problem(cp.Minimize(0))")
       for key, solver, capability in [
           ("cvxpy_osqp", "OSQP", "Continuous convex quadratic objectives with linear constraints only; no integer variables or cones."),
           ("cvxpy_scs", "SCS", "Continuous convex conic optimization including SDP, exponential and power cones; no integer variables."),
           ("cvxpy_mosek", "MOSEK", "Convex LP/QP and conic optimization, including mixed integer conic models; no mixed integer SDP. A MOSEK license is required."),
       ]},
}
# For methods whose original prompts ask for (MI)LP. CVXPY is left out: Clarabel has no integer variables.
MILP_LANGUAGES = frozenset({"pyomo", "gurobipy", "pywraplp", "pulp"})


@dataclass(frozen=True)
class CodeTarget:
    language: str

    def __post_init__(self) -> None:
        if self.language not in LANGUAGES:
            raise ValueError(f"Unknown code language {self.language!r}; choose one of {sorted(LANGUAGES)}.")

    @property
    def prompt(self) -> str:
        """Instructions that make generated code fit this language and its solver."""
        language = LANGUAGES[self.language]
        return CONTRACT.format(model_type=language.model_type, solver=language.solver,
                               objective=language.objective) + "\n\n" + language.reference

    @property
    def library(self) -> str:
        return LANGUAGES[self.language].library

    @property
    def starter(self) -> str:
        """An empty `build_model` stating its interface, for methods whose prompts take a starter code."""
        language = LANGUAGES[self.language]
        return STARTER.format(imports=language.imports, model_type="a " + language.model_type, solver=language.solver,
                              constructor=language.constructor)
