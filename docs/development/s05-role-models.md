# S05-D1 角色模型配置

SDK／Worker0.14.0 开发实现；[#30](https://github.com/Fangziyang0910/LLM4OM/issues/30)。规范由 [插件契约](../plugin-contracts.md)维护；原S05-D的澄清／交互恢复与S05-C公共反馈修正仍待实现，此切片不将它们标为完成。

`llm`声明默认Provider/model/config，`llm.role_models`按实际逻辑角色名称提供独立覆盖。未配置的角色使用默认选择；角色请求仍走同一个Gateway，不获得另一份预算或并发限制。配置前检查每个Provider的能力和配置；目前只允许在线HTTP文本Provider，Mock角色覆盖明确拒绝。

每个请求使用选定角色的实际协议、模型、输出上限、重试与超时。角色、requested／returned model、Provider与endpoint hash写入逐次记录。所有角色共用attempt／token／concurrency／绝对deadline、取消和durable journal。成功响应无密钥重放；未知结果保留预留，不能悄悄重发。角色endpoint/model/cap变化拒绝复用原身份。

报告的 `same_requested_model_roles` 只表示所声明模型名称相同，不证明权重相同。`heterogeneous_role_models`表示声明的模型名称不同。`same_role_resources`／`different_role_resources`另行比较Provider/model/config；不能把同名模型的不同服务当作相同实验条件。

## 配置

以下片段合入正常RunConfig，其余求解／执行／预算保持显式。endpoint和model是示例占位符，凭据变量名不包含密钥。逻辑role通过`llm.complete({role, messages, request_id})`声明。

```yaml
llm:
  provider_plugin_id: llm4om.providers.openai_compatible
  model: configured-default-model
  config:
    base_url: https://api.example.com/v1
    credential_env: LLM4OM_LLM_API_KEY
  role_models:
    formulation:
      provider_plugin_id: llm4om.providers.openai_compatible
      model: configured-formulation-model
      config:
        base_url: https://api.example.com/v1
        credential_env: LLM4OM_LLM_API_KEY
```

Direct默认逻辑role为formulation。OptiMUS和CoE使用其实际role字符串，见各自call记录；不在核心硬编码方法的专家名称。覆盖支持跨OpenAI-compatible／Messages协议，恢复按实际调用协议解码。未配置`role_models`时保留默认路径和资源身份。

## 当前证据

本机HTTP／Gateway测试覆盖不同模型与cap、共享总预算／并发、取消后的未知预留、模型／endpoint／cap变化拒绝、跨协议实际decoder和无密钥重放。SDK／实际HiGHS验收已观察formulation-model被选中并得到目标13；公共admission检查无HTTP地拒绝未知／非法／Mock角色Provider。当前8项角色聚焦测试已通过，基础Provider26项回归通过。干净Python3.11wheel的8项角色测试／9.680秒通过，源码／wheel／Worker一致。完整本机回归与独立审阅仍待完成；合成模型名不代表真实远程模型权重验收。

真实 run `9323290a2ac44b16b8692376d7b8c245` 的默认配置为OpenAI-compatible，Formulation角色覆盖为Messages；实际一次deepseek-v4-pro-0813调用／6674已报告token，成本未知。实际HiGHS得到 x_A=3、x_B=2、目标13，公共模型域／利润／两行资源约束核对正确。冻结检查器预声明qty_A／qty_B，所以该协议结果仍为unknown_mapping，未事后改写policy；另存公开模型审阅与映射检查，原始CSV独立计算13。两种证据分开记录，不当作benchmark准确率。无密钥CLI恢复保持账本和调用不变。

代码hash `f1896d2df3fc1eae7c7876939bc2025c7a99d6620fe971d60006c6b442f9ef6d`，Worker镜像 `sha256:f8df356afb6dcadea31c4b5a507b9e2404598f79f81220aebe7bdf23983f18ad`。182个源文件、82个公开运行文件与53个wheel条目通过实际密钥扫描。证据在 `/tmp/llm4om-s05d-roles/real-acceptance/verification.json` 和相邻本机材料，不提交运行数据。
