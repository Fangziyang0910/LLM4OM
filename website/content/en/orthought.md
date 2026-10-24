ORThought writes a reasoning path, formulation and code in the order of an expert modeling workflow. If execution fails, it debugs using the problem, formulation and error.

## Workflow

```text
Understand objective, variables and constraints → reasoning path → formulation and code
                                              → execute → debug code if needed
```

The reasoning path is saved as the `solution_path` artifact. It makes the interpretation and organization of the model visible for inspecting where constraints came from.

## How to use it

Select ORThought with a library and backend suitable for the problem. Check whether the reasoning identifies the decisions, objective direction and requirements before inspecting expressions and code.

Execution errors trigger bounded debugging. Code that executes but produces an infeasible model does not automatically enter that debugging loop. Inspect platform evidence separately when you need to understand infeasibility.

## Integrated scope

The platform integrates the upstream formalized modeling mode and solve agent. It does not include the paper's multi-agent comparison or LogiOR dataset. Code extraction is adapted so a short valid `build_model(data)` function is not rejected by the upstream length threshold.

## Source

See the [pinned ORThought source](https://github.com/BeinuoYang/ORThought/tree/5293e24861a65d1e4a2f61f4fad0a81de901ee38) and [paper](https://arxiv.org/abs/2508.14410). The source has no declared license; the project records the prompts for research reproduction in [NOTICE](https://github.com/Fangziyang0910/LLM4OM/blob/main/NOTICE).
