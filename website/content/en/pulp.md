PuLP targets linear and mixed-integer programming. Variables, linear sums and inequalities suit production, transportation, budgets and allocation when relationships are linear.

## What linear means

`3A+2B` and `2A+B≤8` are linear because coefficients are known constants. `A×B`, `A²` and division by an unknown variable are not. Convex quadratic losses and norms can use libraries such as CVXPY, linked below.

Binary decisions can still express switches in a linear model. With a valid capacity bound, `production ≤ capacity × open` links production to a binary opening decision because capacity is constant.

## Complete production model

```python
import pulp

def build_model(data):
    model = pulp.LpProblem("production", pulp.LpMaximize)
    a = pulp.LpVariable("A", lowBound=0, cat="Integer")
    b = pulp.LpVariable("B", lowBound=0, cat="Integer")
    model += 3*a + 2*b, "profit"
    model += 2*a + b <= 8, "cutting"
    model += a + 2*b <= 8, "finishing"
    return model
```

The expression without a comparison defines the objective; comparison expressions add constraints. Names must be unique. The platform calls CBC or the explicit compatible backend; generated code does not call `model.solve()`.

## Default backend and interfaces

The default is `PULP_CBC_CMD`. Other backends are discovered through native `listSolvers/getSolver`, preserving Python, command-line and dynamic-library identifiers.

Row-oriented algebra and column-oriented `LpConstraintVar` both return `LpProblem`. Choose a form matching the data organization.

## Review and revise results

The example gives A=3, B=2 and objective 13. Results show variables, objective and actual backend. Export the full data or revise capacities and minimum demand from the saved plan.

```demo
production
```

Change cutting capacity or minimum B in the example and download the current CSV. See [revisions](../revisions/) and [scenario comparison](../scenarios/) for the platform workflow.

## Common issues and selection

Specify `cat="Integer"` for whole quantities and `cat="Binary"` for switches. Inspect names, objective direction and every resource constraint. For variable-product expressions, select a library supporting the required structure.

See [Pyomo](../pyomo/) for broader algebraic modeling, [CVXPY](../cvxpy/) for convex norms and quadratic losses, or [CPMpy](../cpmpy/) for discrete logic and global constraints. API details are in the [official PuLP documentation](https://coin-or.github.io/pulp/technical/pulp.html).
