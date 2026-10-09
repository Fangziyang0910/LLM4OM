# S05-A Provider 实现与验收记录

状态：S05-A 当前文本 Provider 范围已实现，Python 包 0.4.0 未发布；已完成两个真实外部 Provider／容器案例、两版本回归与独立审阅后的修复。远程 CI 单独记录。规范来源为 [插件契约](../plugin-contracts.md)、FR-14～19 与 [S05-A](../implementation-plan.md)。核心 schema 仍为 0.2.0，IR 为 0.1.0，方法 profile 为 grounded_single_candidate/0.1.0。完整 1.0 目标保持不变。

## 使用

从现有 run.yaml 复制配置，保持 Direct、编译器、Backend 与 Solver 的选择。替换 llm：

```yaml
llm:
  provider_plugin_id: llm4om.providers.openai_compatible
  model: deepseek-v4-pro-0813
  config:
    base_url: https://api.example.com/v1
    credential_env: LLM4OM_LLM_API_KEY
    max_output_tokens: 16384
    max_retries: 1
    timeout_s: 180
```

base_url 必须替换为实际端点。明示模型不从环境自动替换。发送到 base_url/chat/completions，使用 max_tokens、stream=false。该请求选项必须由真实网关验收；不能由 OpenAI 文档推断第三方支持。HTTPS 支持远程端点，HTTP 仅支持 loopback fixture。拒绝 URL 用户信息、query、fragment 和重定向；不使用环境代理。text 是唯一能力，tools、response_schema、stream 与任意 generation options 均不支持。

凭据优先从 RunConfig 所在目录的 .env 读取；文件不存在时读取当前工作目录的 .env，再由进程环境覆盖。这样在项目根目录执行命令时可以复用项目私有凭据。仅解析 literal KEY=value，可带 export 和成对引号；不执行命令、不插值、不修改进程环境。当前不支持多行值、转义或行尾注释。只把配置指定的 credential_env 值交给 Provider；方法、公开配置、Worker 和 trace 不获得认证 header。doctor 只做 admission，不发送 HTTP。缺凭据或不支持的参数在方法运行前拒绝；offline 只接受显式 Mock。没有自动 fallback。

本地 HTTP 验证必须显式选 trusted_local；生产 container 测试仍要求真实 Docker，测试不自动跳过。token 预算需容纳完整输入的 UTF-8 字节估算与最大输出预留；微型示例测试使用 max_total_tokens=30000、wall_time_s=300。修改配置后，从项目根目录运行 `llm4om doctor --config PATH` 做免费预检，再运行 `llm4om run --problem examples/specs/problem.json --config PATH`。

## Direct 输出

Direct 发送完整已投影的公开 ProblemSpec 和 `{data_id: CSV原文}`，包含显式数值。system 消息定义下列紧凑 JSON；user 消息为 `{problem, data}`。无数据的问题发送空 data 对象，不要求手工需求拆分或 oracle。

```text
{
  representation: {
    sets: [{id, elements 或 source:{data_id,column}}],
    parameters: [{id,index_sets,value 或 source:{data_id,column,key_column}}],
    variables: [{id,index_sets,domain,lower_bound,upper_bound,requirement_ids}],
    objective: {sense,expression_text,requirement_ids},
    constraints: [{id,expression_text,requirement_ids}]
  },
  structured_ir: {
    problem_type: lp|milp,
    variables: [{id,name,domain,lower_bound,upper_bound,requirement_ids}],
    objective: {sense:min|max,expression,requirement_ids},
    constraints: [{id,expression,sense:le|ge|eq,rhs,requirement_ids}],
    assumptions: []
  }
}
expression = {constant:有限数,terms:[{variable_id,coefficient:有限数}]}
domain = continuous|integer|binary
```

五元素细则及 LPIR 数学语义复用契约。LLM 不生成 artifact、文件 hash、平台 ID／引用或 provenance。Direct 适配器生成这些字段，核心使用实际保存的引用。五元素与 IR 标为联合生成，不能称为文本的确定性编译。Code 来源为确定性 LPIR 编译。Mock 的旧完整 packet 与独立 fixture 方法的 MethodOutcome／ModelProposal 保留。

## Gateway 资源与恢复

公共 HTTP seam 为 OpenAICompatibleFactory.create(config, model, environment=...) 和 Gateway(provider, budget, archive).complete(request)。请求允许 messages、request_id、role。省略 request_id 时分配独立逻辑身份，相同内容也可用于独立采样。显式 request_id 才用于成功回复恢复；相同 ID 的内容／端点／模型／输出上限必须一致。

每个真实 attempt 有独立 UUID。Gateway 在 HTTP 前用文件锁原子保存尝试与 token 预留，OS slot 锁限制共享并发。429、5xx 和连接错误最多重试 max_retries 次，退避为 0.1、0.2、0.4…秒，最大 1 秒。401／403、其他 4xx、不支持请求和非法响应不重试。超时保留未知结果，不主动重发。HTTP 错误 body 不进入公开诊断。

估算为规范化请求 UTF-8 字节数；它是 admission 估算，不是供应方 token 测量。响应保留 input、output、total、cached、reasoning；缺字段为 null，cached／reasoning 不重复加入 total。没有定价表，cost 为 null。已知 total 结算预留，未知 total 或失败保守持有预留。结算后继续计入其他未知 attempt 的预留；最后调用实测占用越界保存成功回复并返回 token_budget_overrun。共享绝对 deadline 限制调用 timeout、重试、Docker admission／create、Worker 启动、容器墙钟与 Solver time_limit。清理仍允许有限额外时间以回收进程和容器。

