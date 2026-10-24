Server configuration controls the default LLM, concurrency, shared usage and persistent storage. Run records retain the settings actually used, without keys.

## Common environment variables

| Variable | Purpose |
|---|---|
| `LLM4OM_LLM_PROVIDER` | Default preset provider |
| `LLM4OM_LLM_BASE_URL` | Model service endpoint |
| `LLM4OM_LLM_MODEL` | Model ID actually used in API requests |
| `LLM4OM_LLM_API_KEY` | Default preset key |
| `LLM4OM_LLM_NAME` | Preset display name |
| `LLM4OM_LLM_EXTRA_BODY` | Provider-specific request body as JSON |
| `LLM4OM_DAILY_TOKENS` | Daily input-plus-output token limit per preset |
| `LLM4OM_RUNS_PER_HOUR` | Runs per client address per hour |
| `LLM4OM_SANDBOX_JOBS` | Concurrent solves and check scripts across the service; default 4 and must be positive |
| `TZ` | Day boundary for usage accounting, for example `Asia/Shanghai` |
| `LLM4OM_TRUST_PROXY` | Use the forwarded client address behind a trusted proxy |
| `LLM4OM_SEARCH_API_KEY` | Independent search service key |
| `LLM4OM_SEARCH_BASE_URL` | Independent search endpoint |

Zero or unset daily-token and hourly-run limits mean unlimited. Exhausted daily usage stops before the next LLM call while retaining completed results. Consult `.env.example` for exact complete field names.

## Concurrency and queues

`llm4om serve --jobs` controls active runs, with a default of 4; additional runs queue. `LLM4OM_SANDBOX_JOBS` separately limits all solves and check scripts, including AutoFormulation's parallel checks. Sandbox waiting counts toward the run deadline.

Use one service process per workspace. Keep the same `--workspace` or Compose volume to retain history.

## Backup and restore

Storage includes preset keys, so restrict backup access. Stop the app, copy the complete workspace and restart:

```bash
docker compose stop app
docker compose cp app:/data ./llm4om-backup
chmod -R go-rwx ./llm4om-backup
docker compose start app
```

For restoration, stop the service before copying backup contents to `/data/` so shutdown writes cannot overwrite restored records. Normal saves occur periodically and at exit; forced termination may lose recent unsaved changes. See the [original deployment guide](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/deployment.md) for restoration commands.

## Optional tracing

Enabling LangSmith sends problems, data and model replies to that service. Set `LANGSMITH_TRACING` and its credentials only when that transfer is permitted. Ordinary platform recording does not require external tracing.
