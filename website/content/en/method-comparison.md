Method comparison holds the problem fixed and compares actual outputs from different modeling methods or LLM presets. [Scenario comparison](../scenarios/) instead changes business requirements.

## Start a comparison

In the manual workbench, open Run settings, enable Compare and select multiple methods or LLM presets, up to 12 runs. Confirm the problem, attachments, library and backend before starting.

Each item executes independently and retains its own formulation, code, steps and solver result. Open a row in the comparison table to inspect that run.

## Read the comparison table

| Information | What it helps explain |
|---|---|
| Status and objective | Whether solving completed and whether model objectives agree |
| Duration | Actual execution time, excluding queue time |
| LLM calls and tokens | The method's call cost on this problem |
| Formulation, code and steps | Modeling choices or errors behind numerical differences |

Equal objective values do not imply identical or correct models. When values differ, inspect domains, objective direction, constraints and data binding before attributing the difference to a method.

## Keep comparison conditions clear

For method comparisons, hold the problem, attachments, LLM preset, library and backend fixed where possible. For LLM comparisons, fix the method and solving environment. Save configurations and reports, including actual preset parameters rather than only method names.

A single problem helps explain specific behavior. Measuring overall modeling ability requires a sourced problem set, reference answers and consistent criteria. Side-by-side display alone does not establish a general accuracy result.
