# S05-B Anthropic Messages protocol investigation

Date: 2026-10-09. Status: protocol research and one real compatibility probe; **Provider adapter not implemented**. Scope follows [S05-B](../implementation-plan.md#s05-真实-llm-与反馈修正), [LLM contracts](../plugin-contracts.md), and [S05-A](s05-provider.md). These observations prepare the second protocol Adapter; they are not platform integration acceptance.

## Protocol and accounting

Messages requests use `POST /v1/messages`, explicit model, positive `max_tokens`, and user/assistant content. System content is a separate request field. Send `anthropic-version`; the inspected version is `2023-06-01`. Official authentication supports Bearer and the legacy `x-api-key` header. The compatibility probe used the latter against the user's already authorized host. Sources: [Messages](https://platform.claude.com/docs/en/api/messages/create), [versions](https://platform.claude.com/docs/en/api/versioning), [authentication](https://platform.claude.com/docs/en/manage-claude/authentication).

Responses contain message identity, actual model, content blocks and `stop_reason`. Text collection must preserve block order; thinking blocks do not establish a reported reasoning-token count. Tools, images and streaming need declared support rather than an implicit fallback. Input usage is the sum of uncached input, cache creation and cache read counts; unknown components stay unknown. Output includes the response's reported output count. Cached input is a subset of total input, not another additive cost after normalization. Sources: [Messages](https://platform.claude.com/docs/en/api/messages/create), [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

HTTP error responses have typed diagnostics; authentication/permission/request errors are distinct from transient 429/5xx/529 and timeout. `request-id` differs from the existing OpenAI-compatible header. Keep bounded retry/deadline, reservation and cancellation semantics in the shared Gateway; do not introduce a hidden second client/retry budget. Source: [errors](https://platform.claude.com/docs/en/api/errors).

## Actual configured-service evidence

The same `https://api.x5m5x.com/v1` endpoint and authorized private project credential were used. GET `/messages` returned404, which did not establish POST support. One POST with `deepseek-v4-pro-0813`, output cap64 and a trivial connection prompt returned HTTP200 in6.303s: `type=message`, actual model exactly matched, content block types thinking/text, `stop_reason=end_turn`. Reported usage: uncached input40, output18, cache creation0, cache read0; derived total58. No separate reasoning count or price was reported; cost remains unknown.

Evidence metadata: `/tmp/llm4om-s05b/messages-probe.json`; request count1, no retries. Raw reply stays outside the repository in a private directory0700/file0600. Credential/header values were not printed or stored in public metadata, and no model change was made. This proves Messages compatibility of this configured service, not use of Anthropic model weights or an implemented/verified `llm4om.providers.anthropic` path. Adapter parsing, budget/crash restoration, public CLI solving and independent review remain required S05-B work.
