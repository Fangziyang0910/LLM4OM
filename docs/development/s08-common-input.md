# S08-B 共同公开输入与基准比较

用途：记录SDK／Worker0.27.0的OptiMUS文本／普通JSON输入变体、事前共同样本选择与真实方法接入比较。状态：共同输入与case选择已实现，真实9组合运行已完成并保留全部结果；成功接入比较尚未全部完成。范围为S08-B、FR-10／31／32／34；指标依据[评测协议](../evaluation.md)，固定原方法依据[S06-B](s06b-optimus.md)。

## 明确的输入变体

原`llm4om.methods.optimus`继续要求公开params／labels JSON。固定上游main使用create_state直接读params.json，不调用parameters.get_params。`llm4om.methods.optimus_inline`保留同一main、提示、状态、反思、代码组装与调试流程；参数声明和labels为空，将原始公开数据bytes作为文本追加到描述，代码使用公开值的字面量。data.json因此没有预声明参数条目。

该变体有独立variant_id，不声称复现原预处理输入。没有生成或注入参考模型、答案、代码或隐藏labels。public-input-projection.json保存有效描述hash、数据hash与输入策略；完整source-main fidelity继续用相同公开资源tape对照。配置见[optimus-inline.yaml](../../examples/specs/optimus-inline.yaml)。

## 共同样本

ExperimentSpec.tasks每项可指定case_ids，必须是原冻结manifest中已selected的非空、唯一子集。任务资格、参考协议和源字节不改写；新增实验快照冻结具体共同case列表，报告N_selected为实验选中数，N_manifest_selected记录原任务总选中数。所有方法在同一冻结子集上运行，不能按结果改变共同集合。

本次接入验收选三个固定官方发布各第一个记录：NL4Opt dev首个原ID、MAMO EasyLP1、NLP4LP1。NLP4LP沿用已有公开数学审阅；MAMO在模型运行前依据整数域与原文舍入要求冻结review。未使用隐藏参考选择样本。三配置共用deepseek-v4-pro-0813、Gurobi、CPU／内存／并发和相同单run预算；Direct保留五元素＋native代码，OptiMUS保留native状态，CoE保留其未提供Formulation的事实。各自变体和阶段可用性不同，分别记录。

## 比较边界与证据

9个组合是一份接入验收，不能据此给出统计方法排名。原始NL4Opt缺少独立域／最优参考，目标匹配和独立可行指标为not_available／null；不能因为某候选optimal将其升格为准确率。MAMO／NLP4LP的数值匹配与语义正确性分别记录；失败和未知成本保留。

本机inline源main聚焦检查通过，九次源流程响应保留、data.json为空、fidelity match、公开数据hash可查；原params／labels接口保持不变。真实9组合只完成Direct/NL4Opt，运行5760e605d14649069ffe6bb7e6be7c67由真实容器Gurobi得到candidate optimal 888.8888888888889、8,513 Tokens；原NL4Opt没有数值参考，因此评分为null。其余8组合均provider_connection_error，结果与原资格分母保留；91,273 Tokens为未知响应预留，费用未知。恢复保留9个结果，不增加调用或Solver。浏览器视觉、独立审阅和完整性能验收仍需完成。

无凭据GET与无效凭据POST探针当前通过直连／本机代理均得到HTTP401，说明这些瞬时探针的TLS／HTTP可连接；无法据此判断8次有效模型请求失败的根因。没有把失败归因于方法，也没有重发完整付费实验。inline变体通过本机synthetic HTTP与实际Gurobi验收：9次固定main响应、目标12、data.json空参数，检查9.387s通过；原main9项检查1.405s通过，显式case选择2.597s、兼容预检2.735s通过。源码41模块、240文件仓库和JS语法通过。
