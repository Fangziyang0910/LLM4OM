coptpy constructs native COPT models for LP, MILP, convex quadratic and supported conic optimization. Scalar and matrix APIs use the COPT engine.

## When native interfaces help

Use it when a team already works with COPT and wants consistent native models and execution.

Different libraries can express the same production model. Keep domains, capacities and coefficients fixed when comparing. Differences in speed or objective cannot be attributed to engines if the business models differ.

## Complete production model

```python
import coptpy as cp
from coptpy import COPT

def build_model(data):
    model = cp.Envr().createModel("production")
    a = model.addVar(lb=0, vtype=COPT.INTEGER, name="A")
    b = model.addVar(lb=0, vtype=COPT.INTEGER, name="B")
    model.setObjective(3*a + 2*b, COPT.MAXIMIZE)
    model.addConstr(2*a + b <= 8, name="cutting")
    model.addConstr(a + 2*b <= 8, name="finishing")
    return model
```

Return the model; the platform solves it. The integer optimum is A=3, B=2, objective 13. Indexed models can use `addVars`; matrix APIs still require correct dimensions.

## Convex quadratic structure and integer domains

Validate a small linear case first. Adding quadratic costs requires checking convexity and backend support. Integer decisions also require the appropriate mixed-integer capability.

```demo
production
```

Changing the quantity domain changes the example's mathematics. The interaction shows the corresponding values and objective.

## Licensing and deployment

COPT has a restricted small-scale noncommercial path under applicable conditions. Larger models or commercial use require the appropriate license.

Deployment uses `COPT_LICENSE_DIR` with the specific `license.dat` and `license.key` files mounted read-only for the sandbox. Package installation, library loading and license validation are separate steps; see [backends and licenses](../backends/).

## Checking results and references

Inspect engine, status, objective direction and decision values. Distinguish a retained feasible incumbent from proven optimality after a limit. Use hand calculations for small resource models and retain full models and exports for larger reviews.

See the [COPT Python documentation](https://guide.coap.online/copt/en-doc/pythoninterface.html) and [installation and licensing guide](https://guide.coap.online/copt/en-doc/install.html).
