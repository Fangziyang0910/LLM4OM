# 插件扩展契约

插件以声明接口协作。内置与已安装实现使用同一注册机制；已安装 Python 包属于可信平台代码，生成代码另行隔离。

## Manifest 与发现

工厂实现 `describe()` 和 `create(config)`。普通插件通过 `llm4om.plugins` entry point 导出工厂实例。

| Manifest 字段 | 内容 |
|---|---|
| `schema_version/plugin_version/contract_range` | 结构、插件版本和支持契约区间 |
| `plugin_id/kind` | 唯一 ID 与插件种类 |
| `display_name/description` | 名称和用途 |
| `capabilities` | 接受/产出类型、问题类型和资源能力 |
| `config_schema` | 自包含 JSON Schema |
| `dependencies` | 包、执行环境和许可证条件 |
| `source` | 上游、固定版本、变体与适配差异；无上游时为 null |

注册键为 `(kind, plugin_id)`。重复活动键报错，不按安装顺序覆盖。非法 Manifest 阻止发现，不静默隐藏。配置 schema 允许本地片段引用，不接受远程引用或任意对象构造。

能力声明使用明确枚举和带版本 profile。未知能力不视为支持。Planner 校验产物、问题类型、模型接口、LLM 特性和执行要求，再做依赖检查。`preflight_ok` 表示准备条件成立，不保证服务和生成行为成功。

研究方法来源另记论文、固定提交、variant、原模型与配置模型的差异。论文成绩、代码版本和数据版本分别关联。

## 插件种类

| kind | 接口或职责 |
|---|---|
| `method` | 异步 run，组织建模策略 |
| `llm_provider` | 文本 Provider，Gateway 管理资源 |
| `task_adapter/evaluator` | 导入/读取冻结案例，以及独立评测 |
| `data_loader` | 公开字节到有限 DataView |
| `compiler` | 严格 IR 到 CompiledCode |
| `model_backend/solver_backend` | Worker 内构建、导出与数值求解 |
| `executor` | 声明的容器或拥有进程调用 |
| `artifact_store` | 运行存储打开器 |
| `reporter` | 已形成公开结果的呈现 |

Registry、Planner、预算和状态机保留在核心。具体输入输出分别见[方法](methods.md)、[LLM](llm.md)、[任务](tasks.md)和[执行](execution.md)契约。

## 身份与恢复

admission 冻结 Manifest、配置、依赖和安装来源。安装来源包括 entry point、分发包/版本及包文件哈希。`package_sha256` 排除字节码，便携的 `content_sha256` 还排除安装元数据。

宿主和 Worker 比较执行内容、声明与配置。Worker 的数值依赖和镜像 ID 另行固定。恢复要求原身份一致，源码或包变化不静默迁移旧运行。

插件异常通过安全类型和栈帧报告，不公开异常正文或插件 stdout 中的私有内容。该规则是可信代码的错误卫生，不构成恶意插件沙箱。

## Compiler

接口为 `compile(ir, target_backend) -> CompiledCode`。当前 profile 为 `grounded_lpir_pyomo/0.1.0`，接受 `grounded_lpir/0.1.0`，输出 Pyomo 工厂，声明 `deterministic=true`。

输入是公开 IR 副本。输出源码非空，最多 8 MiB；平台检查语法、变量/约束 ID、索引排列和常数锚点。Code 保存实际编译器、源 IR、symbol map 和编译身份，Build 保存目标后端与配置哈希。

Worker 请求包含 IR、源码哈希、symbol map、编译器选择/身份和执行目标。Worker 重新编译并核对源码与映射后求解。低层内置请求仍可使用其原接口；平台请求总是传入已准入选择。

镜像构建支持重复 `--plugin-wheel`。只接受显式可信 wheel，拒绝替换 SDK 和文件名冲突。运行时不安装插件或挂载宿主源码；额外依赖需要已存在于锁定运行环境。

## ModelBackend 与 SolverBackend

