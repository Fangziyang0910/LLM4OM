# 通用 LLM 配置与页面密钥

2026-10-15，SDK／Worker 0.37.0 开发版本。规范由 [FR-05／FR-15](../requirements/v1.0.md)和[插件契约](../plugin-contracts.md)维护。

LLM Provider 与具体模型独立配置，建模方法和求解器复用同一模型调用接口。Web 预设 OpenAI、Google Gemini、Kimi、GLM、OpenRouter、阿里云百炼、DeepSeek，保留 Anthropic 和 OpenAI 兼容选项。预设固定地址，只有 OpenAI 兼容允许修改 URL。模型名称由使用者自由填写。预设目录位于 `workbench.py`，由 bootstrap 提供给页面；提交和预检携带 `llm_preset`，后端校验 Provider 和固定地址。高级 JSON 同样不能改写当前预设地址；CLI／SDK 和第三方 Provider 配置不依赖此页面目录。不新增提供方 SDK、注册接口或配置管理系统。

切换方法／求解器、浏览内置样例不改 LLM 设置。切换供应商分别保留模型与地址草稿，初次切换请填写该供应商的模型名。点击“保存模型配置与密钥”保存当前供应商和选择，开始建模前也会自动保存。刷新页面或重启同一工作区的服务后，恢复上次保存的供应商、模型和配置。原 `.env` 默认服务继续可用。

设置保存在 `<workspace>/.private/llm-settings.local.json`。JSON 分别记录供应商配置、上次选择和按 Provider／地址绑定的密钥；更换地址不会把旧地址的 Key 发给新服务。密钥输入框留空会保留该地址已有 Key，填写后保存则更新 Key。更新采用同目录临时文件替换，文件权限为 600，私有目录创建权限为 700；文件和临时文件均由 Git 忽略。格式错误的已有文件报错，不清空或覆盖。

前台在问题输入区底部的模型按钮显示模型名称及密钥是否配置。点击打开“选择模型”窗口，选择供应商、填写地址和 Key、保存设置；窗口内显示“未配置密钥”“已配置（本机）”“已保存（本机）”或“已填写（未保存）”及掩码。预算与显式连通性检查位于“建模选项”的“高级设置”。默认服务和已保存密钥只向前台返回状态或掩码预览；超过 12 字符时显示前后各 4 字符，中间固定掩码，短密钥全部遮挡。保存后清空密码框，继续显示已保存状态。完整密钥不通过查询接口返回。

模型选择区复用现有 Provider 的目录查询。已有默认或保存密钥时，进入“新建问题”或在编辑器中切换到该服务会自动读取；新填密钥可点击“获取模型列表”。自动查询只在编辑器可见时触发，直接打开运行结果不会读取模型目录；切回编辑器时继续查询并保留未提交的草稿。列表显示服务返回的展示名称和 API ID，选择时只写入 API ID，仍可手动填写。读取不要求先填写模型名，也不要求运行方法或求解器预检；请求受现有代理、凭据隔离、禁止重定向、10 秒和 8 MiB 限制保护。404、认证失败或连接失败显示提示并保留手动输入。分页服务只显示本次返回的一页，并标记 has_more；不自动改写已有模型选择。切换供应商后迟到的目录结果不覆盖新列表。

目录差异由 HTTP Adapter 处理，方法、求解器和页面无需增加供应商分支。路径为 `/compatible-mode/v1` 的百炼兼容地址读取同源 `/api/v1/models?capabilities=TG&page_no=1&page_size=100`，仅查询文本生成模型；将 `output.models[].model/name` 转为统一 ID／名称，并由经过校验的分页数量计算 has_more。其他兼容地址读取 `/models` 的 `data[].id/name`；Messages 读取 `data[].id/display_name`。不自动跨地域换地址，不跟随重定向，也不回退到生成请求。

