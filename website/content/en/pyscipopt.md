PySCIPOpt uses native SCIP models for linear, integer and nonlinear constraints. It suits models combining discrete choices with native nonlinear expressions.

## Expressing a nonlinear objective

The native interface uses a linear objective. Introduce auxiliary t, constrain `cost(x)≤t`, and minimize t. This epigraph form preserves the cost while fitting the interface.

The example minimizes squared distance to `(1,2)` under a resource limit of 2. Auxiliary `loss` represents that cost.

## Complete native model

```python
from pyscipopt import Model

def build_model(data):
    model = Model("allocation")
    x = model.addVar(name="x", lb=0, vtype="C")
    y = model.addVar(name="y", lb=0, vtype="C")
    loss = model.addVar(name="loss", lb=0, vtype="C")
    model.addCons(x + y <= 2, name="resource")
    model.addCons((x-1)**2 + (y-2)**2 <= loss, name="loss_definition")
    model.setObjective(loss, "minimize")
    return model
```

SCIP should return values near x=0.5, y=1.5 and loss=0.5, read with numerical tolerances. Return Model; the platform performs solving.

## How the auxiliary variable works

```mermaid
flowchart LR
  Cost["Nonlinear cost expression"] --> Link["cost ≤ loss"]
  Link --> Obj["Linear objective: min loss"]
  Obj --> SCIP["Solve native SCIP model"]
  SCIP --> Values["Decisions and auxiliary value"]
```

For maximization, the corresponding hypograph uses `t≤reward(x)` and maximizes t. Objective direction determines the linking inequality. Meaningful names help explain auxiliary values.

## Variables, indices and matrices

`vtype="C"` means continuous, `"I"` integer and `"B"` binary. Scalar and matrix APIs return `pyscipopt.Model`. Parse full attachments to construct indexed products, times or network decisions.

For mixed discrete/nonlinear models, choose a modeling method covering that mathematics. Runs retain the library, backend and method together.

## Results and further operations

Auxiliary variables are part of the saved model. Export all values and explain which variables are business decisions versus cost or logical auxiliaries. Use [revisions](../revisions/) to change resources or fix discrete choices and compare plans.

See [CVXPY](../cvxpy/) for geometry and an interactive version of the continuous example. Native APIs are documented in [PySCIPOpt Model](https://pyscipopt.readthedocs.io/en/stable/api/model.html) and the [matrix tutorial](https://pyscipopt.readthedocs.io/en/stable/tutorials/matrix.html).
