"""Executable native API examples used by integration tests."""

from llm4om.code_prompts import REFERENCES as ORTOOLS

REFERENCES = {
    **ORTOOLS,
    "pyomo.kernel": '''import pyomo.kernel as pmo
def build_model(data):
    m = pmo.block()
    m.x = pmo.variable(domain=pmo.NonNegativeReals)
    m.limit = pmo.constraint(m.x >= 2)
    m.objective = pmo.objective(m.x)
    return m
Use kernel blocks, variables and constraints consistently; do not mix kernel and environ components.''',
    "gurobipy.matrix": '''import gurobipy as gp
from gurobipy import GRB
import numpy as np
def build_model(data):
    m = gp.Model()
    x = m.addMVar(2, lb=0, vtype=GRB.INTEGER, name="x")
    m.addConstr(np.array([[2,1],[1,2]]) @ x <= np.array([8,8]))
    m.setObjective(np.array([3,2]) @ x, GRB.MAXIMIZE)
    return m
The matrix and scalar APIs can be combined. General, quadratic and nonlinear constraints use the native API.''',
    "ortools.model_builder": '''from ortools.linear_solver.python import model_builder
def build_model(data):
    m = model_builder.ModelBuilder()
    x = m.new_int_var(0, 10, "x")
    m.add(x <= 4)
    m.maximize(3*x)
    return m
Return ModelBuilder. Bounds use float("inf") or finite numbers; ModelBuilder has no infinity() method.
Do not instantiate ModelSolver or solve the model.''',
    "cpmpy.solver": '''import cpmpy as cp
def build_model(data):
    x = cp.intvar(0, 10, shape=2, name="x")
    s = cp.SolverLookup.get("{solver}")
    s += 2*x[0]+x[1] <= 8
    s += x[0]+2*x[1] <= 8
    s.maximize(3*x[0]+2*x[1])
    return s
Return the selected CPMpy SolverInterface without solving. Scalar/array variables and global constraints
are supported through the selected backend's native CPMpy transformations. A model can have no objective.''',
    "pulp.column": '''import pulp
def build_model(data):
    m = pulp.LpProblem("column_model", pulp.LpMinimize)
    obj = pulp.LpConstraintVar("objective")
    row = pulp.LpConstraintVar("demand", pulp.LpConstraintGE, 2)
    m.setObjective(obj)
    m += row
    pulp.LpVariable("x", lowBound=0, e=3*obj + row)
    return m
Return LpProblem. LpConstraintVar and the variable's e argument implement PuLP's column-oriented API.
Do not call solve().''',
    "cvxpy.dgp": '''import cvxpy as cp
def build_model(data):
    x = cp.Variable(pos=True, name="x")
    y = cp.Variable(pos=True, name="y")
    return cp.Problem(cp.Minimize(1/(x*y)), [x+y <= 2])
Return a log-log convex DGP Problem. Variables in geometric expressions must be strictly positive.
The platform calls solve(gp=True). Do not logarithmically transform the model manually or solve it.''',
    "cvxpy.dqcp": '''import cvxpy as cp
def build_model(data):
    x = cp.Variable(nonneg=True, name="x")
    y = cp.Variable(pos=True, name="y")
    return cp.Problem(cp.Minimize(x/y), [x >= 1, x <= 4, y >= 1, y <= 2])
Return a DQCP Problem; the platform calls solve(qcp=True) using CVXPY's native bisection.
Declare nonneg=True or pos=True on variables with known nonnegative/positive signs; explicit lower-bound
constraints do not give CVXPY the sign metadata needed to recognize a ratio as DQCP.
Use atoms supported by DQCP. Do not solve or implement bisection yourself.''',
    "pyscipopt.matrix": '''from pyscipopt import Model
import numpy as np
def build_model(data):
    m = Model()
    x = m.addMatrixVar(shape=2, vtype="I", lb=0, name="x")
    m.addMatrixCons(np.array([[2,1],[1,2]]) @ x <= np.array([8,8]))
    m.setObjective(np.array([3,2]) @ x, "maximize")
    return m
Return Model. Scalar and matrix expressions can be combined. Nonlinear objectives need an auxiliary
variable and a correctly directed epigraph/hypograph constraint. Do not optimize().''',
    "casadi.opti_conic": '''import casadi as ca
def build_model(data):
    m = ca.Opti("conic")
    x = m.variable(2)
    m.minimize(ca.sumsqr(x))
    m.subject_to(x[0]+x[1] == 2)
    return m
Return Opti("conic"), for linear/quadratic objectives with linear constraints. Do not set solver() or solve().
Opti assigns names automatically. Use variable() or variable(n); the third argument is a type (full/symmetric),
not a variable name. Explain the native variable components in the formulation.''',
    "casadi.nlpsol": '''import casadi as ca
def build_model(data):
    x = ca.MX.sym("x", 2)
    nlp = {"x": x, "f": ca.sumsqr(x-1), "g": x[0]+x[1]}
    return {"problem": nlp, "arguments": {"x0": [0,0], "lbx": [0,0], "ubx": [3,3], "lbg": 2, "ubg": 2}}
Return symbolic problem and numerical arguments for CasADi nlpsol; do not create or call a solver.
MX and SX are both supported. Results use x[i] in native decision-vector order; explain that order in the formulation.
Optional options contains native plugin construction options such as discrete flags or algorithm settings.
Nonconvex NLP success generally proves only a local solution.''',
    "casadi.qpsol": '''import casadi as ca
def build_model(data):
    x = ca.SX.sym("x", 2)
    return {"problem": {"x": x, "f": ca.sumsqr(x), "g": x[0]+x[1]},
            "arguments": {"lbx": [0,0], "ubx": [3,3], "lbg": 2, "ubg": 2}}
Return symbolic problem and numerical arguments for qpsol. The objective is quadratic and constraints linear.
Results use x[i] in native decision-vector order. Optional options contains native plugin options. Do not solve.''',
    "casadi.conic": '''import casadi as ca
def build_model(data):
    h = ca.DM.eye(2)*2
    a = ca.DM([[1,1]])
    return {"problem": {"h": h.sparsity(), "a": a.sparsity()},
            "arguments": {"h": h, "a": a, "g": [0,0], "lbx": [0,0], "ubx": [3,3], "lba": 2, "uba": 2}}
Return the sparsity structure and numeric conic arguments. The QP objective is 0.5*x.T@h@x + g.T@x.
Use native SOC/SDP structures only if the selected plugin supports them. Results use x[i] in decision-vector order;
optional options contains native plugin options. Do not create or call a solver.''',
    "coptpy.matrix": '''import coptpy as cp
from coptpy import COPT
import numpy as np
def build_model(data):
    m = cp.Envr().createModel("production")
    x = m.addMVar(2, lb=0, vtype=COPT.INTEGER, nameprefix="x")
    m.addMConstr(np.array([[2,1],[1,2]]), x, COPT.LESS_EQUAL, np.array([8,8]))
    m.setObjective(np.array([3,2]) @ x, COPT.MAXIMIZE)
    return m
Return coptpy.Model. Scalar and matrix APIs can be mixed. Use native quadratic/conic constraints when needed.
Do not call solve().''',
}
