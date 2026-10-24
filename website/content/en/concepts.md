A run depends on the problem, modeling method, LLM and solver environment. Their separate roles help explain both configuration choices and results.

## From problem to plan

```text
Natural-language problem + data
             ↓
A modeling method organizes LLM calls
             ↓
Mathematical model + Python code
             ↓
The sandbox executes code; a backend solves the model
             ↓
Status, objective, decisions and recorded steps
```

## Four distinct choices

| Choice | What it determines | Examples |
|---|---|---|
| Modeling method | How a model is generated, checked and repaired | Direct, TriVAL, BIND |
| LLM preset | Which language model reasons and generates code | Your configured model service and model ID |
| Modeling library | Which Python interface expresses the model | Pyomo, CPMpy, CVXPY |
| Solver backend | Which engine computes the solution | HiGHS, CP-SAT, Gurobi, Ipopt |

Changing the LLM does not directly change the solver. Choosing another library does not automatically broaden a method's problem scope. See the [method guide](../methods/) and [solver guide](../solvers/).

## What a run saves

Each run fixes its problem, attachments, configuration, steps, formulation, code and actual result. A revision creates a separate run for comparison. Deleting a preset or changing server configuration later does not rewrite saved runs.

## Read the status correctly

- `optimal`: the solver established optimality for the current model.
- `feasible`: a solution exists, possibly without proof of optimality.
- `locally_optimal`: a local optimization conclusion, often for nonlinear models.
- `infeasible`: the current model is infeasible; conflict evidence may be available.
- Execution failure: code, dependencies, interfaces or limits prevented completion.

Solver status and business-model correctness are separate judgments. If method validation fails even though a solver reports optimality, read the failed stage and its feedback first.
