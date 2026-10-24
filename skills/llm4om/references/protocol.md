# Host response format

`host start`, `host resume`, and `host status` return JSON with a session path, status, pending requests, actual steps, usage counts, and available formulation/code/solve artifacts.

## Text answers

For each pending request, preserve its exact ID and put the method's answer in `content`:

```json
{
  "REQUEST_ID_FROM_PENDING": {
    "content": "The formulation and fenced Python code, JSON review, or other text required by this task."
  }
}
```

Use a file-writing tool or a quoted heredoc to create the JSON file. Preserve newlines and escapes in code and mathematics. Do not interpolate generated code into an unquoted shell command.

## Tool answers

When the request supplies tools and requires a call, return tool-call intentions with JSON objects as arguments:

```json
{
  "REQUEST_ID_FROM_PENDING": {
    "content": "",
    "tool_calls": [
      {"name": "write_code", "args": {"code": "def build_model(data):\n    ...\n"}}
    ]
  }
}
```

This example illustrates shape only; write executable code for the real task. Use the actual supplied tool name and schema. The CLI assigns a tool-call ID if omitted. Tool results return in the next model request. Tool-choice requirements appear in `options`; a structured validator normally requires its output tool rather than a prose answer.

## Parallel requests

Supply one answer for every pending ID in one response file. Repeated prompts with different IDs represent separate candidates or judgments. Generate each requested candidate or judgment rather than copying one answer across all IDs. Submit once all are answered; rejected response files leave the pending tasks available for correction.

The graph preserves the original sample count, ranking, voting, and branch selection. Sampling settings in `options` describe the original method. A portable skill cannot change the host model's temperature, guarantee independent contexts, or guarantee the original API's sampling distribution. This is a host-model adaptation, not an identical reproduction of an API-backed experiment.

## Status and recovery

| Status | Action |
|---|---|
| `waiting` | Answer every pending request and resume. |
| `completed` | Inspect actual solve results and deliver artifacts. The solver may report genuine infeasibility or unboundedness. |
| `failed` | Read `failure` and completed artifacts; start a new session for a new attempt. |
| `interrupted` | The process stopped during computation. Resume with an empty JSON object if there are no pending model requests. |

Completed model answers, solves, and helper scripts are preserved across CLI invocations. Native LangGraph checkpoints retain method state. A process killed during an unfinished solve may need to run that unfinished operation again.

Host pauses do not consume the method's active execution time limit. `--max-calls` caps host requests, `--max-solves` caps solves, and `--time-limit` bounds each solve or helper script. Published method parameters and retry rules remain fixed. AutoFormulation retains an expensive search by default; use an explicit call budget when needed and report budget exhaustion as an incomplete search.

`usage.llm_calls` counts distinct host-model requests; the CLI itself makes no LLM API call. Token counts are `null` because the coding agent owns model usage. A native solve status or objective value is execution evidence, not a model's prediction.
