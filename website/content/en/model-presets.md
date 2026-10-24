An LLM preset fixes a provider, endpoint, model ID, key and request parameters. Modeling and conversations select a preset rather than accepting a fresh key on each run.

## Add a preset

Open LLM presets at the lower left. Select the provider, enter its model ID, key and required endpoint, then save. A preset name controls display only; API requests use the model ID. Supported providers include OpenAI, Gemini, Kimi, GLM, OpenRouter, Bailian, DeepSeek, Anthropic and OpenAI-compatible services.

Failed saves retain the form. For 401 errors, check the key; for 404, check the endpoint, protocol and model ID. To change fixed parameters, delete and recreate the preset. The new preset receives a new ID.

## Server default preset

Set these fields in `.env` to provide the default preset with ID `env`:

```dotenv
LLM4OM_LLM_PROVIDER=openai_compatible
LLM4OM_LLM_BASE_URL=https://api.example.com/v1
LLM4OM_LLM_MODEL=your-model-id
LLM4OM_LLM_API_KEY=your-api-key
LLM4OM_LLM_NAME=Team model
```

Replace these placeholders with actual service details. Only the server configuration can change this default; the UI cannot delete it. Keys stay in private server configuration, outside run records and the generated-code environment.

## Provider-specific parameters

TriVAL's structured output requires forced tool selection. With DeepSeek, disable thinking in the extra request body:

```json
{"thinking": {"type": "disabled"}}
```

The DeepSeek thinking toggle in chat controls that reply; modeling tools still use the run preset. OpenRouter supports dedicated reasoning parameters, while unsupported fields produce an error. Extra parameters cannot replace existing model, key or temperature fields, or recording callbacks.

## Usage and history

The preset dialog shows daily usage. The service can enforce daily token limits; see [Configuration and usage](../configuration/). Deleting a preset leaves saved results intact. Rerunning an old record requires an available preset.
