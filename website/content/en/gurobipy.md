gurobipy is Gurobi's native Python modeling interface. Scalar-expression and matrix APIs both return the same native Gurobi model.

## Select it in the platform

Choose gurobipy, whose native engine is Gurobi. Its model is not connected to arbitrary alternative engines. For HiGHS or CBC, use a library with the relevant native adapter.

Model capabilities depend on the installed Gurobi version and problem type. The platform retains native constraints and expressions; code must still express domains, objective and requirements correctly.

## Code and results

`build_model(data)` returns `gurobipy.Model` without calling `optimize()`. The platform solves and reads objective, variables, status and available diagnosis. Scalar and matrix APIs may be combined in one model.

For an infeasible model, Gurobi IIS can supply conflicting constraints for [infeasibility explanation](../conflicts/). Evidence concerns the current formulation, so check its mapping to the business requirements.

## Licenses

Without a full license, use is limited to the scope allowed by the runtime. Larger models, shared use and containers require a license suitable for the actual deployment. Configure `GRB_LICENSE_FILE` and corresponding host, app and sandbox mounts. See [Backends and licenses](../backends/).

## Official references

See the [Gurobi Python API](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/overview.html) and [MVar matrix variables](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/mvar.html). Installation or apparent backend availability does not replace license validation during an actual solve.
