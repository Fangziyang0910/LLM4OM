# 自动优化建模研究综述与平台设计依据

调研日期：2026-10-08；文档修订：0.4.0。本文面向 LLM4OM 的需求与设计，依据一手论文、作者仓库和选择性源码考察。完整书目、链接和阅读范围见 [参考资料库](references/README.md)，检索过程见 [检索记录](references/search-log.md)。当前没有本平台实验结果。

## 1. 调研结论与项目目标

LLM4OM 的核心任务是将自然语言问题和数据交给指定建模方法，形成可检查的建模输出，再通过兼容后端调用求解器。科研实验在这一流程上组织不同 benchmark、方法、LLM 和求解配置。

领域文献中的方法实际处理不同环节：有的改进推理流程，有的训练专用模型，有的搜索数学表述，有的研究数据绑定，还有的提供评测或交互。它们需要分别接入共同接口，不能仅把项目名称列入同一个“方法列表”。

本项目采用三个设计判断：建模按 Formulation／Code 两阶段观察，默认五元素表述；方法与外部 LLM 分别配置；共同封装保留不同表示和独立评测证据。这些是对文献与实际实现的分析所得，不是任何单篇论文对本平台有效性的证明。

## 2. 研究问题与术语

### 2.1 建模任务包含哪些转换

Formulation 将自然语言需求与数据形成数学表述，Code 将表述与明确数据绑定落实为计算实现，形成具体优化模型；数值求解再产生决策解、目标与终止状态。每个转换可能失败，应保持可区分。

例如生产问题中，识别“数量为非负整数”是变量域建模，找到利润表中的正确产品行是数据绑定，生成 Pyomo 变量对象是计算实现，HiGHS 求出模型最优解是数值求解。这四类行为的正确性证据不同。

