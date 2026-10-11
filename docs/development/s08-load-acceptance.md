# S08-C 本机负载与故障验收

用途：记录NFR-03／05／06、AC-18／22的本机压力证据。状态：1000离线批量性能验收通过；100CLI故障集合已通过；2026-10-11真实批量调度故障恢复验收通过（99格真实外部Provider，SIGINT协作取消＋resume零丢失）。工作项为[Issue61](https://github.com/Fangziyang0910/LLM4OM/issues/61)。规范由[需求](../requirements/v1.0.md)、[评测协议](../evaluation.md)与[S08](s08-benchmark.md)维护，完整1.0未完成。

## 真实批量调度故障恢复（2026-10-11，SDK／Worker0.37.0）

NL4Opt dev全99例（冻结manifest，仅dev split原样selected）×Direct five_element＋native_gurobipy×deepseek-v4-pro官方API×容器Gurobi，单run预算4 attempts／60k tokens／6 Solver，实验并发4。首次配置的单run token预算(30k)低于Provider单请求输出预留(32768)，42格在admission以budget_exhausted拒绝且零消耗——该次配置错误批次如实弃置，未产生模型调用。

修正后批次在42格启动、38格入账（25完成／13方法失败）时对benchmark进程注入SIGINT协作取消：4个在飞格记cancelled＋interrupted，预留账本(168 attempts／2.52M tokens)与全部已存结果完好。`--resume`后38格全部复用零重跑（N_reused=38）、4个取消格重跑、57个新格继续，最终99/99入账：76 completed＋23方法性失败（formulation pass 87／not_available 12），99次真实LLM attempt、87次Solver调用、tokens部分未知保持null，JSONL／CSV／Markdown／HTML四报告零错误，恢复会话耗时1,914秒。无任务丢失、无串结果、无重复计费；失败分母保留。证据位于`/tmp/llm4om-s08c`（运行数据不提交）。

## 冻结环境与负载

SDK／Worker0.28.0，代码hash72b2f0d37365b3f32a94fdcb4cb73eef8c8d174bea159f385afe9a3a460a6b03，镜像sha256:35403f20b47bb16326e0facb49c5e6a294debb521ecc9e06a856267ec6fe7d3a。本机Docker cgroup限制4vCPU／8GiB；离线任务固定到CPU0～3。这里vCPU是四个逻辑CPU，宿主拓扑为两个物理核。100故障集合在CPU4～7运行，使用另一组物理核，不与该参考组共享核。宿主仍运行既有服务；本实验不声称独占整台机器。

[acceptance_load.py](../../scripts/acceptance_load.py)通过真正的run_experiment运行1000个相同公开微型问题的独立repeat，并发4。Mock仅生成已冻结表述，离线模式不调用外部模型／Solver。直接CLI run＋evaluate以相同四路并发执行64次，事前排除前四次预热，剩余60次中位数作为参考。每个已调度任务耗时减该参考得到附加耗时，并报告其P95；排队等待和整体预检／报告另计入完整batch wall time，不混入该逐任务口径。这个口径与通过条件明确写入原始结果；不将1000次相同微型问题称为模型泛化实验。

## 故障集合

[acceptance_faults.py](../../scripts/acceptance_faults.py)从公共CLI并发运行100个任务：正常响应、非法JSON、HTTP429、超时、活动取消各20个。它验证应用与Provider／Solver／保存控制的规模故障隔离，使用本机合成HTTP和实际HiGHS，不使用付费模型。

实际原始终态为20completed／60failed／20cancelled，100个唯一run_id均保留。正常20个得到手算目标13，完成后继续没有新模型请求。未知HTTP结果的20个取消run保留预算预留，默认continue没有静默重调；显式rerun产生20个新run、继承未知资源、父bundle保持不变。共40个真实HiGHS成功结果，失败60个未调用Solver。结果在/tmp/llm4om-s08-load-evidence/faults/faults.json与逐run outcome.json。该100集合通过CLI并发入口，不能代称已通过100任务run_experiment调度中断／恢复；这部分继续由原S08规模要求验收。

本机执行脚本原bytes与hash保存于/tmp/llm4om-s08-load-evidence/execution-identity.json及executed脚本副本。运行中未改写脚本；结束后仅补充公开函数类型注解，原执行bytes与hash继续保留。没有Actions，没有新增真实模型请求。独立Standards／Spec审阅仍待完成。


## 最终性能结果

1000个任务均artifact_ready、1000个不同job_id／run_id，全量保存，无任务丢失。直接CLI参考60个测量的中位数为2.677985474s；调度附加耗时P95为0.209321421s，通过≤0.5s要求。整批run_experiment含预检／报告为706.472338s。CPU cgroup为400000／100000，memory.max为8589934592。完整逐任务时长、基线时长、公共报告hash在/tmp/llm4om-s08-load-evidence/reference/performance.json；记录的测量口径同上，不将整批排队时间解释为逐任务附加耗时。

性能用例没有启动Solver或外部模型，因此不生成虚构的求解／LLM启动耗时；这些阶段属于单独真实运行证据。100CLI故障集合与1000run_experiment负载各执行一次，未重复完整回归。100任务真实批量调度故障／恢复、独立审阅与其余发布要求仍待完成。两个CLI验收脚本可使用现有Worker镜像、只读脚本／fixtures挂载及独立可写output重现；脚本在入口校验资源与唯一输出，失败保留原始证据。