后端声明 `handle_profile`，求解器声明 `handle_profiles/result_profile/options_schema`。当前 Handle 包括 `pyomo_linear/0.1.0` 和 `gurobipy_linear/0.1.0`；求解结果 profile 包括 HiGHS、Gurobi 和 OR-Tools API。

后端实现 `load/export`，原生后端另提供受控 `read_transport`。求解器实现 `runtime/solve`。输入 profile、依赖、选项及实际 LP/MILP 类型在生成或执行边界核对。

完整决策映射、有限 JSON、实际包版本、请求选项和声明结果来源必须匹配。常数模型内部零变量显式记录，不变成业务决策。应用绑定实际插件 ID，不根据第三方名称猜测证据。

## DataLoader 与 DataView

加载器使用 `public_bytes/0.1.0`，声明 csv/json 格式和 full/rows/summary 视图。缺省为 `llm4om.data_loaders.public`。核心控制路径、8 MiB 原始读取、哈希及原数据 schema。

Loader 接收公开原始字节、复制的 schema 和数据 ID/格式/哈希/大小，不获得路径、Gateway、密钥或评测资料。

RunConfig.data_view 设置 preview/full/summary、行列/字节限制及可选列白名单。默认最多 100 行、32 列、65536 字节。full 要求完整且未超限；CSV 预览保留原值和行重数。JSON 支持原始完整对象或有限顶层结构摘要，不做未声明数值聚合。

核心核对视图内容、计数、原始成员和暴露范围。完整视图保留原字节。原始哈希和视图哈希分别保存。未声明 views 访问能力的方法要求完整视图，不能猜测未提供的值。

原始数据与求解绑定保持不变。bundle 保存视图记录和内容快照，trace 引用实际视图。Worker 接收原始公开数据，不加载宿主 Loader 或隐藏材料。

## Executor

Manifest 声明唯一执行模式和 executor_profile。`create(config)` 返回进程 callable。当前 `container_process/0.1.0` 复用 run_container 并返回 ContainerExecution；`owned_process/0.1.0` 复用 run_owned_process 并返回 stdout/stderr/exit_code。

预检、模型执行、原生脚本和收集器均使用已选执行器。取消、deadline、资源和隔离要求沿用声明的进程接口。方法不获得低层宿主执行接口。

## ArtifactStore

存储声明 `store_profile=run_store/0.1.0`。`create(config)` 返回 `opener(root, *, resume=None, cancellation=None, versioned=True)`。

打开器返回 RunStore 成员契约，包括运行身份、路径、引用、事件、状态、公开投影、取消、write/json/emit/checkpoint/close/accept_publications。

运行、恢复、报告和派生操作按保存的 store binding 打开。早期无 binding 的记录使用内置 filesystem。公开 root 投影为 `.`，不泄漏宿主位置。

选择解析失败时，核心用 filesystem 保存具体 admission 失败。已解析打开器失败按原异常传播；存储 OSError 保持 CLI `store_unavailable` 语义。

## Reporter

Reporter 声明 `public_results/0.1.0`、run/experiment scope 和文件名。配置最多 32 项，声明文件名总数最多 128，不能冲突。`summary.json` 保留给核心。

`render` 接收公开结果深复制、ReportDestination 和 scope。destination.put 只接受唯一声明文件，文件名不含目录、URL 或点前缀；输出合计最多 64 MiB。核心核对实际字节、引用和文件集合后发布。

Reporter 只改变呈现，不改变评测、选择、分母和预算。异常记录为 report_errors，其他报告继续，建模结果不改成失败。report_run/report_experiment 使用固定身份重建已保存公开结果，不调用 LLM 或求解器。

## 接入验证

新插件提供 Manifest、配置说明、支持组合，以及成功和失败用例。实际数值后端还需真实求解；研究方法记录固定来源与差异。工程插件示例位于 [examples/plugins](../../examples/README.md#插件示例)。
