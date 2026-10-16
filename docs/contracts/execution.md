# 执行与恢复契约

生成代码只在隔离 Worker 中运行。可信收集器校验模型并独立求解。数值支持范围见[执行与求解](../development/solvers.md)。

## 参数化工厂

FactoryCodeProposal `0.1.0` 保存 `source/source_sha256/data_bindings/schema_version/representation_kind`。默认表示为 `python_factory`。源文本、哈希、当前数据绑定和方法能力在宿主校验；宿主不执行源码。

```python
from hashlib import sha256
from llm4om import FactoryCodeProposal, ModelProposal, MethodOutcome

code = FactoryCodeProposal(
    source=source,
    source_sha256=sha256(source.encode("utf-8")).hexdigest(),
    data_bindings=bindings,
)
proposal = ModelProposal(artifact, formulation, code=code)
return MethodOutcome("selected", "001", proposal)
```

Direct 的紧凑回复在工厂模式为 `{representation, python_factory}`，严格 IR 模式为 `{representation, structured_ir}`。原生工厂模式为 `{representation, native_gurobipy}`。

工厂定义 `build_model(data)`。data 是公开 ID 到原始 CSV/JSON 字节的映射，不含宿主路径、密钥或评测材料。工厂返回 Worker 内的 `ModelHandle(model, decision_map)`，每个活动标量变量必须有唯一稳定决策 ID。

Pyomo 构建接受闭区间连续/整数域、二元域、有限线性表达、范围约束和单目标。固定变量、开放域、未知活动组件及非线性拒绝。范围约束展开为两行，常数保留。

工厂子进程只导出受控实例和决策组件名。可信父进程校验问题、修订、数据、源哈希和结构，再构建新模型并调用求解器。子 stdout 只作为有界诊断。容器只读，父进程禁止被子进程读取内存或文件描述符。

保存的 Code 标为 `method_generated`，即使生成来源是手写 fixture。`factory-instance.json` 和 `decision-map.json` 标为 `factory_exported_instance`。它们是提取视图，不是源表述或语义证明。

工厂构建与求解共享 CPU、内存、PID、时间和输出限制。异常和非法导出保留源产物及诊断，不制造 SolveResult。

## gurobipy 工厂

原生 proposal 设 `representation_kind=native_code`，保存 `factory_contract=native_gurobipy/0.1.0` 和 `entry_point=build_model`。后端为 gurobipy，求解器为 Gurobi，执行为容器。

构建子进程导出 SDK MPS 字节和完整变量映射。含空白的变量名拒绝。可信收集器用新的环境和模型读取、验证与求解，不读取生成代码中的 `X/ObjVal`。

MPS 保留常数、方向、界、类型和线性行。仅支持单目标线性 LP/MILP；未支持结构在优化前拒绝。范围松弛变量需明确映射。

可选视图包括原生 MPS、实例和决策映射，来源为 `native_exported_instance`。Code 校验层次为 `factory_contract`，与确定性编译和语义正确性分开。

## 原生脚本

ScriptCodeProposal `0.1.0` 保存源文本、源哈希、当前绑定和显式派生的 `data_json` 字节。Code 使用 `native_script/0.1.0` 工厂契约及 `code.py` 入口，不冒充模型工厂。

脚本资源为 `execute(execution_id, code)`。执行反馈包含原始退出/状态/日志、输入引用、不可信捕获、可空可信求解引用和收集器错误。源执行与独立收集分别记录。

脚本先在受保护子进程运行，再由新可信 Worker 校验 MPS、映射和结构并独立求解。一次脚本尝试占一个求解槽；有效捕获的收集器再占一个。准入要求两个可用槽。

账本分别记录脚本执行、收集调用、捕获和 hook 观察。`source_optimize_calls=null`，因为任意 Python 可以绕过观察 hook。完整且身份一致的执行可复用，未知执行不自动重试。

## 求解器结果

求解器使用声明的 `result_profile` 校验依赖、选项、解键和证据。内部来源为 `trusted_highs_api/trusted_gurobi_api/trusted_ortools_api`，持久化容器来源为 `trusted_container_worker`。

