# 通用 LLM 配置与页面密钥

2026-10-15，SDK／Worker 0.37.0 开发版本。规范由 [FR-05／FR-15](../requirements/v1.0.md)和[插件契约](../plugin-contracts.md)维护。

LLM Provider 与具体模型独立配置，建模方法和求解器复用同一模型调用接口。Web 预设 OpenAI、Google Gemini、Kimi、GLM、OpenRouter、阿里云百炼、DeepSeek，保留 Anthropic 和 OpenAI 兼容选项。预设固定地址，只有 OpenAI 兼容允许修改 URL。模型名称由使用者自由填写。预设目录位于 `workbench.py`，由 bootstrap 提供给页面；提交和预检携带 `llm_preset`，后端校验 Provider 和固定地址。高级 JSON 同样不能改写当前预设地址；CLI／SDK 和第三方 Provider 配置不依赖此页面目录。不新增提供方 SDK、注册接口或配置管理系统。

切换方法／求解器、浏览内置样例不改 LLM 设置。切换供应商分别保留本页的模型与地址草稿，初次切换请填写该供应商的模型名。密钥草稿按 Provider／地址保存，改为另一个地址时不带入前一个地址的 Key。原 `.env` 默认服务仍可使用；更换协议或地址后，需提供对应服务的 Key，不能自动把默认服务的密钥转发给新地址。普通兼容性检查不要求网络或 Key；显式目录检查和运行使用填写的 Key。

前台显示“未配置密钥”“已配置（本机）”或“已填写（本页）”。默认服务只向 bootstrap 返回配置状态和掩码预览；超过 12 字符时显示前后各 4 字符，中间固定掩码，短密钥全部遮挡。页面输入同样显示掩码预览。完整密钥不通过查询接口返回。

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

页面 Key 位于密码输入框，通过 `X-LLM4OM-Provider-Key` 请求头独立提交给本机后端。公开 JSON 仍由原隐私契约校验，不允许内嵌 `api_key`。后端按工作项保留内存密钥，公开配置只有 `credential_env` 引用；拥有的 CLI 应用进程获得私有环境覆盖，不修改全局 `os.environ`。复用原 Provider／Gateway 的认证、目录检查、预算、取消和响应脱敏。方法输入、生成代码容器、工作区文件和导出不包含 Key。

Key 不写入 `.env`、浏览器存储或公开产物；关闭页面会清空输入框，重启服务会清空服务内存。已有页面密钥运行可在结果页“运行密钥”中重新填写，再恢复、派生重跑或修订；已保存配置与父运行不改写。原来使用服务端环境的工作项继续使用原凭据来源。

验收入口：

- `tests/test_web_llm_settings.py`：九项预设、固定地址不可覆盖、默认密钥有／无状态与掩码、两个确定性 HTTP 协议、各自模型与私有 Key、目录检查、实际 HiGHS 目标 13、运行与导出无 Key、服务重启后重新供给 Key 派生求解、拒绝公开 Key 与默认密钥跨服务复用。
- `tests/web_llm_settings_flow.cjs`：各供应商固定地址、仅兼容选项可编辑、JSON 改写被拒绝、可见状态与掩码、切换供应商／自定义地址的模型与 Key 隔离、方法与求解器独立选择、请求头与 JSON 分离、结果页密钥重填、无浏览器存储与窄屏。
- 相关 Web 回归、前端类型／构建、Python 类型、仓库检查和安装包静态资源检查。本机服务与 Worker 更新后保持历史工作区内容。

工程 HTTP fixture 不代表各供应商真实模型验收；本轮没有使用外部供应商密钥新增付费调用。

本轮本机验证：四组浏览器流程、前端／Python 类型、仓库检查与打包通过；容器 HiGHS 算例目标为 13。本机 Web 已更新，6 条运行的 1390 个历史文件逐一核对未变。10 项 Web 测试中 9 项首轮通过，批量取消用例首轮出现 failed／cancelled 状态差异，独立重跑该测试文件的 2 项用例均通过；本轮没有修改批量执行逻辑。
