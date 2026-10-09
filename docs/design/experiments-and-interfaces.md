# 实验、恢复与入口详细设计

文档修订：0.4.0。开发设计，S01 已实现单问题应用入口与文件记录，其余能力待接入；返回 [详细设计索引](../detailed-design.md)。字段与错误语义由 [接口契约](../plugin-contracts.md)维护，指标由 [评测协议](../evaluation.md)维护。

## DD-06 Benchmark 与实验展开

BenchmarkSpec 由数据集选择、公开任务解释、参考材料适用性和评测协议组成；ExperimentSpec 再加入方法／LLM／后端变体、预算和重复次数。两者由配置与 manifest 表达，1.0 不额外增加一个必须执行的 Benchmark 插件层。

### 导入

首批适配 NL4Opt、NLP4LP 和 MAMO 的 LP/MILP 子集。NLP4LP 的公开描述／参数与私有参考代码／解分别导入；MAMO 保留 EasyLP／ComplexLP 子集身份，ODE 不进入本版评测。

TaskAdapter → 公开 ProblemSpec + 私有 oracle_ref → dataset manifest → 事前类型／证据过滤 → 冻结 EvaluationManifest。原数据不复制进核心包。名字相同的数据集用来源、版本与引用键区分。

### 展开与执行

冻结 manifest → 展开明确的配置组合 → 对每个组合预检 → 对共同样本产生 RunConfig → 调用 DD-01 → 按协议汇总。重复 run_id 不会增加独立问题数量；方法实例与可变状态不跨运行共享。

模型类型不兼容的样本在运行前按共同规则分类。方法生成失败、预算耗尽和检查器异常保留既定分母。没有 eligible 样本时指标为 null。

### 两种比较

默认比较 direct、OptiMUS、CoE 在同一通用外部 LLM、样本、可比执行条件与预算下的方法流程；角色模型覆盖必须显式记录。以后具备原推荐模型时可另比较完整系统，当前不将缺少训练权重的流程变体列为该原系统。不同比较条件分表，不能将后一种解释为纯方法效果。实际预算消耗、模型调用重试和求解次数都留存。

对应 FR-08～12/18/28～34；AC-04/05/15～17/22。
## DD-07 持久化、恢复与报告

运行事件按递增 sequence_no 排序。写入阶段产物后，再发布引用该产物的完成事件；使用临时文件与原子替换，避免报告读到半份 JSON。文件 hash 与事件引用校验失败应报错，不能忽略。

外部请求先写 call_id 与预算预留；响应先落盘，再结算并记完成事件。未知结果记录 `outcome_unknown`。恢复复用已持久化响应；重新调用策略明确展示可能重复及其预算处理。

S04-B 当前实现见 [取消与恢复](../development/s04-resume.md)。核心阶段 checkpoint 与方法内部 checkpoint 分开保存。方法支持 checkpoint 时，其 run 入口接受可序列化 checkpoint。恢复校验方法、契约、公开输入和配置。版本不兼容则拒绝；不支持内部 checkpoint 且尚无完整阶段时明确拒绝。将来若提供派生重跑，须显式请求并保留 lineage／已有费用与未知预留。

报告读取已保存结果，不重新选择候选或评分。公开导出包含运行配置、版本、Formulation／Code 引用与可用性、候选、求解和评测记录；排除凭据与私有 oracle。原始 LLM trace 的导出遵循独立访问策略。

缓存复用、产物回放和新方法运行分别记录。求解记录的复用 key 包含实际表示、数据、编译与求解配置，不能只依赖自然语言问题 ID。

对应 FR-17/26/30～34；AC-08/17～19/21/22。
## DD-08 CLI 与 Web 共用应用接口

### 应用用例

| 用例 | 输入 | 输出 |
|---|---|---|
| list_plugins / doctor | 环境与配置 | 能力列表、检查结果、兼容路径 |
| run_problem | ProblemSpec + RunConfig | run_id + RunBundle |
| run_experiment | ExperimentSpec | experiment_id + 进度与逐样本结果 |
| inspect_run / inspect_candidate | ID | 已保存的模型、代码、数据绑定与记录 |
| cancel_run / resume_run | ID 与明确恢复策略 | 新状态或派生运行引用 |
| render_report / export_bundle | ID 与格式 | 报告或公开产物包 |

表中名称是应用用例，最终 SDK 命名在 S01 实现时落实。CLI 命令规划保持 README 中的 run/benchmark/resume/report；inspect 可以先通过 run 结果路径提供，无需增加未验证命令。

### Web 页面与领域信息

| 页面 | 用户操作 | 核心内容 |
|---|---|---|
| 问题与运行 | 输入文本、导入数据、选择方法／LLM／求解器 | 原问题、兼容选择、资源预算 |
| 建模输出 | 查看候选与最终选择 | Formulation 五元素／IR、Code 实现、阶段修正、假设与数据来源 |
| 求解结果 | 查看解与诊断 | 决策值、目标、终止状态、界、gap |
| 实验比较 | 选择 benchmark 与配置变体 | 样本、进度、逐样本结果、成本和证据 |
| 环境与插件 | 检查依赖与接入能力 | 支持路径及具体不兼容原因 |

不同问题不强制具有同样的数学视图。页面区分候选自身可行、独立检查通过和仅目标匹配。进度来自同一事件记录；首次实现可轮询，不为传输方式增加另一套状态机。

CLI 与 Web 的同配置运行产生相同的配置 fingerprint 规则，run_id 仍不同。Web 会话仅保存选择与 run_id，后台任务状态由应用层管理。多用户权限、公共托管与协作编辑不在 1.0 范围。

对应 FR-06/20/24/26/34～36；AC-20/23。
