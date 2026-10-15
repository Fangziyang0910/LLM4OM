# S03 显式模型连通性检查

用途：记录FR-06的CLI／Web模型接口目录检查。状态：SDK／Worker0.35.0开发实现与本机验收；不代表完整1.0发布。规范来源为[需求规格](../requirements/v1.0.md)、[插件契约](../plugin-contracts.md)和[执行设计](../design/experiments-and-interfaces.md)。

## 使用与证据范围

```bash
llm4om doctor --config /path/to/run.yaml
llm4om doctor --config /path/to/run.yaml --check-connectivity
```

默认 doctor 只检查配置、依赖、实际Solver环境与兼容性，不向模型端点发送HTTP。显式开关检查默认Provider及角色Provider的模型目录。Web勾选“检查配置时联网测试模型接口”后点击“检查配置”，调用相同CLI；结果直接显示在配置区，完整报告保留在高级环境信息中。Web 的模型选择区另会按已保存密钥自动读取目录，详见[模型选择](s09-llm-settings.md)。

HTTP文本Provider通过可选`models_get/0.1.0`能力和`check_connectivity(timeout)`接入；`plugins list`显示该声明。当前OpenAI-compatible与Messages Adapter分别发送各自认证格式的GET `/models`，不调用文本生成端点，不使用生成重试或Run Gateway。Mock为`not_applicable`，无声明的Provider为`not_supported`；不回退到生成请求。

检查复用已有隔离传输、显式代理、禁止重定向和凭据保护。每个端点最多一次HTTP尝试／10秒，总检查最多20秒且不超过admission deadline；响应上限1MiB。报告保留状态、角色、模型、耗时、HTTP状态、固定诊断，以及可用于选择模型的规范化 ID／展示名称和 has_more；不返回模型目录原文或认证header。

目录响应可达并符合结构时记录`reachable`；`model_listed`只表示该页包含请求的模型ID。分页和别名可导致未列出，因此不把这个布尔值作为生成能力或建模质量证明。两个协议的目录与认证字段依据[OpenAI模型目录](https://developers.openai.com/api/reference/resources/models/methods/list)和[Claude模型目录](https://platform.claude.com/docs/en/api/models/list)，读取日期2026-10-10。

CLI的`preflight_ok`与`connectivity_checks`分开：请求检查后，只有通过或无需网络时返回0；失败／未支持／未完成返回1，配置预检结果仍保留。Task-only doctor不检查模型。检查不创建run、不生成文本、不重置已有预算。

## 验收

本机`tests/test_connectivity.py`通过默认零HTTP、两个协议正确GET／认证、目录404保留不支持、零生成和凭据未导出。已保存回复回放的受影响Provider检查与4项显式代理检查通过；42模块类型检查通过。不是全量回归。

Chrome通过默认零HTTP、显式一次目录GET、可读模型ID记录和390px布局；没有生成POST或创建任务。入口为`tests/helpers/connectivity_server.py`和`tests/web_connectivity_check_flow.cjs`，仅使用本机合成凭据。Web启动同时修正进程环境配置的读取：无`.env`时也读取进程环境；存在文件时仍由进程环境覆盖。

实际指定DeepSeek／显式代理配置的一次CLI检查：admission通过，目录请求在约5.168秒后返回`provider_connection_error`／`tls_interrupted`，`generation_requests=0`。没有重试、生成或修改代理路由。该观察不证明故障位于代理或Provider，也不改变既有成功的建模／求解记录。

本机运行、检查报告和构建记录位于`/tmp/llm4om-connectivity-evidence`，不提交凭据或运行数据。最终Worker身份在交付记录中固定；早期校验镜像保留为0.35.0-precheck，不用于最终支持声明。

最终Worker0.35.0身份为`sha256:4a45e114988733c17d06ecdde837506ccb4547cf45f7a92e5f5a265a2640e9ec`。相同工程Mock输入经CLI／实际容器HiGHS得到目标13、completed；该运行证明新版执行流程，不证明外部模型质量。新增CLI／网页检查、共享传输回放／显式代理、42模块类型检查和274文件仓库检查通过，未运行全量回归、batch或Actions。
