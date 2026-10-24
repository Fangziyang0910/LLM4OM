OptiTree matches a problem down a type tree, retrieves guidance from the matched node and generates code. Its classification retains mixed-integer programming as the root scope.

## Workflow

```text
Classify from the root → match child types → retrieve guidance
                      → reason and generate code → execute → inspect errors
```

The deepest matched entry guides reasoning. If code cannot run, an inspector revises it using actual sandbox feedback within the inspection limit.

## How to use it

Select OptiTree and submit a clear LP/MILP problem to inspect how classification and retrieved guidance affect modeling. The upstream type tree and templates are distributed with the platform; you do not need to build a separate library.

Changing the modeling library changes the code contract, rather than the tree's mathematical scope.

## What to inspect

Inspect the classification path, retrieved entry, reasoning, formulation and code. If classification names an absent type, omits judgment fields or loops back to a visited node, the platform stops at the current node. Retrieved guidance still needs to be checked against the actual problem.

## Source and adaptation

See the [pinned OptiTree source](https://github.com/MIRALab-USTC/OptiTree/tree/2e70ecfd0a3c8e9c0c16d36d7d498a7344cfdec9) and [paper](https://arxiv.org/abs/2510.22192). Classification, reasoning and inspection prompts and the original tree are retained. Code requests are adapted to return native models for sandbox solving.