领域中的 abstract model 指参数化表述，concrete model 指参数绑定后的具体实例。它们与软件接口抽象无关。[领域综述的模型层次](https://arxiv.org/html/2508.10047v1)、[Pyomo 官方说明](https://pyomo.readthedocs.io/en/6.9.5/getting_started/pyomo_overview/abstract_concrete.html)

### 2.2 训练方法与推理方法

ORLM、SIRL、OptiMind 等工作可包含数据构造、训练所得模型与测试时策略。本版主要使用通用外部 LLM，暂不集成这些工作的任务专用训练权重；其推理流程／提示可明确作方法变体。未来接入专用模型仍用同一 LLM 配置，训练数据与 benchmark 分别管理。模型 checkpoint 名称不能替代整个方法配置。

### 2.3 五元素、Code 与领域表示

默认五元素按集合、参数、变量、目标和约束组织 Formulation。LLMOPT 的模板采用文本／LaTeX，之后另生成 Code；因此五元素的组织通用性与严格 IR 的可编译性分别判断。[LLMOPT 模板](https://arxiv.org/html/2410.13213v2)

数学表述可以是符号模型、结构化 IR 或文字公式；计算表示可以是 Pyomo 工厂或 gurobipy 脚本。Pyomo/PuLP 是建模接口，HiGHS/Gurobi 是数值求解器。平台按明确兼容路径连接它们。[Pyomo APPSI](https://pyomo.readthedocs.io/en/stable/reference/topical/appsi/appsi.html)

## 3. 代表性技术路线

| 路线 | 代表工作 | 实际变化的对象 | 在 LLM4OM 中的接入位置 |
|---|---|---|---|
| 直接生成与公开反馈修正 | 平台 direct／可选 feedback_repair；首批 OptiMUS [R05/R06](references/README.md#r06) | 提示流程、状态与修正策略 | ModelingMethod |
| 多专家协作 | 首批 CoE [R04](references/README.md#r04) | 角色、路由、协作和反思 | 方法内部实现，角色模型由配置指定 |
| 表述空间搜索 | Autoformulation [R09](references/README.md#r09) | 阶段产物扩展、价值估计与剪枝 | ModelingMethod，保留搜索轨迹与最终选择 |
| 专用模型与训练 | ORLM、LLMOPT、SIRL、OptiMind、Step-Opt [R07](references/README.md#r07) | 模型权重、训练数据和推理包装 | 本版只考虑流程／提示变体；专用权重留待后续 |
| 结构化输出与确定性编译 | IR2Solve [R20](references/README.md#r20) | 生成接口、表示检查和编译 | 方法输出＋IR/Compiler |
| 数据绑定 | BIND/Text2Opt-Bench [R18](references/README.md#r18) | 数值数据的暴露和读取方式 | 数据视图、绑定记录与方法配置 |
| 显式建模策略 | SAGE [R21](references/README.md#r21) | 表述策略、训练奖励与表述多样性 | 模型／方法配置及策略说明 |
| 交互与原始业务数据 | ORPilot [R17](references/README.md#r17) | 澄清、参数计算和端到端工作流 | 整体方法适配，平台提供共同资源 |

### 3.1 什么应留在方法内部

CoE 的专家选择、Autoformulation 的搜索节点、OptiMUS 的问题状态与检索步骤属于推理策略。核心只需知道阶段产物何时产生、消耗多少资源、执行得到什么公开反馈、最终选了哪次公开检查。方法内部角色可以叫 evaluator，但不因此拥有隐藏 benchmark 参考材料。

### 3.2 表示约束可能改变方法行为

IR2Solve 的 ModelIR 有集合、参数和受限表达式，并包含规则处理；本项目 GroundedLPIR 使用已展开变量和显式线性系数。二者都可确定性编译，但表达能力、约束粒度和规则语义不同。平台将表示检查、规范化、语义修正与编译分别记录，不能将改变约束含义的规则称为纯编译。[IR2Solve 表示与编译章节](https://arxiv.org/html/2608.02641v1)

结构化表示有利于检查和复现；原生代码有利于保留历史方法。因此 1.0 共存两条路径，不增加覆盖任意优化类型的表达式解释器。

### 3.3 结构错误与绑定错误需要不同诊断

BIND 的实验重点是数据规模增长时的数值与索引绑定问题。这使“只看模型结构复杂度”不足以描述输入难度。平台同时记录描述长度、数据大小、模型规模，以及错列／错索引与约束遗漏等不同错误；它们不被归并为一种统一失败机制。[Text2Opt-Bench](https://arxiv.org/abs/2605.21751)

## 4. Benchmark 调研与接入策略

| 数据／任务 | 原始问题特点 | 参考材料与版本问题 | 1.0 或后续行动 |
|---|---|---|---|
| NL4Opt [R03](references/README.md#r03) | LP 文字题、实体与结构标注 | 原竞赛结构任务与后续求解版不同 | 首批接入，保留源 ID 和派生标注 |
| IndustryOR [R07](references/README.md#r07) | 多领域问题，可含表格 | 存在原始、清洗与修正版；非线性实例不能改标为 MILP | 后续候选；导入时冻结 LP/MILP 范围 |
| MAMO [R10](references/README.md#r10) | EasyLP、ComplexLP 和 ODE 等子任务 | 子集语义与可用决策信息不同 | 首批 EasyLP／ComplexLP 的 LP/MILP 子集；ODE 排除 |
| ComplexOR [R04](references/README.md#r04) | 模型结构与数值参数分开 | 论文与公开实现的数据范围需核对 | 后续参数化任务与多 Agent 比较 |
| NLP4LP [R06](references/README.md#r06) | 结构／数据分离的 LP/MILP 与案例 | OptiMUS 论文版本和数据 release 持续变化 | 首批；锁 release、公开参数与隐藏参考、许可，不固定论文样本数 |
| OptiBench/ReSocratic [R11](references/README.md#r11) | 端到端任务与数据合成 | 包含不同问题类型；与另一个 OptiBench 同名 | 使用明确来源 ID，按类型导入 |
| OptiBench/Equivalence [R12](references/README.md#r12) | 参数化 LP/MILP 与模型级评测 | 匿名投稿记录、决定与数据入口仍需核验 | 不冒充已完整核验的可接入数据集 |
| OptMATH [R14](references/README.md#r14) | 双向合成及困难测试样本 | 训练与测试的构造、筛选来源不同 | 后续记录构造过程与 split |
| Text2Opt-Bench [R18](references/README.md#r18) | 可调整数据规模和任务类型 | 数据外置与内嵌形式影响评测条件 | 后续绑定与输入规模研究 |
| MIPLIB-NL [R19](references/README.md#r19) | 工业规模 MILP，描述、表述、代码和数据配对 | instance.json 包含参考目标，导入须剥离 | 后续规模实验，避免参考模型进入方法侧 |

原始发布的题目数量不等于本平台 eligible 数量。实例类型、oracle 证据、清洗版本和共同任务范围在运行前确定。基准维护的错误修复应形成新版本，不原地改变历史实验。

## 5. 评测文献与科研判断

### 5.1 目标值比较与解检查

模型求解目标与参考数值相近，是实例级数值证据。独立检查原决策的域、约束和目标，能进一步支持该解符合原问题。仅检查模型自己的约束无法发现业务遗漏。平台因此分别输出 objective_match、candidate_feasibility 和 independent_feasibility。

### 5.2 模型级比较

图编辑距离评测关注结构排列和表达差异；EquivaMap 关注决策变量映射下的表述等价。它们说明模型比较需要明确变量映射和等价定义，而非将字符串差异视为模型错误。对两个模型的等价判断也不能自动证明参考模型完整表达了自然语言需求。[图编辑距离评测](https://aclanthology.org/2024.lrec-main.1438/)、[EquivaMap](https://arxiv.org/abs/2502.14760)

1.0 保留评估器接口与证据范围，先实现目标比较和独立解检查，不将完整语义等价证明设为所有实例的前置条件。

### 5.3 最终选择与 Pass@k

论文常把 pass@k 写成“k 个采样输出中至少一个成功”。本平台只在同一问题实例的 k 次独立运行之间统计 Pass@k；同一运行内的修正与重新生成是建模步骤，不是独立样本。最终结果问“方法实际选出的建模输出是否成功”。隐藏答案选出的 oracle-best 仅用于独立诊断，不作为实际方法成绩。

### 5.4 正确性与求解效率

不同有效表述可能有不同规模和求解效率。后续研究可比较质量相当的不同表述，但必须固定数据、求解器、资源与终止条件，保存界和 gap。代码执行更快或约束更少，不自动意味着模型更好。

## 6. 平台与交互系统比较

| 系统 | 本次确认的对象 | 可迁移认识 | 需要保持的区分 |
|---|---|---|---|
| LLM4AD [R02](references/README.md#r02) | 多算法设计方法、任务与 LLM 接口，GUI | 方法内部逻辑封装，多任务共用评估入口 | 算法表现分数与建模／求解证据不同 |
| ORPilot [R17](references/README.md#r17) | 数据与交互工作流、多后端代码与 IR 能力 | 原始数据、派生参数、澄清和运行反馈 | 考察提交默认代码路径，IR 按需生成 |
| OptiMUS [R06](references/README.md#r06) | 特定建模方法与版本分支 | 状态、模块化反馈和原生复现 | 系统能运行多个模块，不自动等于多论文方法 registry |
| OptiChat [R26](references/README.md#r26) | 与已有优化模型交互 | 模型检查、解释和诊断 | 输入已有模型与从自然语言建模不同 |
| OptiGuide [R28](references/README.md#r28) | what-if 和多个研究子项目 | 求解结果分析、来源组织 | 同仓库项目不自动共享同一运行契约 |
| LLM4OR [R01](references/README.md#r01) | 文献、清洗资料与比较门户 | 资料与数据质量追踪 | 门户资料与可执行插件平台不同 |

对 LLM4AD、OptiMUS、ORPilot 和 CoE 的源码观察见 [固定提交记录](references/source-inspection.md)。本次未部署这些系统，接口与代码存在不等于其所有能力已通过真实运行验证。

## 7. 文献认识到设计的映射

| 认识 | 本项目选择 | 需求／设计位置 |
|---|---|---|
| 方法策略与模型能力分别变化 | ModelingMethod 与 LLMProvider 独立 | FR-03/13/15/18；DD-02/03 |
| 表示影响生成与复现条件 | ModelArtifact 共同封装，IR 与原生代码并行 | FR-20～23；DD-04/05 |
| 数据规模与绑定有独立影响 | 保存公开数据视图、来源与绑定诊断 | FR-09/12/20；DD-04 |
| 求解反馈不足以覆盖语义错误 | 公共反馈修正与独立评测分离 | FR-08/28/29；DD-02/06 |
| 数据版本和协议改变比较结果 | Benchmark manifest 与失败分母冻结 | FR-10/11/30～32；DD-06 |
| 用户运行与科研实验应共享行为 | 单问题应用流程，CLI/Web/benchmark 复用 | FR-35/36；DD-01/08 |

这些映射服务用户已确认的集成平台目标，不将任何参考工作的模块清单整体搬入核心。

## 8. 领域 DSL 对平台的启示

OptiDSL 使用问题族对应的预定义模板，并通过路由和实例化得到结构化输入；其领域 DSL 示例和格式约束见 [R29](references/README.md#r29)。同一领域格式经适配可以连接不同求解方法，实际覆盖范围由模板、约束特征和后端共同决定。主要建模比较统一使用 Gurobi，不能将全部提升归为更换求解器。

对 LLM4OM，DSL 是 Formulation 的可选表示，外层仍统一保存数学表述、Code、数据与来源。首批五元素不强制展开为某种 DSL；领域扩展时再声明模板 schema、必需特征与逐后端能力。PyVRP 官方文档说明 VRPLIB 并未完全标准化，未识别字段会被忽略，因此格式可读不能作为约束已实现的证据。[官方格式说明](https://pyvrp.org/dev/supported_vrplib_fields.html)

论文补充提示将缺失字段填 FALSE；平台用户问题保留未知／待澄清，不直接沿用这一数据生成条件。这里采用的是表示与执行分开的设计认识，尚未接入 OptiDSL 实现。

## 9. 邻接工作与调研边界

LLaMoCo 的主要输入为代码／LaTeX 的优化问题，输出求解程序；APF 面向高成本仿真设计；OptiChat/OptiGuide 强调模型与结果分析。它们值得保留为邻接参考，但不会仅因标题包含 optimization 而纳入首批自然语言 LP/MILP 建模方法。

本次调研覆盖代表性路线与近期数据／表示工作，没有证明本平台是首个此类系统，也没有重跑各论文成绩。部分条目只核验摘要与书目，阅读范围逐项列明。资料由 AI 辅助整理；平台设计是基于来源的分析，实际通用性仍由不同实现接入和真实验收确认。
