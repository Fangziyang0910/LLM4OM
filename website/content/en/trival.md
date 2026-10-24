TriVAL separates validation into semantics, mathematical formulation and code. Each stage constructs, validates and revises its output. Code issues can send the process back to formulation.

## Workflow

```text
Semantic facts and validation → formulation and validation → code, execution and validation
                                        ↑                              ↓
                                        └──── revise when needed ──────┘
```

The stages distinguish understanding the problem, expressing it mathematically and implementing it in code. Intermediate artifacts and feedback appear in the process view.

## How to use it

Select TriVAL with a library and backend suitable for the problem. It supports workflows where you want to inspect stage-by-stage judgments as well as the final numbers.

With DeepSeek, disable thinking in the run preset because structured output requires forced tool selection. See [LLM presets](../model-presets/).

## What to inspect

Read the semantic facts, formulation, code and validation feedback. Reaching a validation limit does not mean a stage passed. The platform reports unresolved stages and keeps actual artifacts and solver results. An optimal solver status does not override method-validation failure.

## Source and adaptation

The core graph, nodes, prompts and loops come from the [pinned SCUT-EIPI/TriVAL source](https://github.com/SCUT-EIPI/TriVAL/tree/380a529). The platform supplies LLMs and sandboxes, adapting code to return native models through `build_model(data)`. Original documentation linked below records the detailed adaptations.