Gurobi 原始整数状态转为字符串。状态 2/3/4/5/9/11 分别对应最优、不可行、不可行或无界、无界、时间限制和中断。`SolCount` 决定是否提供 primal、向量和目标。非有限或未提供的 bound/gap 为 `null`。

OR-Tools 绑定实际 `ortools` 包版本，读取 Pyomo 线性 Handle，经 MPSolver/SCIP 求解。支持有限非负 `time_limit_s`，零值不开始求解。具体数值范围由所选适配器校验。

运行探测记录实际可用性和微型求解。Gurobi 错误 10010 对应 `size_limited`；未观察到上限只记为 `micro_model_available_size_limit_not_observed`，不推断完整许可证。

## 取消

`run_problem` 接收 CancellationToken。`cancel_run(run)` 返回 `cancellation_requested/inactive`，写入绑定运行和拥有者的控制请求，不向持久化 PID 直接发信号。

HTTP、Docker 和平台拥有的本地求解进程均可取消。已安装方法声明 `cancellation=cooperative/0.1.0` 后，需要让出异步执行并检查取消。未声明的方法不能据此声称内部推理有界。

取消保留已完成阶段和实际诊断。清理使用有界的终止、查询和删除。Docker daemon 失联时保留身份和失败原因，不能证明容器已经删除。

## 持久化与检查点

核心检查点是 `0.1.0` envelope，包含 payload 和规范化 JSON 的 SHA-256。payload 绑定运行、公开输入/配置、不可变引用、事件、阶段、方法状态、admission 和资源账本位置。

文件先持久化，再原子替换。新目录逐层持久化。运行写锁保持单一写者，控制锁串行化拥有者更新。原内容保存在 `history/`，固定路径是当前公开视图。

不可变检查点另存 `checkpoints/<hash>.json`。视图发布前记录绑定检查点哈希、拥有者和目标引用的写入意图。恢复核对原始字节、拥有者和引用，只重建有效未提交视图。损坏的已提交内容返回 `checkpoint_incompatible`。

中断发布收据先纳入核心状态，再修复视图。身份检查失败仍保留收据和不可变历史。存储负责验证与发布，应用判断记录是否代表完成阶段。不序列化后端对象、pickle、凭据或 oracle。

## 恢复与派生重跑

`resume_run(run, strategy="continue")` 使用原运行、预算和 deadline。校验输入、配置、公开引用、插件/包、SDK 源码、Python/依赖、Worker 镜像和资源配置。失败发生在新请求或求解之前。

方法开始前保存 `method_started`。未完成且无内部检查点时返回 `checkpoint_unsupported`。完整表述/代码或匹配的真实执行可以直接复用，恢复不增加 LLM、检查或求解次数。

执行完成引用与 `execute_done` 先于 `solver_finished` 一起提交。已发布但核心尚未提交的完成记录，经收据、输入/输出引用和执行身份核对后复用。不能从任意公开文件或 stdout 拼造结果。

`completed/artifact_ready` 恢复幂等。其他过期运行返回 `deadline_exhausted`。已开始求解保留计数，取消不退还槽位。

显式 `strategy="rerun"` 创建新运行，保存 `derived_rerun` lineage、父检查点、公开历史和累计资源。新运行有新 deadline，但父已知消耗和未知预留继续计入上限。重新生成不把父回复冒充新输出。

## 私有资源日志

Gateway 先写不可变 `journal/<hash>.json`，再更新私有 `state.json`，最后提交核心资源位置。日志绑定 previous hash、原预算、deadline、请求与 Provider 身份。两个存储位置不宣称跨文件系统事务。

恢复要求完整单链，mutable head 不早于核心已提交位置。有效旧 genesis 也不能覆盖已结算资源。初次无请求 genesis 可按规则恢复，已提交 head 丢失则拒绝。

私有目录权限为 `0700`，文件为 `0600`。公开 trace 使用字段白名单，不包含原始回复或密钥。成功回复复用原 attempt；未知结果保留预留，返回 `provider_outcome_unknown`，不重发相同请求。

Gateway.recover 返回公开账本与 trace，不要求 API Key。凭据回显在原始和解码响应中检查，发现后先于归档失败。OS 持久化与故障注入验证不等于物理断电验收。
