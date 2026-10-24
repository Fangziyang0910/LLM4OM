Start with the failed stage and complete error. Distinguish server connection, LLM calls, code execution, infeasibility and method-validation failure before choosing a fix.

## Platform or LLM connection errors

| Symptom | Next check |
|---|---|
| Cannot connect to the platform | Check `docker compose ps`, listening port, firewall and URL |
| Preset returns 401 | Check key, provider and protocol |
| Preset returns 404 | Check endpoint and model ID; a display name cannot replace the model ID |
| TriVAL structured output fails with DeepSeek | Disable thinking in the run preset as described in [LLM presets](../model-presets/) |
| HTTPS certificate fails | Check DNS, ports 80/443 and Caddy logs |

## Code or backend errors

For a missing Worker image, rerun `docker compose up -d --build`, or use `uv run llm4om build-worker` for a local service. For Docker connection failures, check socket paths and permissions.

Expand unavailable-backend reasons and inspect executables, interface type and licensing. Explicit engine selection does not trigger replacement. Do not send continuous decisions to an integer-only model or solve an integer problem with an LP-only backend.

## An optimal objective with a failure notice

Solver optimality concerns the current model. TriVAL or SAC-Opt validation may still fail. Feedback Repair may identify incorrect coefficients, constraints or data binding. Read method feedback and model versions rather than only the objective.

If new code fails before execution, it does not inherit the previous solution. Earlier actual solves remain saved in the modeling process.

## Infeasibility, local results and usage limits

For infeasibility, check [conflict evidence](../conflicts/) and business requirements. Local optimality and local infeasibility retain their local meanings; see [CasADi](../casadi/). When daily tokens are exhausted, use another available preset or wait for the next day in the configured server timezone. Retrying does not bypass limits.

## Recover a conversation or report a problem

Refresh reconnects to active runs, and failed text replies do not delete saved plans. Preserved steps after cancellation do not imply resuming a method from that node. Record the run link, failed stage, method, library, backend and complete error when reporting a problem. Do not include API keys or license files.
