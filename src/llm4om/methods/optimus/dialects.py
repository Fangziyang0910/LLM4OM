"""The modeling-library parts of OptiMUS, one dialect per code language.

Upstream passes `solver="gurobipy"` and gurobipy directions to its code prompts and implements `get_var_code` only for
gurobipy. The gurobipy dialect is that text unchanged. The Pyomo and OR-Tools pywraplp dialects replace each
gurobipy-specific piece: the directions, the two code examples, the a <= x <= b note, the imports, the model set-up
and the variable code.
"""

from dataclasses import dataclass
from typing import Callable

from llm4om.methods.optimus import prompts as P

GUROBIPY_CONSTRAINT_EXAMPLE = "    model.addConstr(SalesVolumes[i] <= MaxProductionVolumes[i])"
GUROBIPY_OBJECTIVE_EXAMPLE = "model.setObjective(quicksum(price[i] * x[i] for i in range(N)), GRB.MAXIMIZE)"
GUROBIPY_RANGE_NOTE = "Gurobi does not support a <= x <= b syntax"
PYOMO_DOMAINS = {"CONTINUOUS": "NonNegativeReals", "INTEGER": "NonNegativeIntegers", "BINARY": "Binary"}
ORTOOLS_VARS = {"CONTINUOUS": "NumVar", "INTEGER": "IntVar", "BINARY": "BoolVar"}


@dataclass(frozen=True)
class Dialect:
    solver: str  # the {solver} of the code prompts
    directions: str
    constraint_example: str
    objective_example: str
    range_note: str
    imports: str
    setup: str
    var_code: Callable[[str, list, str], str]  # upstream generate_code.get_var_code: (symbol, shape, type) -> code

    def constraint_prompt(self) -> str:
        return (P.TARGET_CODE__PROMPT_CONSTRAINTS_CODE.replace(GUROBIPY_CONSTRAINT_EXAMPLE, self.constraint_example)
                .replace(GUROBIPY_RANGE_NOTE, self.range_note))

    def objective_prompt(self) -> str:
        return P.TARGET_CODE__PROMPT_OBJECTIVE_CODE.replace(GUROBIPY_OBJECTIVE_EXAMPLE, self.objective_example)


def gurobipy_var(symbol: str, shape: list, type: str) -> str:
    if shape == []:
        return f'{symbol} = model.addVar(vtype=GRB.{type.upper()}, name="{symbol}")\n'
    return f"{symbol} = model.addVars(" + ", ".join(str(i) for i in shape) + f', vtype=GRB.{type.upper()}, name="{symbol}")\n'


def pyomo_var(symbol: str, shape: list, type: str) -> str:
    """Gurobi variables default to a lower bound of 0, so continuous and integer map to the nonnegative domains."""
    domain = PYOMO_DOMAINS.get(type.upper(), type.upper())
    indices = "".join(f"range({i}), " for i in shape)
    return f'{symbol} = Var({indices}domain={domain})\nmodel.add_component("{symbol}", {symbol})\n'


def ortools_var(symbol: str, shape: list, type: str) -> str:
    """Like Gurobi variables, continuous and integer variables have a lower bound of 0; indexed ones are dicts."""
    kind = ORTOOLS_VARS.get(type.upper(), "NumVar")
    bounds = "" if kind == "BoolVar" else "0, model.infinity(), "
    if shape == []:
        return f'{symbol} = model.{kind}({bounds}"{symbol}")\n'
    if len(shape) == 1:
        return f'{symbol} = {{i: model.{kind}({bounds}f"{symbol}[{{i}}]") for i in range({shape[0]})}}\n'
    ranges = ", ".join(f"range({i})" for i in shape)
    return (f'{symbol} = {{idx: model.{kind}({bounds}f"{symbol}{{list(idx)}}") '
            f"for idx in itertools.product({ranges})}}\n")


GUROBIPY = Dialect(
    solver="gurobipy",
    directions=P.TARGET_CODE__DIRECTIONS,
    constraint_example=GUROBIPY_CONSTRAINT_EXAMPLE,
    objective_example=GUROBIPY_OBJECTIVE_EXAMPLE,
    range_note=GUROBIPY_RANGE_NOTE,
    imports="from gurobipy import Model, GRB, quicksum",
    setup='model = Model("OptimizationProblem")',
    var_code=gurobipy_var,
)

PYOMO = Dialect(
    solver="Pyomo",
    directions=P.TARGET_CODE__DIRECTIONS
    .replace("from gurobipy import Model, GRB",
             "from pyomo.environ import ConcreteModel, ConstraintList, Objective, quicksum, maximize, minimize")
    .replace('model = Model("OptimizationProblem")',
             'model = ConcreteModel("OptimizationProblem")\nmodel.constraints = ConstraintList()')
    .replace("Use model.addConstr() to add the constraint to the model.",
             "Use model.constraints.add() to add the constraint to the model."),
    constraint_example="    model.constraints.add(SalesVolumes[i] <= MaxProductionVolumes[i])",
    objective_example="model.objective = Objective(expr=quicksum(price[i] * x[i] for i in range(N)), sense=maximize)",
    range_note="Pyomo does not support a <= x <= b syntax",
    imports=("from pyomo.environ import (ConcreteModel, ConstraintList, Objective, Var, quicksum, maximize, minimize,\n"
             "                           NonNegativeReals, NonNegativeIntegers, Binary)"),
    setup='model = ConcreteModel("OptimizationProblem")\nmodel.constraints = ConstraintList()',
    var_code=pyomo_var,
)

ORTOOLS = Dialect(
    solver="OR-Tools (pywraplp)",
    directions=P.TARGET_CODE__DIRECTIONS
    .replace("from gurobipy import Model, GRB", "from ortools.linear_solver import pywraplp")
    .replace('model = Model("OptimizationProblem")', 'model = pywraplp.Solver.CreateSolver("SCIP")')
    .replace("Use model.addConstr() to add the constraint to the model.",
             "Use model.Add() to add the constraint to the model."),
    constraint_example="    model.Add(SalesVolumes[i] <= MaxProductionVolumes[i])",
    objective_example="model.Maximize(sum(price[i] * x[i] for i in range(N)))",
    range_note="OR-Tools does not support a <= x <= b syntax",
    imports="import itertools\nfrom ortools.linear_solver import pywraplp",
    setup='model = pywraplp.Solver.CreateSolver("SCIP")',
    var_code=ortools_var,
)

DIALECTS = {"gurobipy": GUROBIPY, "pyomo": PYOMO, "pywraplp": ORTOOLS}
