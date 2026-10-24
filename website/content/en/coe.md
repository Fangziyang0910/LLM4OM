Chain-of-Experts (CoE) asks experts to comment in sequence, then uses a reducer to produce the formulation and code. A conductor selects the next expert from the discussion so far.

## Workflow

```text
Start trial → conductor selects expert → expert comments → continue or reduce → model and code
```

The upstream design provides seven expert roles. The platform retains their prompts, conductor and reducer, rather than replacing the sequence with a parallel vote.

## How to use it

Select Chain-of-Experts for LP/MILP problems to inspect how interpretation, modeling and code advice are combined. Each trial starts with an empty comment pool.

The default allows up to three collaborating experts and disables reflection. Reflection is a deployment preset, not a per-message toggle. When enabled, an execution error triggers responsibility analysis from the last expert backwards before further trials.

## What to inspect

Inspect expert selection, individual comments and the final model. Expert opinions are not solver results; numerical values come from actual sandbox computation. With reflection disabled by default, multiple experts do not imply automatic multi-round repair on every run.

## Source and adaptation

The workflow and prompts follow the [pinned Chain-of-Experts source](https://github.com/xzymustbexzy/Chain-of-Experts/tree/afb89bf602690ea621f13a23c42722f20f653a43). The platform supplies the complete shared library contract and executes code in the sandbox. Reflection reads actual solver feedback rather than generating extra test inputs.
