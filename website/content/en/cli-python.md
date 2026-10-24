CLI and Python execute the same modeling graphs as the workbench. To use your current Codex or Claude Code model without a platform API key, install the Host Skill using [installation](../installation/). The `run` and Python examples below use a platform model preset and need the `llm` optional dependencies; the repository development setup already includes them.

## Run one problem from the CLI

Save the [quickstart](../quickstart/) production statement as UTF-8 `problem.txt`. Use a preset in the workspace:

```bash
uv run llm4om run --file problem.txt --workspace runs/web --method direct --language pyomo --solver highs --output result.json
```

The terminal shows stages, formulation, code and result. `result.json` retains final state and steps for further processing.

## Attach data and select a preset

```bash
uv run llm4om run --file problem.txt --data production.json --method bind --language pyomo --workspace runs/web --preset your-preset-id --output result.json
```

Repeat `--data` for more files. Code reads text by original file name. `--preset` uses a saved workspace ID; omission selects the default. Download data from [attachments](../attachments/).

| Option | Purpose |
|---|---|
| `--problem` / `--file` | Inline statement or UTF-8 file |
| `--method` | ID such as feedback_repair or sac_opt |
| `--language` | ID such as pyomo, ortools or cvxpy |
| `--solver` | Native ID; omission uses AUTO |
| `--workspace` / `--preset` | Preset workspace and ID |
| `--output` | Save final JSON state |

## Complete minimal Python call

```python
from llm4om import run_problem

state = run_problem(
    "Produce nonnegative integer A and B with profits 3 and 2. "
    "Cutting: 2A+B<=8; finishing: A+2B<=8. Maximize total profit.",
    method="direct",
    language="pyomo",
    solver="highs",
    workspace="runs/web",
    explain=True,
    locale="en",
)
print(state.get("failure") or state.get("solve"))
```

The returned state includes problem, configuration, formulation, code, solve and steps. `explain=True` adds a business explanation; `locale` sets its language.

## Supply complete data in Python

```python
from pathlib import Path
from llm4om import run_problem

state = run_problem(
    "Use production.json to choose nonnegative integer quantities and maximize profit. "
    "usage is resource-by-product hours per unit; capacity is available hours.",
    method="bind",
    language="pyomo",
    data={"production.json": Path("production.json").read_text(encoding="utf-8")},
    workspace="runs/web",
)
print(state.get("solve", {}).get("variables"))
```

`data` maps file names to text, matching workbench attachments.

## Supply model configuration explicitly

Pass `llm=LLMSettings(...)` for script-defined service configuration and read credentials from environment variables. Fields are defined in [LLMSettings](https://github.com/Fangziyang0910/LLM4OM/blob/main/src/llm4om/llm.py).

Method parameters come from presets. Async integrations can use lower-level `run` and `Resources`; see the [public Python module](https://github.com/Fangziyang0910/LLM4OM/blob/main/src/llm4om/__init__.py).

## Handle run state

Read `failure` and `solve.status` before processing values. Steps locate model calls, execution and validation feedback. For browsable retained history, the workbench provides links, tags, notes and exports; see [history](../history/).
