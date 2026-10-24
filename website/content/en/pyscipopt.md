PySCIPOpt is SCIP's native Python interface. The platform recognizes its Model with scalar, expression and matrix APIs.

## Suitable models

Native SCIP models express mixed-integer linear problems and supported nonlinear constraints. Direct PySCIPOpt modeling exposes more native structure than the linear SCIP interface within OR-Tools.

Capabilities still depend on the installed version and problem type. A method restricted to LP/MILP does not automatically gain a nonlinear modeling workflow by selecting PySCIPOpt.

## Select it in the platform

Choose PySCIPOpt, whose native backend is SCIP. Its Model is not switched to arbitrary alternative engines. Define `build_model(data)` and return the model without calling `optimize()`.

## Express nonlinear objectives

The native objective must be linear. Express a nonlinear objective using an auxiliary variable and correctly directed epigraph or hypograph constraints. For example, minimization of a squared expression can bound that expression above by an auxiliary variable and minimize the variable. Check that the transformation preserves the original meaning.

Specify bounds explicitly. A continuous decision that may be negative should not accidentally retain a nonnegative default bound. Actual SCIP execution provides the status and objective.

## Official references

See the [Model API](https://pyscipopt.readthedocs.io/en/stable/api/model.html), [nonlinear expressions](https://pyscipopt.readthedocs.io/en/stable/tutorials/expressions.html) and [matrix interface](https://pyscipopt.readthedocs.io/en/stable/tutorials/matrix.html).
