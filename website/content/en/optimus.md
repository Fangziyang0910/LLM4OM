OptiMUS 0.3 decomposes a problem into parameters, objective and constraints. It builds expressions and code component by component, then assembles and executes them. Its platform ID is `optimus`.

## Workflow

```text
Parameters → objective and constraints → constraint checks → formulation
           → component code → assembly → execution → debugging if needed
```

Constraint extraction includes redundancy and confidence checks. Components use the selected library and are assembled into the complete platform function.

## How to use it

Select OptiMUS 0.3 to inspect how individual objectives and constraints are formed. It retains LP/MILP scope. Supply parameter values explicitly in the statement or attachments; an upstream-format `params.json` can also be used.

All nine libraries are available, without converting nonlinear requirements to linear ones or relaxing variable domains to fit a library.

## Process and stopping behavior

Inspect parameter values, individual constraint expressions, the objective and assembled code. Execution errors trigger bounded debugging. The upstream workflow treats optimal status as debugging success, so infeasible or unbounded models may also enter debugging. This differs from Feedback Repair's stopping rules.

## Source and adaptation

The workflow and prompts follow the [pinned OptiMUS v0.3 source](https://github.com/teshnizi/OptiMUS/tree/e182e9ef5841605c2a7e87467021fd83522b6484) and [v0.3 paper](https://arxiv.org/abs/2407.19633). The platform removes interactive input, does not enable upstream RAG, and adapts execution and code contracts to the chosen library and sandbox.
