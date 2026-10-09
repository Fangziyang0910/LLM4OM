# OptiMUS public production example

Status: SDK/Worker 0.9.0 development example, not a benchmark score. The
[S06-B record](../../docs/development/s06b-optimus.md) defines implemented behavior
and outstanding acceptance; [contracts](../../docs/plugin-contracts.md#14-s06-b-native-script-resources-sdk-090)
define the interface.

`problem.json`, `params.json` and `labels.json` are hand-authored public inputs.
The source workflow separates parameter metadata from values. The mathematical
check is immediate: integer `0 <= x <= 4`, maximize `3x`, so `x=4`, objective12.
No reference model or answer is sent to the method.

From the repository root, install the Gurobi/development extras and build the
Worker as described in [CONTRIBUTING](../../CONTRIBUTING.md). Copy `run.yaml` to
a local ignored configuration, set its actual OpenAI-compatible endpoint and
provide `LLM4OM_LLM_API_KEY` through the project `.env` or process environment.
Keep the public problem path absolute if the copied config moves.

```bash
uv run --locked llm4om doctor --config examples/optimus/run.yaml
uv run --locked llm4om run --problem examples/optimus/problem.json --config /absolute/path/to/local-config.yaml
```

Doctor does not call the paid model; `run` makes multiple paid requests. The
checked-in endpoint is a placeholder. This example selects the fixed source
main, error correction on and RAG off, with container gurobipy/Gurobi only.
The source may execute up to three scripts and generate a final unexecuted
repair. The platform records every revision and reuses the selected execution.

Inspect `method/state_*.json`, `method/revisions.json`, `method/source-calls.json`,
`method/source-selection.json` and `method/fidelity-report.json` in the public
run directory. Source stdout is a debugging observation. The independent
collector supplies the actual solution and objective. An optimal candidate
still needs comparison with the original problem before semantic correctness
can be claimed.
