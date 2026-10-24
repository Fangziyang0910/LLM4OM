coptpy is COPT's native Python interface. It is one modeling-library choice, with scalar, expression and matrix APIs returning a COPT model.

## Modeling scope

Current generation guidance covers LP, MILP, convex quadratic and conic optimization. Solvability depends on native capabilities and the installed version. The selected modeling method must also support the problem scope.

## Select it in the platform

Choose coptpy with native engine COPT. Code creates a model through its environment, defines `build_model(data)` and returns the model without solving. The platform reads the actual objective, variables and native status.

This path uses COPT's own model. Choosing COPT as a backend through CVXPY still uses CVXPY as the modeling library, rather than adding another library category.

## License configuration

The current deployment can test examples within the runtime's small noncommercial mode; larger models and commercial deployments need a suitable license. Set `COPT_LICENSE_DIR`, usually containing `license.dat` and `license.key`. Compose also needs matching host-path mounts.

The sandbox mounts the actual license files read-only and remains without network access. SDK installation, plugin loading and license validity are separate checks. Missing licenses do not trigger a silent substitute engine.

## Official references

See the [COPT Python interface](https://guide.coap.online/copt/en-doc/pythoninterface.html) and [installation and licensing](https://guide.coap.online/copt/en-doc/install.html). Platform mount examples appear in [Backends and licenses](../backends/).
