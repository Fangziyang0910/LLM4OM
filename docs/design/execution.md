# 插件、建模输出与求解详细设计

文档修订：0.4.0。开发设计，S01 已实现公开产物校验与存储，S02-A 已实现严格 LPIR 编译与 trusted_local HiGHS，S03 已实现方法发现／当前路径预检；返回 [详细设计索引](../detailed-design.md)。字段与错误语义由 [接口契约](../plugin-contracts.md)维护，指标由 [评测协议](../evaluation.md)维护。

## DD-03 插件接入与兼容路径

### 接入顺序

1. 安装可信 Python 插件包；发现其 `llm4om.plugins` entry point。
2. 读取 Manifest，检查 ID、版本和配置 schema。
3. 校验方法输入／输出、LLM 功能、表示、后端、求解器及执行环境。
4. 检查本机依赖，默认不调用付费服务。
5. 创建固定 ExecutionPlan，随后才能进入生成与执行阶段。

预检结果输出可用路径或字段级错误。未声明能力按未知处理；不会自动降级到另一方法或输出模式。

### 路径选择示例

| 产物与配置 | 计划结果 |
|---|---|
| grounded LPIR → lp_ir_to_pyomo → pyomo_factory → HiGHS | 首批必须实现的结构化路径 |
| 相同 IR → Pyomo → Gurobi | S06-A 已验证当前微型 LP/MILP |
| Pyomo 工厂 → HiGHS 或 Gurobi | 由工厂声明与实际模型类型决定 |
| native gurobipy → Gurobi | S06-A SDK MPS／可信 API 提取，限当前线性子集 |
| native gurobipy → HiGHS | `CAPABILITY_MISMATCH` |
| 原生脚本无法提取解向量 | 可执行，但独立解检查证据不足 |

第三方方法声明 Manifest、实现共同入口并通过兼容预检后，由同一应用流程提供 CLI/Web 与实验调用。方法论文引用和适配版本记录于 Manifest.source；源码考察提交与正式接入锁定分开维护，见 [源码考察](../references/source-inspection.md)。

对应 FR-01～06/14/22/23；AC-01/02/12/21。
## DD-04 建模输出与数据绑定

