Pyomo expresses algebraic models with sets, parameters, variables, objectives and constraints. It connects to multiple native backends, keeping model expression separate from the engine.

## Supported interfaces

The platform recognizes `ConcreteModel`, instantiated `AbstractModel` and `pyomo.kernel` models. Components such as GDP and DAE remain part of algebraic modeling, rather than extra library settings. Solvability depends on transformations and the selected backend.

## Select it in the platform

Choose Pyomo with AUTO or a native ID from the available backend list. Algebraic models usually default to HiGHS; Kernel automatically uses CBC for its model type. Nonlinear models need a compatible installed backend.

```bash
uv run llm4om run --problem "Your complete problem" --method direct --language pyomo --solver highs
```

## Generated-code requirements

`build_model(data)` returns a constructed native model for the platform to solve. Specify domains and bounds explicitly. Nonnegative integers and continuous variables that may be negative are different decisions. Do not read unsolved variable values while constructing the model.

Linear models can use Gurobi IIS evidence under the available diagnosis and license conditions. See [Infeasibility](../conflicts/).

## Further reading

See [official Pyomo modeling documentation](https://pyomo.readthedocs.io/en/stable/explanation/modeling/index.html), the [Kernel API](https://pyomo.readthedocs.io/en/stable/api/pyomo.kernel.html) and [backend guide](../backends/). The service discovers actual execution engines from native registries rather than listing decomposition algorithms as engines.
