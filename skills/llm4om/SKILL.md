---
name: llm4om
description: "Model and solve optimization problems using the current agent and real solvers. Use for scheduling, production planning, routing, resource allocation, mathematical programming, or a named LLM4OM modeling method."
---

# Model and solve

Use your current model for modeling, review and explanation. The skill's runner executes the selected method graph, its tools, and the solver. The agent needs workspace file access, command execution, uv and a running Docker engine.

Locate `scripts/run.py` beside this installed `SKILL.md` and use its **absolute path** as `RUNNER` in the examples below. Run commands in the user's workspace. In separate shell calls, use the resolved path again. Save the business problem as UTF-8 text and keep attached data in separate files.

## Start

Preserve the user's objective, constraints, units and variable domains. Clarify missing business decisions when they affect the answer. Honor a requested method or library. Direct and Pyomo suit a first linear/integer model. Consult [method selection](references/methods.md) for other problem structures.

```bash
uv run --script "$RUNNER" start --file problem.md --method direct --language pyomo --session runs/host/plan-a
```

Choose a fresh session directory. Add `--data FILE` for each attachment. Select `--solver NAME` only when a particular backend is needed. First use prepares the matching Docker worker; allow the build to finish. For environment errors see [setup](references/setup.md).

## Answer the method's requests

- **waiting** — Read each item in `pending`. Answer its messages with your current model, following its response format and any supplied tool schemas. Save one JSON object mapping every pending ID to its answer. A text entry looks like `{"REQUEST_ID": {"content": "..."}}`. For tool calls and parallel candidates see [response format](references/protocol.md).
- Submit the answers and continue until the method finishes:

  ```bash
  uv run --script "$RUNNER" resume --session runs/host/plan-a --responses answers.json
  ```

- **completed** — Read `solve.status`, actual decisions, units and objective. Use `result_file` for the full variable table, Pareto front, diagnostics, intermediate steps and usage. Link the saved formulation, code or result when relevant. Preserve the difference between optimal, feasible, infeasible and a search that found no solution.
- **failed** — Report the concrete error and the available artifacts. **interrupted** — Inspect the saved session with `status --session DIRECTORY`; resume with an empty JSON object if no requests are pending.

For changed requirements, start a new session from the complete revised problem so both outcomes remain available. The method's own tools perform checks, repairs and candidate selection; no separate model API or Web service is required.

## Other tasks

Use the same `uv run --script "$RUNNER"` prefix with `methods` to list methods, `target --language LIBRARY` to read the maintained code contract, or `backends` to discover engines in the actual worker. When the user already has a model, `solve --code model.py --language pyomo` executes it directly and accepts the same `--data FILE` attachments.
