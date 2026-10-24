Start with the failed stage and complete error. The following checks cover connections, model requests, execution, validation and recovery.

## Pages and service connections

| Symptom | Check/action |
|---|---|
| Local page unavailable | Inspect `docker compose ps` and `docker compose logs -f app` |
| Other devices cannot connect | Check server IP, mapping, firewall and security group |
| HTTPS certificate issue | Check DNS, ports 80/443 and `docker compose logs -f https` |
| Interrupted live progress | Refresh the run link; inspect proxy streaming and server logs |

Python startup prints the listening address and workspace. Compose uses `LLM4OM_PORT`.

## Presets and model requests

| Error | Action |
|---|---|
| 401 | Check key and provider |
| 404 | Check endpoint, protocol and model ID |
| Structured-output/tool-choice error | Inspect service tool support, method and advanced parameters |
| DeepSeek with TriVAL | Set `{"thinking":{"type":"disabled"}}` in the run preset |
| Quota message | Check daily usage and select an available preset or continue next day |

Failed saves retain entered values. Follow [preset configuration](../model-presets/), then confirm with a small example.

## Execution environment and code

For a missing Worker, run `docker compose up -d --build`, or `uv run llm4om build-worker` in Python setups.

For Docker connection errors, inspect the service, socket permissions and `DOCKER_SOCKET`. For backend/license failures, read complete feedback and follow [backend setup](../backends/).

Execution errors identify exceptions and stages. Locate file names, fields, indices, return objects or APIs, then rerun the appropriate repair workflow from the problem.

## Method validation and solver results

TriVAL retains semantic, formulation and code validation; SAC-Opt retains per-constraint comparisons; Feedback Repair retains accept/repair reasons. Failure messages identify stages, with artifacts and executions in the process view.

Open the relevant stage and compare feedback with its model/code version. Method articles provide stopping conditions, return paths and parameters for following the run.

## Infeasibility and native statuses

Use [conflict analysis](../conflicts/) when IIS/MUS evidence is available, then revise the relevant rules. For nonlinear paths, inspect starts, bounds and native feedback before computing further scenarios.

Run information records time, calls and quotas. See [configuration](../configuration/) for limits and [solvers](../solvers/) for mathematical selection.

## Recovery and issue records

Refresh reconnects conversations to active runs; open saved plans from cards or history. Retry original messages after stopping. Batch retries reuse saved scenarios and continue remaining work.

Capture run link, method, library, backend, public preset configuration, failed stage, complete error and relevant problem text. These connect an issue to concrete inputs and execution. See [maintenance](../configuration/) for logs and backups.
