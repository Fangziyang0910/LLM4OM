# S08-B 共同公开输入与基准比较

用途：记录SDK／Worker0.27.0的OptiMUS文本／普通JSON输入变体、事前共同样本选择与真实方法接入比较。状态：2026-10-11官方API全九格重跑完成——9/9经真实外部Provider接入、连接失败清零、4/4数值参考匹配；3格方法性失败如实记录。范围为S08-B、FR-10／31／32／34；指标依据[评测协议](../evaluation.md)，固定原方法依据[S06-B](s06b-optimus.md)。

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

顺序派生重跑已完成OptiMUS/NL4Opt实际接入：父run4dbf51e7d69b47198705c33635cc5e81保留失败，新runeda1ad611e5c4ccd812393803132ccfc使用相同公开case/config，固定main fidelity为match，实际Gurobi候选目标880。共20 attempts包含父未知attempt，已知37,054 Tokens＋原9,805预留，total/cost仍为null；2次源脚本尝试、3个Solver调用。其整数候选与Direct连续候选888.8888888888889的差异不解释为准确率，原NL4Opt域和独立最优参考仍未提供。首次9格结果不替换；其余7格在原父预算上限和原实验截止时间内顺序派生，现已全部结束；下表记录结果，不替换首次9格。


## 顺序派生结果

| Benchmark | 方法 | 结果 | 证据 |
|---|---|---|---|
| NL4Opt | OptiMUS inline | completed，候选目标880 | 固定main fidelity match；数值参考不可用 |
| NL4Opt | CoE | collector_failed | 生成prob_problem仅return模型，没有optimize；退出成功不当作求解证据 |
| MAMO | Direct | completed，目标10000 | run529f5e941db94a42994572f16f9d9b14；supplied_numeric_reference_match通过，独立语义未验证 |
| MAMO | OptiMUS inline | provider_connection_error | 已知35,825 Tokens，继承及新增未知预留分别保留 |
| MAMO | CoE | provider_connection_error | 已知10,110 Tokens，未产生候选 |
| NLP4LP | Direct | provider_connection_error | 失败保留在原参考资格分母 |
| NLP4LP | OptiMUS inline | provider_connection_error | 失败保留在原参考资格分母 |
| NLP4LP | CoE | provider_connection_error | 失败保留在原参考资格分母 |

这是显式rerun条件，父run、派生run与资源账本分别保存。派生账本包含父消耗，不能将两个账本相加解释为新增消耗；total_tokens与cost未知仍为null。顺序执行并未消除所有连接失败，因此并发不是已经证实的根因。没有自动补写CoE的optimize，也没有用隐藏评分选择另一个样本。

## 官方API全九格重跑（2026-10-11）

原父运行与冻结任务源在本机清理后，按相同固定提交重新获取源字节（NL4Opt dev.jsonl、MAMO三JSONL＋LICENSE、NLP4LP受限数据集2127文件经认证下载）并逐项sha256核验，重新导入三份冻结manifest（MAMO easy_lp:1与NLP4LP train:1按题面原文重新冻结公开数学review，各manifest仅选中对应首例）。SDK／Worker0.37.0、三配置共用deepseek-v4-pro官方直连、Gurobi、相同单run预算（30 attempts／300k tokens／1800s）与顺序并发1。实验预算按调度器累计预留语义取9倍单run预算；前两次尝试分别因预算预留不足与导入运行时身份变化被拒，未产生模型调用。

九格全部经真实外部Provider完成接入，无一次连接失败：

| Benchmark | 方法 | 结果 | 资源 |
|---|---|---|---|
| NL4Opt | Direct | completed | 1 attempt／9,590 Tokens／1 Solver |
| NL4Opt | OptiMUS inline | completed | 17 attempts／27,841 Tokens／2 Solver |
| NL4Opt | CoE | collector_failed | 7 attempts／15,143 Tokens，prob_problem仍仅return模型 |
| MAMO | Direct | completed，objective_match 1/1 | 1 attempt／6,135 Tokens |
| MAMO | OptiMUS inline | completed，objective_match 1/1 | 21 attempts／34,996 Tokens |
| MAMO | CoE | completed，objective_match 1/1 | 7 attempts／11,317 Tokens |
| NLP4LP | Direct | invalid_formulation | 1 attempt／7,458 Tokens／0 Solver，单次native_gurobipy联合输出未给出完整五元素，按0/1保留分母 |
| NLP4LP | OptiMUS inline | completed，objective_match 1/1 | 18 attempts／25,925 Tokens |
| NLP4LP | CoE | collector_failed | 7 attempts／15,620 Tokens |

四格数值参考（MAMO×3、NLP4LP×OptiMUS）全部匹配（4/4）；NL4Opt无独立参考保持null。CoE两格collector_failed与Direct一格invalid_formulation是记录在案的方法性结果，不是平台接入失败；MAMO×OptiMUS／CoE与NLP4LP×OptiMUS首次取得成功接入。总耗时1,178秒、约155k Tokens、费用未知。9组合仍是一份接入验收，不据此给出统计排名。实验与全部运行证据位于`/tmp/llm4om-s08b`（不提交运行数据）；重导入的manifest身份含0.37.0运行时。