展示名称和请求 ID 分开处理。例如，2026-10-15 [DeepSeek 官方目录](https://api-docs.deepseek.com/api/list-models/)与[模型说明](https://api-docs.deepseek.com/quick_start/pricing/)对应 `name=DeepSeek-V4.1-Flash`、`id=deepseek-flash`。界面根据实际目录显示名称，配置仍保存 `deepseek-flash`，不把展示名称拼成新的请求 ID。

固定地址按官方文档核对，使用普通按量 API；百炼预设为北京地域，其他地域／业务空间可用 OpenAI 兼容选项。

| 预设 | Base URL | 目录请求与官方来源 |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `/models`，[模型目录](https://developers.openai.com/api/reference/resources/models/methods/list) |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `/models`，[OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai) |
| Kimi | `https://api.moonshot.cn/v1` | `/models`，[列出模型](https://platform.kimi.com/docs/api/list-models) |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | `/models` 标准兼容探测；[兼容指南](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)未明确声明模型目录，待真实密钥验收 |
| OpenRouter | `https://openrouter.ai/api/v1` | `/models`，[模型目录](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties) |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 同源 `/api/v1/models`，[查询模型列表](https://help.aliyun.com/zh/model-studio/list-models)；既有共享地址的实际账户响应待验收 |
| DeepSeek | `https://api.deepseek.com/v1` | `/models`，[模型目录](https://api-docs.deepseek.com/api/list-models/) |
| Anthropic | `https://api.anthropic.com/v1` | `/models`，[List Models](https://platform.claude.com/docs/en/api/models/list) |
| OpenAI 兼容 | 使用者填写 | `/models`，是否支持以服务实际响应为准 |

页面 Key 位于密码输入框，通过 `X-LLM4OM-Provider-Key` 请求头独立提交给本机后端。公开 JSON 仍由原隐私契约校验，不允许内嵌 `api_key`。后端从本地设置解析所选地址的 Key，并按工作项保留内存快照；公开配置只有 `credential_env` 引用。拥有的 CLI 应用进程获得私有环境覆盖，不修改全局 `os.environ`。复用原 Provider／Gateway 的认证、目录检查、预算、取消和响应脱敏。方法输入、生成代码容器、公开运行文件和导出不包含 Key。

浏览器不持久化 Key。服务重启后，恢复、派生重跑和修订自动按已保存运行的 Provider／地址查找本地 Key。原 `.env` 服务也可为地址匹配的历史页面密钥运行提供凭据。结果页“运行密钥”仍支持临时覆盖；该覆盖不改写供应商设置与父运行。只通过旧 HTTP 接口临时提交且未保存到设置的 Key 仍仅在服务内存中保留。

验收入口：

- `tests/test_web_llm_settings.py`：九项预设、固定地址不可覆盖、默认密钥有／无状态与掩码、两个确定性 HTTP 协议、各自模型与私有 Key、空模型名读取目录、名称／ID 投影、404／401／私有响应拒绝、实际 HiGHS 目标 13、运行与导出无 Key、两供应商设置与 600 权限、重启后无 Key 请求头检查／派生求解、无效保存不覆盖原文件、拒绝公开 Key 与默认密钥跨服务复用。
- `tests/web_llm_settings_flow.cjs`：各供应商固定地址、仅兼容选项可编辑、JSON 改写被拒绝、可见状态与掩码、分别保存模型与 Key、刷新恢复、空密钥保留、自定义地址隔离、方法与求解器独立选择、请求头与 JSON 分离、结果页临时覆盖、无浏览器存储与窄屏。
- `tests/web_connectivity_check_flow.cjs`：自动目录读取、展示名称／API ID 选择、手动覆盖、目录失败后继续填写、跨供应商迟到响应隔离、doctor 增量请求计数和零文本生成。
- `tests/web_model_flow.cjs`：直接打开结果页并浏览数学表述时零 POST，进入编辑器后自动读取目录，往返结果页后保留问题草稿。
- `tests/test_connectivity.py`：九项预设的路径与认证在本机 HTTP 服务验收，覆盖 Google 兼容路径、百炼原生结构及分页提示、Messages 名称、缺名称回退 ID、大于 1 MiB 的聚合目录和零生成；合成目录不证明供应商线上支持。
- 公共 Web 设置测试另覆盖百炼原生目录的空模型名读取、ID／名称投影、分页结束，以及错误成功标记、非法分页、非法 ID 和隐藏元数据内 Key 的拒绝。
- 相关 Web 回归、前端类型／构建、Python 类型、仓库检查和安装包静态资源检查。本机服务与 Worker 更新后保持历史工作区内容。

工程 HTTP fixture 不代表各供应商真实模型验收；本轮没有使用外部供应商密钥新增付费调用。

持久化切片验证：10 项 Web 测试通过，最终设置 HTTP 用例再次通过，包含服务重启后无密钥请求头的目录检查和 HiGHS 目标 13 派生求解。四组浏览器流程、前端／Python 类型、仓库检查和打包通过。本机页面保存现有默认配置后，刷新和再次重启服务均恢复成功；私有设置文件权限 600 且被 Git 忽略。原有 6 条运行的 1390 个历史文件逐一核对未变，最终 wheel 的 Web 源码与静态资源和工作区一致。

模型目录切片验证：26 项 Provider 测试、CLI 目录检查、公共 Web 设置／目录用例和五组浏览器流程通过。实际 DeepSeek GET 目录返回 `deepseek-flash → DeepSeek-V4.1-Flash`、`deepseek-v4-pro → DeepSeek-V4-Pro`；本机页面自动显示这两个选项，当前选择保留 `deepseek-flash`。没有发起文本生成，其他供应商未逐家使用真实密钥验收。

供应商目录补齐验证（2026-10-15）：29 项相关 Python 测试和目录浏览器流程通过，覆盖全部九项预设的本地协议响应与百炼公共 Web 调用。55 模块类型检查、363 文件仓库检查、离线构建及包内源码／静态资源一致性检查通过。一次匿名 OpenRouter 目录 GET 返回 462 个模型、773997 字节；重启后的本机 Web 再次使用既有密钥读到上述两个 DeepSeek 模型。其余供应商没有真实密钥验收，GLM 的标准目录探测与百炼既有共享地址仍待真实账户确认。本轮只更新宿主服务，6 条历史运行及私有设置共 1391 个文件的内容哈希保持不变。
