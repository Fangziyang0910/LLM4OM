# 通用 LLM 配置与页面密钥

2026-10-15，SDK／Worker 0.37.0 开发版本。规范由 [FR-05／FR-15](../requirements/v1.0.md)和[插件契约](../plugin-contracts.md)维护。

LLM Provider 与具体模型独立配置，建模方法和求解器复用同一模型调用接口。Web 预设 OpenAI、Google Gemini、Kimi、GLM、OpenRouter、阿里云百炼、DeepSeek，保留 Anthropic 和 OpenAI 兼容选项。预设固定地址，只有 OpenAI 兼容允许修改 URL。模型名称由使用者自由填写。预设目录位于 `workbench.py`，由 bootstrap 提供给页面；提交和预检携带 `llm_preset`，后端校验 Provider 和固定地址。高级 JSON 同样不能改写当前预设地址；CLI／SDK 和第三方 Provider 配置不依赖此页面目录。不新增提供方 SDK、注册接口或配置管理系统。

切换方法／求解器、浏览内置样例不改 LLM 设置。切换供应商分别保留模型与地址草稿，初次切换请填写该供应商的模型名。点击“保存模型配置与密钥”保存当前供应商和选择，开始建模前也会自动保存。刷新页面或重启同一工作区的服务后，恢复上次保存的供应商、模型和配置。原 `.env` 默认服务继续可用。

设置保存在 `<workspace>/.private/llm-settings.local.json`。JSON 分别记录供应商配置、上次选择和按 Provider／地址绑定的密钥；更换地址不会把旧地址的 Key 发给新服务。密钥输入框留空会保留该地址已有 Key，填写后保存则更新 Key。更新采用同目录临时文件替换，文件权限为 600，私有目录创建权限为 700；文件和临时文件均由 Git 忽略。格式错误的已有文件报错，不清空或覆盖。

前台显示“未配置密钥”“已配置（本机）”“已保存（本机）”或“已填写（未保存）”。默认服务和已保存密钥只向前台返回状态或掩码预览；超过 12 字符时显示前后各 4 字符，中间固定掩码，短密钥全部遮挡。保存后清空密码框，继续显示已保存状态。完整密钥不通过查询接口返回。

固定地址按官方文档核对，使用普通按量 API；百炼预设为北京地域，其他地域／业务空间可用 OpenAI 兼容选项。

| 预设 | 固定 Base URL | 官方来源 |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | [API](https://developers.openai.com/api/reference/overview) |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai) |
| Kimi | `https://api.moonshot.cn/v1` | [快速开始](https://platform.kimi.com/docs/get-api-key) |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | [官方调用示例](https://docs.bigmodel.cn/cn/best-practice/case/ai-search-engine) |
| OpenRouter | `https://openrouter.ai/api/v1` | [Quickstart](https://openrouter.ai/docs/quickstart) |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | [Base URL 总览](https://help.aliyun.com/zh/model-studio/base-url) |
| DeepSeek | `https://api.deepseek.com/v1` | [官方 Chat Completions 示例](https://api-docs.deepseek.com/quick_start/agent_integrations/workbuddy/) |
| Anthropic | `https://api.anthropic.com/v1` | 沿用原 Messages Provider 默认地址 |

页面 Key 位于密码输入框，通过 `X-LLM4OM-Provider-Key` 请求头独立提交给本机后端。公开 JSON 仍由原隐私契约校验，不允许内嵌 `api_key`。后端从本地设置解析所选地址的 Key，并按工作项保留内存快照；公开配置只有 `credential_env` 引用。拥有的 CLI 应用进程获得私有环境覆盖，不修改全局 `os.environ`。复用原 Provider／Gateway 的认证、目录检查、预算、取消和响应脱敏。方法输入、生成代码容器、公开运行文件和导出不包含 Key。

浏览器不持久化 Key。服务重启后，恢复、派生重跑和修订自动按已保存运行的 Provider／地址查找本地 Key。原 `.env` 服务也可为地址匹配的历史页面密钥运行提供凭据。结果页“运行密钥”仍支持临时覆盖；该覆盖不改写供应商设置与父运行。只通过旧 HTTP 接口临时提交且未保存到设置的 Key 仍仅在服务内存中保留。

验收入口：

- `tests/test_web_llm_settings.py`：九项预设、固定地址不可覆盖、默认密钥有／无状态与掩码、两个确定性 HTTP 协议、各自模型与私有 Key、目录检查、实际 HiGHS 目标 13、运行与导出无 Key、两供应商设置与 600 权限、重启后无 Key 请求头检查／派生求解、无效保存不覆盖原文件、拒绝公开 Key 与默认密钥跨服务复用。
- `tests/web_llm_settings_flow.cjs`：各供应商固定地址、仅兼容选项可编辑、JSON 改写被拒绝、可见状态与掩码、分别保存模型与 Key、刷新恢复、空密钥保留、自定义地址隔离、方法与求解器独立选择、请求头与 JSON 分离、结果页临时覆盖、无浏览器存储与窄屏。
- 相关 Web 回归、前端类型／构建、Python 类型、仓库检查和安装包静态资源检查。本机服务与 Worker 更新后保持历史工作区内容。

工程 HTTP fixture 不代表各供应商真实模型验收；本轮没有使用外部供应商密钥新增付费调用。

本轮持久化验证：10 项 Web 测试通过，最终设置 HTTP 用例再次通过，包含服务重启后无密钥请求头的目录检查和 HiGHS 目标 13 派生求解。四组浏览器流程、前端／Python 类型、仓库检查和打包通过。本机页面保存现有默认配置后，刷新和再次重启服务均恢复成功；私有设置文件权限 600 且被 Git 忽略。原有 6 条运行的 1390 个历史文件逐一核对未变，最终 wheel 的 Web 源码与静态资源和工作区一致。
