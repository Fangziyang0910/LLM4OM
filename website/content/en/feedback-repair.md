Feedback Repair adds post-solve review to Direct generation. It checks the objective, domains, constraints and data binding against the original problem, then repairs specific formulation or code errors.

## Workflow

```text
Generate → solve → review against the problem → finish
   ↑           format, execution or modeling issue ↓
   └──────────────── repair from feedback ──────────┘
```

Review still checks the problem meaning when the solver reports optimality. Available conflict diagnosis also informs review. Without repairs, the method itself uses two LLM calls and one solve; later result explanation is additional.

## How to use it

Select Feedback Repair in Run settings for a workflow that reviews problem meaning after computation. Provide clear requirements and data, and choose a compatible library and backend.

Format, execution and modeling corrections share a limit of three repairs. A time limit, a merely feasible result or an objective-free satisfaction problem is not by itself a reason to change the model.

## Read failures and infeasibility

A correctly infeasible or unbounded model can finish without relaxing requirements to obtain a solution. Unresolved review or an unparsable reply preserves completed artifacts and reports failure. If later generation is incomplete, the last actually solved model and result remain traceable.

## Implementation source

This method is maintained by LLM4OM. Review is an additional check rather than a correctness proof. It does not introduce SAC-Opt's semantic anchors or OptiMind's specialized hint library.
