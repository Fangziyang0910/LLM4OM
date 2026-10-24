After a run, read the solver status, objective and concrete decisions, then check that the formulation represents the original problem. The result page retains the model, code, inputs, data and modeling process.

## Read the actual decisions

The result explanation adds business labels and units. Table values come directly from the solver; the LLM supplies labels and text. Explanation reads at most 100 nonzero variables, or the first 100 for an all-zero solution. The full variables remain available for expansion, search and export.

Two-dimensional variables can appear as matrices. When a method revises the model or code, inspect versions and compare with the previous one. Failure of the explanation call does not remove the solver result.

## Interpret the status

| Status or situation | How to read it |
|---|---|
| Optimal | Optimality applies to this model; still check its match to the problem |
| Feasible, or timed out with a solution | Inspect the actual solution; optimality may be unproven |
| Locally optimal | Retain its local meaning; see [CasADi](../casadi/) |
| Infeasible | See [Infeasibility](../conflicts/); this is not an executable plan |
| Method validation failed | Read the failed stage and feedback even if the solver has a result |

If new code fails before execution, the page does not attach the preceding version's result to it. Earlier results remain visible in the process steps.

## Choose an export

- **Excel**: the plan sheet includes business labels, all variable values and units. A problem sheet retains the statement, revisions, attachment names, configuration and links. Zero values are included, regardless of the page's display range.
- **CSV**: download complete variable values for further computation or checks.
- **Markdown report**: problem, settings, result, model, code and notes, with at most 500 nonzero variables and an explicit range notice.

Optimal, feasible, locally optimal and timed-out runs with an actual solution can export Excel. Infeasible, unbounded and failed runs are not exported as executable plans. An export is a snapshot; editing Excel does not solve the model again.

## Continue with the plan

Use Discuss plan, Adjust conditions or Business scenario comparison below the result. Explain the existing result first, then specify requirements to change, keeping a clear computation baseline.
