gurobipy constructs native Gurobi models. It suits workflows using native variables, constraints, matrix expressions and diagnostics. Actual solving requires a usable Gurobi license in the execution environment.

## Model and engine

A gurobipy Model belongs to Gurobi; it uses the native Gurobi engine. Scalar and matrix APIs both construct `gp.Model` and can be chosen to match data structure.

Production, transportation and location LP/MILP are common starting points. For quadratic, conic or other native expressions, also check the installed version, engine capability and modeling method scope.

## Complete production model

```python
import gurobipy as gp
from gurobipy import GRB

def build_model(data):
    model = gp.Model("production")
    a = model.addVar(lb=0, vtype=GRB.INTEGER, name="A")
    b = model.addVar(lb=0, vtype=GRB.INTEGER, name="B")
    model.setObjective(3*a + 2*b, GRB.MAXIMIZE)
    model.addConstr(2*a + b <= 8, name="cutting")
    model.addConstr(a + 2*b <= 8, name="finishing")
    return model
```

Return the built model for platform execution: A=3, B=2 and profit CNY 13. Matrix modeling with `MVar` still needs clear names, dimensions and row/column meanings.

## Review and export a plan

Results show named variables, objective, status and actual backend. Inspect A and B directly in this example. Matrix variables are read by component indices, and complete exports support further analysis.

```demo
production
```

Change capacities and demand in the example to see revised plans. Actual platform runs save the process, model and results together for inspection and comparison.

## Using IIS for infeasibility

Add `B≥5`: finishing `A+2B≤8` already conflicts with nonnegative quantities. Supported linear Gurobi paths can produce an IIS identifying jointly inconsistent constraints or bounds.

An IIS lists an irreducible set of conflicting constraints or bounds to help locate requirements for revision. Named constraints improve the connection to requirements; see [infeasibility and conflicts](../conflicts/).

## Licenses and common failures

 Distinguish missing licenses, environment mismatch, size restrictions and modeling errors. Containers use `GRB_LICENSE_FILE` for an offline license mounted read-only; see [backends and licenses](../backends/).

## Selection and references

Choose it when a suitable Gurobi environment is available and native interfaces or conflict evidence matter. For initial linear-model learning without that license, use open backends through [Pyomo](../pyomo/) or [PuLP](../pulp/). See the [Gurobi Python API](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/overview.html).
