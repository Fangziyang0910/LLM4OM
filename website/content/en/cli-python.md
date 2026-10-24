The CLI and Python API execute the same modeling graphs as the server. Use them for scripts, final-state exports and integration with an existing workflow.

## Run from the CLI

With dependencies installed and an LLM configured, run:

```bash
uv run llm4om run --file problem.txt --method direct --language pyomo --solver highs --output result.json
```

`problem.txt` is your UTF-8 problem statement. Repeat `--data` to add attachments:

```bash
uv run llm4om run --file problem.txt --data demand.csv --data costs.json --method bind --language pyomo
```

The command displays steps and outputs the formulation, code and solver result. `--output` saves final state and steps. Use `--preset` for an LLM preset and `--workspace` for the workspace holding it.

## Common options

| Option | Meaning |
|---|---|
| `--problem` / `--file` | Direct problem text or a UTF-8 file |
| `--method` | Method ID, such as `direct`, `feedback_repair` or `sac_opt` |
| `--language` | Library ID, such as `pyomo`, `ortools` or `cvxpy` |
| `--solver` | Native backend ID; omitted means AUTO |
| `--data` | Input attachment; repeatable |
| `--sandbox local` | Host subprocess execution without isolation; development only |

Per-run calls cannot override method presets. See each method page for actual parameters.

## Call from Python

```python
from llm4om import run_problem

state = run_problem(
    "Produce nonnegative integer quantities A and B, with profits 3 and 2. "
    "Cutting capacity: 2A+B<=8. Processing capacity: A+2B<=8. "
    "Maximize total profit.",
    method="direct",
    language="pyomo",
    solver="highs",
)
if state.get("failure"):
    print(state["failure"])
else:
    print(state["solve"]["objective"])
```

Use `preset=` to select a preset, or `llm=LLMSettings(...)` to provide model configuration. Selecting a backend does not automatically rewrite a library's API; code and native model must remain compatible.