原始回复和资源状态保存在公开 run 目录之外的 `.private/<run_id>/state.json`，目录 0700，文件 0600。公开 bundle 只列 llm-trace.json 摘要：请求／回复身份与 hash、模型、角色、时间、finish、usage 和稳定诊断。没有 prompt、reply 或 header。

重新构造 Gateway 时使用相同 archive 和预算，成功回复直接复用，不重复 HTTP；未知身份拒绝重新发送，预留继续占用。预算不同拒绝恢复。这里恢复的是 Provider 资源，不是 CLI resume 或方法 checkpoint。

## 本地证据与剩余验收

使用 Python 3.11／3.12 的完整 SDK 与 solve extra；Provider 本地 HTTP 测试覆盖成功、usage、重试、认证、预算、共享并发、保存回复恢复、持续滴流、截止与取消。CLI pipeline 覆盖数据 MILP=13、无数据 LP=40/3、截断输出和免费 admission。HTTP 凭据走子进程私有 stdin，不进入 argv、公开 trace 或 Worker。

新增嵌套配置 CLI 先返回 auth_error（red），实现当前工作目录 .env fallback 后通过（green）。完整回归中一次截止测试返回 provider_timeout；这与等待退避时的 deadline_exhausted 都是合法时间边界结果。测试检查有限耗时和请求数，避免假定宿主调度时间。

首次两版本完整回归各 137 项通过。wheel／sdist 构建成功；干净 Python 3.11 环境只安装基础 wheel，真实模型配置的 doctor 免费预检通过，容器 run 目标 13。公开 bundle、wheel／sdist 的真实凭据值扫描均通过。修复后 Python 3.11.13／3.12.3 各完整 139 项测试通过，真实 Docker 未跳过；15 模块 strict mypy、97 源文件、参考导出与 diff 检查通过。最终 wheel／sdist 与 SDK-only 安装通过，免费 doctor 和容器目标 13 再次验证。最终 Worker 为 sha256:525a898eddb370a18962fb6bd281193dd9e4dfcbe91fd7819b9998dd9af57c83。包依赖未新增，uv.lock 同步本包 0.4.0。trusted_local 不提供宿主求解进程硬墙钟隔离；容器路径提供进程隔离。完整方法取消／CLI resume 仍归 S04-B。

## 真实外部模型记录

两个案例通过相同公共 SDK、指定模型 deepseek-v4-pro-0813、用户配置的 HTTPS 网关以及 SDK 0.4.0 的真实 Worker 镜像。核心记录 provider、请求／响应身份、模型、时间、usage 和 hash；凭据由本项目 .env 在运行时读取，不进入日志／公开 bundle。原始模型响应没有 oracle 或参考代码输入。

| 案例 | 结果与独立核验 | 用量 | run_id |
|---|---|---|---|
| 生产 MILP | A=3、B=2、目标 13；满足两资源约束和整数域 | input=969、output=6200、total=7169；reasoning=5217 属于 output | 896afc53e2884c1f8e04e98538ad7cc1 |
| 无数据连续 LP | min 2x+y，x+y≥5，x≤2，y≤4；x=1、y=4、目标 6。原目标=2(x+y)-y≥10-4=6，解达到该界 | input=493、output=2142、total=2635；reasoning=1636 属于 output | 75141bcc146b4f0c9dddced2ac6aa233 |

首次生产调用把 max_output_tokens 设为 4096，供应方报告全部 4096 为 reasoning，finish_reason=length，text 为空，因此没有形成 Formulation（原记录为 invalid_json，现明确返回 llm_output_truncated）；该失败及真实用量仍保留。提高到 16384 后得到完整 JSON 和 stop，两次成功均经候选校验、确定性 Code 编译及容器 Solver API 完成。成本缺少定价依据，保持 null；这些微型实例证明实际流程，没有替代 benchmark 或完整语义评测。

## 独立审阅与修复

固定比较 ce9cdad…f9cfe21；两个独立只读 Codex CLI 进程分别审查 Standards 和 Issue #8 Spec，没有共享报告、编辑源码或读取凭据。真实测试由作者执行。

Standards：2 项契约问题，另有 1 项 possible Duplicated Code 判断。Worker admission 使用过期相对时限，现传递共享绝对 deadline 到 Docker 检查、创建和启动；慢 version／create 的外部 CLI fixture 先复现启动越界，再通过 deadline 拒绝且未 start。非法端口现通过 urlsplit.port 在 admission 校验，abc／70000 负例先 auth_error，再 invalid_config。重复连接错误映射集中为一个私有函数。

Spec：2 项实现问题，1 项交付证据缺口，无范围蔓延。Worker deadline 问题同上；结算现将未知 attempt 预留与已知 total 同时计入占用。503 后成功实测 9900 的负例先错误返回成功，再 token_budget_overrun，保存回复恢复仍拒绝越界且不重发。两版本回归、安装和审阅证据在本页与校验记录补齐。修复目前为作者 TDD 核验，不把它表述为审阅者复审通过。

草稿 [PR #9](https://github.com/Fangziyang0910/LLM4OM/pull/9) 基于 S04-A 分支，关联 [Issue #8](https://github.com/Fangziyang0910/LLM4OM/issues/8)。远程 CI 不使用真实密钥或付费请求；实际网关证据来自上述本地验收。

首轮 7fd1141 的 push／PR CI 在 Python 3.12 同样失败：150 ms 滴流测试窗口内 transport 尚未发出 HTTP，deadline 已使它退出，断言却要求服务器收到请求。预算执行没有越界。fixture 现给冷启动 1 秒，并将 drip body 延长到超过该窗口；继续验证真实请求、有限结束和未知预留，两版本 Provider 回归后重跑 CI。
