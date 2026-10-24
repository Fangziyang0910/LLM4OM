预设模型是一组固定的大模型配置：服务商、接口地址、模型 ID、密钥和请求参数。建模与对话选择预设，不在每次运行中临时填写密钥。

## 添加预设

点击左下角“预设模型”，选择服务商，填写模型 ID、密钥和需要的接口地址后保存。预设名称只控制显示，实际请求使用模型 ID。支持 OpenAI、Gemini、Kimi、GLM、OpenRouter、百炼、DeepSeek、Anthropic，以及 OpenAI 兼容接口。

保存失败会保留表单内容。401 通常需要核对密钥；404 需要核对地址、协议或模型 ID。要更换固定参数，删除原预设后重新添加；新预设会获得新 ID。

## 服务器默认预设

在 `.env` 中配置以下字段，可提供 id 为 `env` 的默认预设：

```dotenv
LLM4OM_LLM_PROVIDER=openai_compatible
LLM4OM_LLM_BASE_URL=https://api.example.com/v1
LLM4OM_LLM_MODEL=your-model-id
LLM4OM_LLM_API_KEY=your-api-key
LLM4OM_LLM_NAME=Team model
```

这是占位示例，请替换为真实服务信息。默认预设只能在服务器修改，页面不能删除它。密钥保存在服务器私有配置中，不进入运行记录或生成代码环境。

## 服务商特有参数

DeepSeek 与 TriVAL 搭配时，结构化输出需要关闭思考模式，可在额外请求参数中填写：

```json
{"thinking": {"type": "disabled"}}
```

对话中的 DeepSeek“深度思考”开关只控制该轮回复；建模工具仍按运行预设执行。OpenRouter 可使用专用推理参数，当前集成不支持的字段会报错。额外参数不能覆盖模型、密钥、温度等已有字段或调用记录回调。

## 用量与历史

预设对话框显示当天用量。服务可设置每日 token 上限，详见[配置与用量](../configuration/)。删除预设不删除历史结果；再次执行旧运行时，需要选择可用预设。