ModelArtifact 是共同封装，formulation_ref 与 code_ref 分别指向数学表述和求解实现；stage_status 记录可用、待生成或不可用。字段的唯一来源是 [接口契约](../plugin-contracts.md#34-candidate--modelartifact--阶段输出)。数学模型、求解代码、参数来源、假设与需求映射是不同信息，应分别标识其来源与可用性。

### 表述与实现的对应路径

| 层次／表示 | 1.0 行为 | 数据变化时 |
|---|---|---|
| 五元素 Formulation | 集合、参数、变量、目标、约束及数据来源；文本由方法进入 Code | 重新绑定参数与表述 revision |
| 具体实例 GroundedLPIR | 系数和有限变量／约束已绑定当前数据 | 生成新绑定与 revision |
| 参数化 Python 工厂 | `build_model(data)` 构建具体后端模型 | 新数据实例化并重新校验 |
| 原生脚本 | 按上游入口执行并提取结果 | 遵守脚本实际数据接口，不推定可复用 |

字段齐全并不证明语义正确。代码提取出的数学视图必须标为推断或经检查的派生视图；不能覆盖原始产物。

### 数据绑定证据

数据文件必须有 hash。可提取的参数绑定额外保存来源列、键／索引、单位、变换代码或声明。例如利润系数来自 `products.profit`，资源系数来自资源列，容量来自 `capacities` 的 resource_id 键。派生参数文件记录父文件和变换 hash。

这些信息使用现有 `data_bindings` 与产物引用表达，不引入一个新的数据处理框架。方法不能提供详细绑定时标明缺失。禁止从当前最优解倒推出一份“正确绑定”。

### 检查步骤

阶段引用／来源检查 → 五元素完整性或表示范围检查 → 路径／大小与类型检查 → 文件 hash → 表格键与缺失值检查 → 表示合法性 → 数据引用可解析性 → 编译。将错列、错键、单位不一致等绑定错误与约束遗漏、变量域错误分开诊断；需要独立证据的标签由检查器或人工赋予。

对应 FR-07～12/20～22/26；AC-03/04/10/24。
## DD-05 编译、执行与求解结果

### 结构化路径

只有经过明确校验的严格 IR 才进入确定性 Code 编译；五元素自由文本不直接执行。校验 LPIR 的 ID、有限系数、域、边界与引用 → 按固定版本编译 → 创建 symbol_map → 在 Worker 构建后端模型 → 求解 → 将解向量映射回 IR 与原决策。

目标常数、目标方向与约束常数必须保持。合法重复项可归一化，原始表示保留；非法引用、非有限值或未支持结构在执行前拒绝。语义修正形成新候选，确定性编译不自行修改业务约束。

### 工厂与原生代码路径

工厂返回 Worker 内的后端模型，平台掌握求解调用。Legacy 脚本可包含求解过程；适配器必须声明入口、依赖、求解组合及提取方式。stdout 中的自报数字与从后端 API 提取的结果具有不同证据来源。

生成实现形成 CodeArtifact，关联源 Formulation；Solver 只执行实际实现，不从五元素文本自动猜测约束。默认容器只挂载公开数据和候选目录。LLM 调用在宿主 Gateway 完成，密钥与隐藏参考材料不传给 Worker。容器失败不能自动降级到本地执行。

### 结果归一化

| 情况 | 保存方式 |
|---|---|
| optimal | 终止状态、解、目标、界和求解器容差 |
| time_limit 且有 incumbent | time_limit + has_primal_solution=true + 解与界 |
| time_limit 且无解 | time_limit + false；解与目标为 null |
| infeasible / unbounded | 各自保留，不合并成“求解失败” |
| 无法区分两者 | infeasible_or_unbounded |
| Worker 超时／OOM | ExecutionResult 记录异常；不得编造 solver 状态 |

具体原始状态依据锁定版本的适配器表映射。[Gurobi 官方状态说明](https://docs.gurobi.com/projects/optimizer/en/current/reference/numericcodes/statuscodes.html)仅说明求解器语义，不替代实际适配验收。

对应 FR-21～27；AC-10～14。

### S02-B 已实现的参数化工厂路径

Direct 的输出模式与独立方法的 profile 通过方法声明解析，不由核心猜测配置。
当前公开契约见 [S02-B 接口](../plugin-contracts.md#10-s02-b-parameterized-factory-interface-sdk-050)。
工厂在容器子进程用当前公开 CSV bytes 构建 Worker-local ModelHandle；父进程校验导出的具体
线性实例后，经既有严格 IR／HiGHS 路径独立求解。构建与收集隔离见 [ADR-0005](../adr/0005-factory-collector-isolation.md)。
原 Code 的来源是 method_generated；导出实例只形成 factory_exported_instance 派生视图，
不覆盖源 Formulation。数据 revision 与 hash 随实例变化，源模板可保持相同 hash。
本地与真实外部模型、重绑定、独立审阅后修复验收见 [实现记录](../development/s02b-factory.md)。


### S06-A 已实现的 Gurobi／native 路径

[实际支持与证据](../development/s06-gurobi.md)明确限定 size-limited 微型 LP/MILP。
Pyomo 参数化工厂复用已有隔离导出和重建；native gurobipy 通过 SDK MPS 在可信收集器读取新模型，
实际 API 检查结构、每个变量的映射和独立求解。二者保留原 Code／Formulation。
原生提取视图标为 native_exported_instance；不能据此宣称源代码／原问题的语义等价。
原生→HiGHS 及 generated Code→宿主／离线在生成前拒绝。实际未支持结构在优化前拒绝。
Runtime doctor 与 run 共用选中 SDK／Worker 和许可证微型可用性检查，不输出许可证身份或日志。
