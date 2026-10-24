A preset stores provider, endpoint, model ID, API key and request parameters. Modeling and conversation select it by name; the server uses its saved configuration.

## Add and select a preset

Open “LLM presets,” choose a provider, enter model ID and key, and configure endpoint and display name as needed. Select the saved preset in run settings or conversation.

Providers include OpenAI, Google Gemini, Kimi, GLM, OpenRouter, Alibaba Bailian, DeepSeek, Anthropic and OpenAI-compatible services. Self-hosted models can use compatible endpoints.

| Field | Value |
|---|---|
| Display name | A recognizable name such as “Team modeling” |
| Model ID | Identifier accepted by the service |
| Endpoint | API endpoint for the selected protocol |
| API key | Credentials for that endpoint |
| Advanced parameters | Supported provider-specific JSON fields |

## Server default preset

Administrators configure `.env` to provide the first-listed `env` preset:

```dotenv
LLM4OM_LLM_PROVIDER=openai_compatible
LLM4OM_LLM_BASE_URL=https://api.example.com/v1
LLM4OM_LLM_MODEL=your-model-id
LLM4OM_LLM_API_KEY=your-api-key
LLM4OM_LLM_NAME=Team model
```

Replace placeholders and recreate the service. UI-added presets use the workspace's private configuration; the default is managed through server environment variables.

## DeepSeek and structured calls

DeepSeek uses a dedicated client. TriVAL uses forced tool selection; configure the run preset as:

```json
{"thinking": {"type": "disabled"}}
```

The conversation thinking toggle controls that conversation's replies and is retained there. Modeling tools read run presets. Other providers use fields supported by their client integrations.

## OpenRouter and advanced parameters

OpenRouter uses a dedicated integration. An example reasoning setting is:

```json
{"reasoning": {"effort": "high"}}
```

Advanced fields are validated at submission; use dedicated fields for model, key and common options. Expand request errors for details. Failed saves retain entered form values.

## Change configuration and inspect usage

Presets are fixed configurations. Delete and re-add to change parameters, obtaining a new ID. Select an available preset when running an older plan again. Historical runs retain their configuration summaries and results.

The preset dialog shows daily usage. Administrators manage shared [quotas and concurrency](../configuration/). Credentials stay in server-private files; records retain display configuration and usage.

## Resolve connection issues

For 401, inspect credentials and provider. For 404, inspect endpoint and model ID. For tool errors, inspect structured-output support and advanced fields. Run a small [Direct](../direct/) example first, then check the validation or conversation workflow you need.
