SAC-Opt extracts semantic anchors for parameters, variables, objective and constraints. It backtranslates constraint code to text, compares it with the intended constraint, freezes accepted components and repairs only failed ones.

## Workflow

```text
Semantic anchors → component code → backtranslate constraints → compare
                                        ↑                      ↓ failed
                                        └── selective repair ──┘
                        → assemble → solve → debug execution errors
```

Backtranslation does not read the original constraint. A separate comparison checks consistency, helping locate a specific component rather than rewriting all code.

## How to use it

Select SAC-Opt for LP/MILP workflows that inspect constraints individually. Provide clear business rules and follow the mapping from anchors to constraint components.

Shared components support all nine libraries. Complete attachments are read in `build_model(data)`. Variable domains and bounds must still match the problem and cannot be relaxed merely to fit a library.

## What to inspect

Review anchors, components, backtranslations, individual comparisons and selective repairs. The current loop checks constraints rather than independently validating the objective. If semantic rounds end with unresolved components, the platform keeps actual artifacts and results while reporting semantic-validation failure.

## Independent implementation and source

This implementation follows the [SAC-Opt paper](https://proceedings.mlr.press/v306/zhang26cb.html) and [pinned reference](https://github.com/Forrest-Stone/SAC-Opt/tree/ec0ddb544ae6b70714181740ebbba16027df50e4). The reference commit has no declared license, so its code and prompts were not copied. The platform batches components and uses its own structured outputs while retaining semantic anchors and selective repair.
