"""Native OR-Tools examples for code generation; API choice stays in the code."""

REFERENCES = {
    "ortools.mathopt": '''from ortools.math_opt.python import mathopt
def build_model(data):
    m = mathopt.Model(name="production")
    a = m.add_integer_variable(lb=0, name="A")
    b = m.add_integer_variable(lb=0, name="B")
    m.add_linear_constraint(2*a+b <= 8)
    m.add_linear_constraint(a+2*b <= 8)
    m.maximize(3*a+2*b)
    return m
Return mathopt.Model. Do not call mathopt.solve(); the platform selects the requested backend.''',
    "ortools.cp_sat": '''from ortools.sat.python import cp_model
def build_model(data):
    m = cp_model.CpModel()
    x = [m.new_int_var(0, 10, f"x[{i}]") for i in range(2)]
    m.add(2*x[0]+x[1] <= 8)
    m.add(x[0]+2*x[1] <= 8)
    m.maximize(3*x[0]+2*x[1])
    return m
Return CpModel, not CpSolver. Integer/Boolean variables only; scale rational coefficients exactly.
Use native interval variables, no_overlap, cumulative, element, allowed assignments and other CP-SAT constraints.
A model without an objective is a satisfaction problem.''',
    "ortools.routing": '''from ortools.constraint_solver import pywrapcp
def build_model(data):
    distances = [[0,2,9],[2,0,4],[9,4,0]]
    manager = pywrapcp.RoutingIndexManager(len(distances), 1, 0)
    routing = pywrapcp.RoutingModel(manager)
    def distance(i, j):
        return distances[manager.IndexToNode(i)][manager.IndexToNode(j)]
    callback = routing.RegisterTransitCallback(distance)
    routing.SetArcCostEvaluatorOfAllVehicles(callback)
    return {"model": routing, "manager": manager}
Return this dictionary; keep callbacks alive with the RoutingModel. Use dimensions for capacity/time,
vehicle-specific costs, disjunctions and pickup/delivery constraints as required. Do not solve.
Routing may produce a good feasible route without proving optimality.''',
    "ortools.constraint": '''from ortools.constraint_solver import pywrapcp
def build_model(data):
    s = pywrapcp.Solver("assignment")
    x = [s.IntVar(0, 3, f"x[{i}]") for i in range(4)]
    s.Add(s.AllDifferent(x))
    return {"model": s, "variables": x}
Return a dictionary with model=pywrapcp.Solver, variables=list of native IntVar.
For optimization also return objective=IntVar and sense="min" or "max".
Optionally return search=a native DecisionBuilder. Do not run search; the platform controls search and its time limit.''',
    "ortools.max_flow": '''from ortools.graph.python import max_flow
def build_model(data):
    m = max_flow.SimpleMaxFlow()
    m.add_arc_with_capacity(0, 1, 5)
    m.add_arc_with_capacity(1, 2, 3)
    return {"model": m, "source": 0, "sink": 2}
Return this dictionary. Capacities are nonnegative integers. Do not solve.''',
    "ortools.min_cost_flow": '''from ortools.graph.python import min_cost_flow
def build_model(data):
    m = min_cost_flow.SimpleMinCostFlow()
    m.add_arc_with_capacity_and_unit_cost(0, 1, 5, 2)
    m.set_node_supply(0, 3)
    m.set_node_supply(1, -3)
    return m
Return SimpleMinCostFlow; positive supplies are sources and negative supplies are demands.
To maximize total flow before minimizing its cost, return {"model": m, "maximize_flow": True} instead.
All capacities, supplies and costs must be integers. Do not solve.''',
    "ortools.assignment": '''from ortools.graph.python import linear_sum_assignment
def build_model(data):
    m = linear_sum_assignment.SimpleLinearSumAssignment()
    for i, row in enumerate([[9,2],[6,4]]):
        for j, cost in enumerate(row):
            m.add_arc_with_cost(i, j, cost)
    return m
This is minimum-cost bipartite one-to-one assignment, not general MIP. Costs must be integers. Do not solve.''',
    "ortools.knapsack": '''def build_model(data):
    return {"values": [6,10,12], "weights": [[1,2,3]], "capacities": [5]}
Return this data dictionary. The platform creates the native KnapsackSolver with the selected backend,
calls init(values, weights, capacities), and solves it. Every weights row is one capacity dimension.
Use integer profits and weights. Some knapsack algorithms support only one capacity dimension.''',
}
