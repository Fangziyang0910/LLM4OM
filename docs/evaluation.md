# 评测协议与正确性证据

协议草案：`llm4om.eval.objective-v0.1` 与 `llm4om.eval.checker-v0.1`。以下为设计要求，当前没有实验结果。

## 1. 必须分开的判断

| 层次 | 检查内容 | 能说明什么 | 不能说明什么 |
|---|---|---|---|
| 产物合法性 | IR 类型／引用／域或代码入口是否有效 | 可进入下一阶段 | 业务逻辑正确 |
| 执行成功 | 编译／构建／脚本能运行 | 代码路径可执行 | 模型可行或正确 |
| 候选模型状态 | solver 的原始与归一化终止状态 | 当前候选模型被求解到何种程度 | 候选表达了原问题 |
| 候选内可行性 | 解满足候选自己的约束与变量域 | 解对候选模型可行 | 没有遗漏业务约束 |
| 独立可行性 | 解满足独立 oracle 检查的原问题规则 | 检查器覆盖范围内符合原问题 | 未检查约束或所有实例均正确 |
| 目标值匹配 | 按协议与参考目标比较 | 本实例数值与参考匹配 | 模型等价或语义正确 |
| 语义证据 | 需求审阅、性质、等价检查等 | 在注明范围内支持语义判断 | 任意自然语言的自动完整证明 |

报告保留各层独立状态。LLM-as-judge 可以作为可插拔辅助检查器，但结果标签为 `llm_judged`，必须记录模型／提示和成本，不替代独立 solver 或形式证明。

## 2. 两种主协议

### 2.1 Objective 协议

适用于具有已核验、有限参考目标值的 LP／MILP 实例。主指标命名为 **objective_match_rate**。记录候选求解状态，不能因目标匹配就将 time_limit 改写为 optimal。

若 oracle 提供原问题目标计算器，优先由原决策映射独立计算目标；否则只能比较提取到的候选 reported objective，并将证据标为 `reported_objective_match`。参考材料只有数值时，对语义或原问题可行性保持 unknown／not_available。

### 2.2 Independent Checker 协议

适用于具有受信任原问题检查器的实例。主指标命名为 **verified_solution_rate**：检查器成功确认原问题可行性，且原问题目标满足预先规定的准确／质量阈值。

只有可行检查器而无参考最优值时，可报告 independent_feasibility_rate，不能称 optimal accuracy。没有完整决策映射时为 unknown，而不是猜测变量名并认为检查通过。

## 3. 样本与分母

1. 在运行任何方法前生成 EvaluationManifest，锁定 dataset/version/split、原始 ID、清洗规则、问题类型过滤、oracle 适用范围和样本哈希。
2. Manifest 中定义 `N_selected`（共同任务范围）与 `N_eligible`（某协议参考条件事先成立的样本）。公开报告两个数和事前排除原因；方法只得到公开问题。
3. 三种方法比较采用相同 eligible 样本，不根据运行后的错误删样本。不支持整个配置组合时该 cell 预检失败，不产生虚构的 0% 或成功率。
4. 纳入后产生建模失败、运行错误、超时无解、预算耗尽、未解决澄清或评估异常的样本保留在分母。它们不计为 pass，但保存具体状态，不将未知语义误标为语义错误。
5. `objective_match_rate = N_objective_pass / N_eligible`；`verified_solution_rate = N_checker_pass / N_eligible`；`assessment_coverage = N_assessed / N_eligible`。同时报告 evaluator error 与 unknown 数量，避免基础设施失败被解释为方法语义能力。
6. N_eligible=0 时率为 null／not_available，不写为 0 或 100%。预期 oracle 导入失败不得运行后悄悄缩小 eligible 集合；修复 oracle 后须更新 manifest 和实验版本。

批量表至少包含 selected、eligible、pass、fail、unknown、not_available、error、cancelled、unresolved 和事前 excluded 计数。应能用逐样本明细重建汇总结果。

## 4. 目标值、域与求解状态处理

有限数值比较采用：

```text
abs(predicted - reference) <= abs_tol + rel_tol * abs(reference)
```

默认建议 abs_tol=1e-6、rel_tol=1e-5；数据源精度、单位与舍入情况可以要求不同阈值，必须在预运行 manifest 固定。整数目标不依靠宽容差掩盖单位错误。NaN、Infinity、无数值或错误提取均不匹配。

对于 infeasible／unbounded 参考实例，使用单独的 **status_match** 协议与 denominator，不能放入有限目标值协议。无法区分 infeasible_or_unbounded 时维持不确定状态。1.0 首批基准导入以明确有限参考最优值样本为主要协议范围，保留其他样本及分类。

