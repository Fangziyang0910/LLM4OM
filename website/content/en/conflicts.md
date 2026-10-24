Infeasibility means the current model's requirements cannot all hold together. When concrete solver evidence is available, the platform maps conflicting constraints to business requirements so you can decide what to change.

## When diagnosis is available

Current paths include Gurobi IIS for linear models and MUS for CPMpy models. CVXPY does not provide this diagnosis here. An infeasible status does not necessarily include an explainable conflict set.

When evidence exists, the result page shows Why infeasible. Expand the corresponding constraints to inspect the model conditions behind each explanation.

## A concrete example

```text
Each A uses 2 cutting units; total cutting capacity is 8.
Additional requirement: produce at least 5 units of A.
```

These requirements conflict: 5 units of A alone need 10 cutting units. First check that the model accurately reflects the business rules, then decide whether to add capacity or change the production requirement.

## Try a revision

The platform offers at most one evidence-based candidate change. It has not been validated by another solve and does not directly alter the original constraints. Try this adjustment fills the revision text. Review or edit it, then compute a new plan to test it. The original problem and result remain saved.

Feedback Repair reads available diagnosis to check modeling errors. Research methods retain their own feedback workflows. Infeasibility can be a correct result; fixed requirements should not be relaxed merely to obtain a solution.

## When no diagnosis is available

The platform does not produce a definite conflict explanation when diagnosis fails, no evidence is supplied or the result is only locally infeasible. Read the original error and check units, bounds and configuration. Large-model Gurobi diagnosis also requires a suitable license. See [CasADi](../casadi/) for local-status semantics.
