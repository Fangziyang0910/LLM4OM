Direct generates the formulation and complete solver code in one LLM call. The platform then executes the code and solves the model. It is the default method in Optimization chat.

## Workflow

```text
Problem and attachments → formulation and code → format check → solve
```

The prompt asks for explicit variable domains, indices, units, objective direction, data sources and constraints. Missing formulation or code produces a failure rather than sending empty code to the solver.

## How to use it

Choose Direct in Run settings or use the default Optimization chat configuration. Select a library and backend that can express and solve the problem. Its short call sequence makes it a useful starting point for inspecting a formulation.

Attachment previews may omit rows. Generated code should read the complete attachment through `build_model(data)`. Consider [BIND](../bind/) for structured-data binding on longer inputs.

## What to inspect

Check domains, objective coefficients, capacities and actual decisions. Direct has no post-solve semantic review loop; choose [Feedback Repair](../feedback-repair/) for that stage. Valid infeasible or unbounded statuses are solver results, rather than evidence that execution never occurred.

## Implementation source

Direct is maintained by LLM4OM. It shares generation prompts and a generation node with Feedback Repair, which adds solving, review and bounded repair.
