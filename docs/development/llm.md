# LLM 配置

Web 的操作步骤见 [README](../../README.md#模型与密钥)。本文说明供应商配置、模型目录和凭据边界；字段见 [LLM 契约](../contracts/llm.md)。

## 供应商与协议

| 预设 | Base URL | 目录 |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `/models` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `/models` |
| Kimi | `https://api.moonshot.cn/v1` | `/models` |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | 标准 `/models` 探测，线上支持待账户确认 |
| OpenRouter | `https://openrouter.ai/api/v1` | `/models` |
| 阿里云百炼（北京） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 同源 `/api/v1/models` |
| DeepSeek | `https://api.deepseek.com/v1` | `/models` |
| Anthropic | `https://api.anthropic.com/v1` | `/models`，Messages 认证 |
| OpenAI 兼容 | 使用者填写 | `/models`，以服务实际支持为准 |

固定地址来自代码中的供应商预设。其他地域、业务空间或自定义地址使用 OpenAI 兼容选项。预设存在不代表每家供应商都已完成真实生成验收。

OpenAI 兼容协议发送非流式文本 Chat Completions。Anthropic 使用独立 Messages 适配器。当前接口不支持图片、流式输出、工具调用或原生 JSON Schema；不支持的请求在生成前拒绝。

## 模型目录

编辑器对已有默认或保存密钥的服务自动读取目录。新填密钥可以点击“获取模型列表”。结果页直接打开时不自动查询。切回编辑器后保留问题草稿。

列表将展示名称和请求 ID 分开。选择模型只保存 API ID，已有手动选择不会被目录自动改写。无法读取目录时，保留手动填写。迟到的响应不能覆盖当前供应商列表。

目录请求只读取一页，最多 10 秒和 8 MiB。`has_more` 表示仍有后续页。目录可达、模型列出和生成权限是不同判断。

百炼请求同源 `/api/v1/models?capabilities=TG&page_no=1&page_size=100`，读取 `output.models[].model/name`。其他兼容服务读取 `data[].id/name`，Messages 读取 `data[].id/display_name`。请求不跨地域重试，不跟随重定向，也不回退到生成。

接口来源：[OpenAI](https://developers.openai.com/api/reference/resources/models/methods/list)、[Google](https://ai.google.dev/gemini-api/docs/openai)、[Kimi](https://platform.kimi.com/docs/api/list-models)、[GLM](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)、[OpenRouter](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)、[百炼](https://help.aliyun.com/zh/model-studio/list-models)、[DeepSeek](https://api-docs.deepseek.com/api/list-models/)、[Anthropic](https://platform.claude.com/docs/en/api/models/list)。

## 密钥保存与恢复

页面通过密码输入框接收密钥，并用 `X-LLM4OM-Provider-Key` 请求头独立提交。公开配置只保存环境变量引用。密钥按 Provider 和规范化 Base URL 绑定；换模型可以复用同一端点密钥，换端点不能借用其他服务密钥。

设置保存在 `<workspace>/.private/llm-settings.local.json`，原子写入，权限为 `600`，由 Git 忽略。未提供新密钥时保留原密钥。保存失败不覆盖已有文件。查询接口只返回配置状态和掩码预览。

服务重启后，恢复和派生运行按保存的 Provider/URL 查找密钥。匹配的 `.env` 默认服务也可提供凭据。结果页临时密钥覆盖不改写供应商设置或父运行。浏览器不持久化密钥。

## CLI 与角色模型

RunConfig 的 `llm` 选择默认 Provider、模型和公开配置。`llm.role_models` 可按逻辑角色覆盖，所有角色共享一次运行的预算、并发和截止时间。每次调用保存实际角色及请求/返回模型身份。

凭据先读取配置目录的 `.env`；不存在时读取当前工作目录的 `.env`。进程环境覆盖文件值。只解析字面 `KEY=value`，不执行插值或命令。已保存响应的恢复不要求再次提供密钥。

```bash
uv run --locked llm4om doctor --config /path/to/run.yaml
uv run --locked llm4om doctor --config /path/to/run.yaml --check-connectivity
```

默认预检不联系模型端点。显式连通性检查读取目录，不生成文本。工程 Mock 不读取真实凭据。

## 代理与失败诊断

默认直连，不自动选择系统代理。需要代理时，在 Provider 配置中设置 `proxy_url`，或为 Web 设置 `LLM4OM_LLM_PROXY_URL`。

当前支持无认证的 HTTP 代理及 HTTPS CONNECT。代理 URL 只允许根路径，不含查询或 fragment；不支持 SOCKS。TLS 校验、重定向拒绝、取消和超时边界保持有效。

公开诊断只显示 TLS、DNS、拒绝连接、重置、超时等固定类别。未知结果保留预算预留；错误响应、完整密钥和原始异常文本不进入公开记录。
