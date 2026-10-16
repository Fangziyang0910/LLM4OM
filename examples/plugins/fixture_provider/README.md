# 独立文本 Provider 示例

本例验证可信 Provider 包通过共同 entry point 接入。它是文本协议工程适配器。字段与恢复规则见 [插件契约](../../../docs/contracts/llm.md)。

在仓库根目录构建并安装到当前环境：

```bash
uv build --wheel examples/plugins/fixture_provider --out-dir /tmp/llm4om-provider-wheel
uv pip install --python .venv/bin/python --no-deps /tmp/llm4om-provider-wheel/llm4om_fixture_provider-0.1.0-py3-none-any.whl
uv run --locked llm4om plugins list
```

配置中的 `llm.provider_plugin_id` 设为 `llm4om.examples.openai_text`，并显式填写模型、base_url和credential_env。其余配置使用现有兼容方法与求解路径，例如 [文本 LLM 配置](../../specs/feedback-repair.yaml)。密钥只放在本机环境变量或忽略提交的 `.env` 中。doctor读取凭据并检查本机准备条件，默认不发模型请求。

本例继承HTTPTextFactory与OpenAICompatibleProvider，声明自己的Manifest与插件ID。新文本协议可以继承HTTPTextProvider，实现_request与decode_reply；共享Gateway负责预算、重试、私有原始响应和恢复。安装的插件代码在可信宿主执行；生成模型的Worker只接收公开输入和建模产物。

插件构造和describe不得发送付费请求。Factory配置必须符合自包含JSON Schema。修改插件源码、包文件、版本或Manifest后，旧run不会自动迁移；保留旧环境以读取其运行证据。