不同等价建模可能有辅助变量、目标缩放或取负号。允许预声明的 objective／decision 映射，但记录其来源，不从隐藏答案自动拟合转换。多解问题不要求与参考解逐变量相等；检查原问题域、可行性及目标。best_bound 和 solver gap 只证明候选模型的解质量，不证明原业务模型正确。

## 5. 语义与编译验证

**建模验证与编译验证单独计量。** 同一错误模型在两个求解器中得到相同数值，不能证明建模正确；同一正确 IR 在两个后端不一致，则需要调查编译、数值容差或求解终止条件。

1.0 提供：独立微型 fixture 检查器；需求条目到变量／目标／约束的溯源展示；可插拔独立解检查；限定性质与数据扰动测试接口；可选人工审阅标签。没有能力覆盖完整约束时写出覆盖范围。

必须包含“漏约束但代码可运行”和“目标值偶然相同但模型错误”的反例，验证报告不会将其标为 semantic_verified。需求覆盖率和 LLM 评论只能作辅助诊断。

## 6. 方法公平比较

实验必须固定或公开：样本、方法 variant、上游提交、LLM endpoint 类型／model ID、角色模型、提示／工具版本、温度／seed、最大调用／token／候选／求解次数／墙钟预算、求解器版本／参数、执行资源、数据视图与评估协议。

至少提供两种比较设置：

- **固定底座与资源**：各方法使用同一模型与预算，比较方法策略。
- **方法原生推荐设置**：保留各方法角色与模型配置，比较完整系统；不得描述成纯方法因果比较。

记录真实尝试与缓存命中。HTTP 重试属于 LLM attempts，语义修正属于 repair，二者不可混用。由 oracle 选取最佳候选的 pass@k 诊断与方法实际选择的 final outcome 分开呈现。

公开同等预算下成功率与 token／调用／时间开销；以“同 token”比较时声明 tokenizer／reasoning token 可用性。供应方统计不足时不要声称实现精确成本公平。

## 7. 汇总与重复实验

每个问题／方法／配置／重复产生独立 run_id。先报告每个 dataset 的 numerator／denominator 和微观汇总；宏观均值说明参与 dataset 及权重，不直接平均不可比百分数。延迟、token 与费用分别给所有运行和成功运行的分布，避免只看成功样本。

少量随机重复时报告原始结果与波动，不编造显著性。需要置信区间时使用以 problem 为采样单位的配对 bootstrap，固定种子及统计脚本版本；多次 run 不能被当作互相独立的新问题扩大样本量。

真实模型别名可能更新，平台记录请求 model ID、响应实际 ID、时间与 provider request ID；无法获得固定快照时在复现报告注明。离线 Mock 指标只验证工程流程，不与真实模型进入同一能力排名。

## 8. 数据污染与公开反馈

训练／调参／提示示例与测试 split 分开；近重复 detection 是诊断工具，不单独证明无污染。记录模型已知训练来源，但无法审计供应方训练语料时写 unknown。

不得把 EvaluationOracle 作为方法输入、few-shot 示例、错误修正提示、数据浏览工具内容或最终候选选择分数。公开校验器可以反馈格式／域／输入错误，但会泄露参考业务规则的检查必须被协议明确授权并与隐藏评测分离。

人工在看到隐藏答案后修改模型的 run 标为 assisted；不计入 unassisted 方法结果。基准清洗依据及理由应在方法运行前冻结；结果不好不是删样本理由。

## 9. 成本与报告字段

至少记录 attempts、completed calls、outcome_unknown calls、input／output／cached／reasoning tokens 的可用项、pricing_version、estimated_cost、cost_status、wall time、modeling time、compile time、queue time、solve time、evaluation time、max resource。

成本未知使用 null，status 为 unknown；Mock 费用可为 0 但注明 mock；用户未提供定价时保留 token 和调用数。wall time 包含失败与等待，不能把批量吞吐耗时当单问题响应耗时。

最少错误标签：description_ambiguous、data_missing、domain_error、constraint_omission、objective_error、code_error、compile_error、solver_limit、budget_limit、provider_error、checker_error、unknown_semantics。细粒度语义标签需有证据，不通过异常文本自动确定全部根因。

## 10. 必须交付的首份实验报告

发布前提交两个真实基准的冻结 manifest、三种方法的共同兼容设置、至少一个真实模型的逐样本记录、目标／独立验证证据覆盖率、资源统计、上游适配差异及失败分析。运行规模由可用预算明确指定，不因预算限制伪造完整基准成绩；小样本报告标作 smoke／pilot。全量基准完成不是实现发布的硬前提，但全部声明能力的真实验收不能缺失。
