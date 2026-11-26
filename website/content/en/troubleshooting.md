Start with the failed stage and complete error. The following checks cover connections, model requests, execution, validation and recovery.

## Identify the failing layer

| Location | Inspect first | Verification |
|---|---|---|
| Page does not open | Service terminal or Compose logs | The listening address opens in a browser |
| Failure before generated content | AI model settings and failed call | The selected preset completes a small problem |
| Execution fails after generation | Executed code and complete error in Solving Steps | Worker and selected backend are available |
| Solve succeeds but the plan is wrong | That version's statement, formulation and domains | Constraints match the business requirements |
| Language or formulas look wrong | Language and display guidance below | Separate translations, source models and raw logs |

Keep the run link before retrying. Retain the original failure evidence; a successful execution does not establish that the model matches the problem.

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
| TriVAL model request fails | Check the preset endpoint, model ID and tool-calling support; TriVAL uses the preset's thinking settings |
| Quota message | Check daily usage and select an available preset or continue next day |

Failed saves retain entered values. Follow [preset configuration](../model-presets/), then confirm with a small example.

## Execution environment and code

For a missing Worker, run `docker compose up -d --build`, or `uv run llm4om build-worker` in Python setups.

For Docker connection errors, inspect the service, socket permissions and `DOCKER_SOCKET`. For backend/license failures, read complete feedback and follow [backend setup](../backends/).

On Windows, Docker Desktop's Linux engine must be running. Start with `docker info`. If virtualization is unavailable, check WSL 2, Windows virtualization components and firmware settings, following Docker Desktop's diagnostics. Changes to Windows features or boot settings can require administrator access and a restart; they are not routine solving steps.

The default Docker Worker executes generated code and calls the solver; model requests originate on the server. Replacing an API key does not repair the Docker engine, and rebuilding the Worker does not repair authentication.

Execution errors identify exceptions and stages. Locate file names, fields, indices, return objects or APIs, then rerun the appropriate repair workflow from the problem.

## Method validation and solver results

TriVAL retains semantic, formulation and code validation. Failure messages identify stages, with artifacts and executions in the process view.

Open the relevant stage and compare feedback with its model/code version. Method articles provide stopping conditions, return paths and parameters for following the run.

## Infeasibility and native statuses

Use [conflict analysis](../conflicts/) when IIS/MUS evidence is available, then revise the relevant rules. For nonlinear paths, inspect starts, bounds and native feedback before computing further scenarios.

Run information records time, calls and quotas. See [configuration](../configuration/) for limits and [solvers](../solvers/) for mathematical selection.

## Language, formulas and reading translations

| Symptom | Action |
|---|---|
| A foreign-language statement remains visible | Source statements are retained; use the reading translation in Problem and data and switch to the original when needed |
| Historical model explanations use another language | Wait for the reading translation; a Translate to Chinese action is available for some mixed-language content |
| History titles, result labels or units use another language | Visible text can use batched, cached display translations for the interface language. Initial generation takes time; failures retain the source. Hover over a translation to inspect the original |
| English or JSON appears during solving | View raw model output shows the actual response, which can contain code, English and tool protocols; it is separate from the localized model reading view |
| Variables show `var_type`, `domain` or `shape` | Fixed model labels are localized in the reading view. Hard-refresh to load current assets; code and raw logs retain protocol names |
| Expressions such as `x_A` appear as plain text | Check for `$...$`, `$$...$$` or math delimiters in the source; translation does not automatically convert bare text into formulas |
| An example translation fails or is empty | Keep the source; check the default available preset, connection and quota, then retry. Existing plans need no new solve |

New runs request explanations in the interface language. This does not guarantee the same language in provider reasoning. A statement and interface already in the same language usually need no reading translation.

Display translations of titles, natural-language result labels and units use the default available preset and its daily quota; cache hits reuse existing translations. They do not rerun the solver, translate raw reasoning, or rewrite statements, title metadata, code, variable names, copied content, reports, Excel exports or subsequent modeling inputs. Translating a unit name does not convert values. Language detection and machine translation can be wrong, especially for mixed-language content; check important entities and units against the source.

Example and reading translations translate natural language, including table headings and descriptive cells, while requesting unchanged numbers, formulas, variable names, code and table structure. Generation uses the server's default available preset and counts toward its quota. The same source, target language and translation rules reuse the local cache. Check important units, negations and constraint directions against the source; translations can be wrong.

Copies, downloads, literal version differences and subsequent modeling use the original content. Explicitly choosing Use translation in the example library makes the translation the new run's statement; inspect it before solving.

## Recovery and issue records

Refresh reconnects conversations to active runs; open saved plans from cards or history. Retry original messages after stopping. Batch retries reuse saved scenarios and continue remaining work.

Capture the run link, method, library, backend, public preset configuration, failed stage, complete error, relevant statement, and expected versus actual behavior. Remove credentials, licenses and sensitive business data before sharing; do not upload `.env` or the entire private workspace. See [maintenance](../configuration/) for logs and backups.
