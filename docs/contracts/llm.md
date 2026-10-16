# LLM 契约

供应商设置与使用步骤见 [LLM 配置](../development/llm.md)。本页定义文本调用、资源和凭据行为。

## 文本接口

方法通过 `context.llm.complete(request)` 调用 Gateway。request 使用 `messages`、可选 `request_id` 和逻辑 `role`。实际输入能力按 Provider Manifest 校验。

HTTPTextFactory 声明 `provider_type`、端点路径、请求 ID header、请求编码和响应解码。工厂提供 `create(config, model, environment=...)` 和延迟凭据的 `restore`。初始化不发送生成请求。

公共文本配置包括 `base_url/credential_env/max_output_tokens/max_retries/timeout_s` 和可选 `proxy_url`。只接受明示能力，未支持的 tools、response schema、多模态或流式请求提前拒绝。

远程地址要求 HTTPS；本机 HTTP 仅供 loopback fixture。拒绝 URL 用户信息、query、fragment 和重定向。请求不会隐式读取系统代理。

## Chat Completions 与 Messages

OpenAI 兼容适配器发送 `POST base_url/chat/completions`，使用非流式文本。实际服务是否接受请求参数需要由真实调用验证。

Anthropic 发送 `POST base_url/messages`，带 `anthropic-version: 2023-06-01` 和 `x-api-key`。system 消息按顺序移到顶层文本块，user/assistant 顺序及文本块边界保留。

共同 messages.content 支持字符串或非空文本块数组。Messages 响应必须为合法 assistant message；text 顺序拼接。thinking/redacted_thinking 仅保留私有原始响应，不作为公开文本或 reasoning token 测量。

解码结果包含 `text`、可空的 `response_id/model/finish_reason`、usage，以及可选 `stop_reason`。未返回的模型身份不补写成请求模型。畸形结构和非法计数返回 `invalid_provider_response`。

Messages 的 `end_turn/stop_sequence` 映射为 stop，`max_tokens` 映射为 length。只有 thinking 的截断响应可保存为空文本，由方法报告 `llm_output_truncated`。

## 用量

usage 包含 input、output、total、cached 和 reasoning token，可分别为 `null`。已知零保留为零；布尔值、负值和非有限值拒绝。

Messages 的归一化输入为原 input 加 cache creation 和 cache read。cached 是这两个缓存分量之和，属于输入子集。total 是归一化 input 加 output；任一加数未知时，相应和为 `null`。

cached/reasoning 不能重复加入 total。没有定价来源时，cost 为 `null`。供应商缺少统计时，平台不推测 token 或计费。

## 请求身份与预算

省略 request_id 时分配独立逻辑身份；相同内容可独立采样。显式 ID 用于恢复，绑定消息、角色资源、端点、模型和输出上限。每个实际 HTTP attempt 有独立 UUID。

Gateway 在发送前原子保存 attempt 和 token 预留，并用进程槽限制共享并发。估算采用规范化请求的 UTF-8 字节数，加最大输出预留。估算不是供应商 token 测量。

已知 total 用于结算；未知用量、失败和未知结果保留预留。响应后发现越界时保留实际回复，并返回 `token_budget_overrun`。调用次数可以严格限制，未知供应商用量不能被宣称为精确 token 硬上限。

所有角色共享运行的尝试、token、并发和绝对 deadline。调用超时、退避、Worker 启动与求解上限均受该 deadline 限制。资源清理允许有界额外时间。

## 重试与准备

429、5xx 和连接错误按 `max_retries` 有界退避，间隔从 0.1 秒倍增，最大 1 秒。认证、其他请求错误、非法响应和超时不自动重试。错误 body 不进入公开诊断。

TextProvider.prepare 是本地幂等操作。Gateway 先核对保存记录、预算和 deadline，再准备凭据；真正发送前再次检查取消。准备失败不增加 HTTP attempt 或预留。已准备实例和重试使用固定凭据。

供应商处理后超时的结果可能未知。平台保留相应资源，恢复不重发同一 request_id。成功回复复用原调用身份。完整日志和恢复约束见[执行契约](execution.md#私有资源日志)。

## 角色模型

`llm.role_models` 按准确逻辑角色名映射 `{provider_plugin_id, model, config}`。省略或空映射使用默认模型。角色覆盖需要已声明的在线文本 Provider，Mock/offline 不隐式替代。

admission 保存各角色的 Provider、请求模型、配置、端点哈希和来源。相同模型名称不证明相同权重。trace 记录实际角色与返回身份；恢复要求原资源身份一致。

## 凭据与公开记录

完整密钥仅进入隔离 HTTP 传输和拥有的应用进程。方法、生成代码、公开配置、trace 和导出不获得认证信息。原始响应和解码字符串均检查凭据回显。

.env 只解析字面值，进程环境优先。不执行命令或插值，不修改调用者全局环境。恢复已保存成功响应不需要新密钥。

公开 trace 保存请求/响应身份与哈希、角色/模型、时间、finish、usage、预留和固定诊断。原始正文在私有 archive 中保存。

## 目录与诊断

Provider 可声明 `connectivity_check=models_get/0.1.0`，实现 `check_connectivity(timeout)`。结果为可达或不支持状态，另有可空 `model_listed`、规范化 `models=[{id,name}]` 和 `has_more`。

目录查询最多一次 HTTP 尝试，不生成文本。单端点最多 10 秒、8 MiB；doctor 总检查最多 20 秒且不超过准入 deadline。目录不返回原文或认证 header。

百炼兼容路径读取同源原生目录；其他协议按适配器读取模型端点。分页只读取当前一页，未列出不等于没有生成权限。Web 设置字段见 [Web 契约](web.md)。

公开连接类别限定为 TLS 证书/中断/其他 TLS、DNS、拒绝连接、重置、超时和通用连接错误。类别不证明供应商是否处理或计费，未知预留继续保留。

显式 proxy_url 只支持无认证 HTTP 根地址及 HTTPS CONNECT。隔离传输清除 NO_PROXY 的路由覆盖，调用进程环境不变。不支持 SOCKS、认证、query 或 fragment。
