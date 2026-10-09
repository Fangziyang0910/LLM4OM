# S02-B 参数化工厂实现与验收

状态：S02-B 当前 HiGHS／容器范围已实现并通过本地验收；SDK／Worker 0.5.0 未发布，关联 [Issue #12](https://github.com/Fangziyang0910/LLM4OM/issues/12)。真实模型、独立审阅与最终结果见本页。
规范来源是 [插件契约](../plugin-contracts.md#10-s02-b-parameterized-factory-interface-sdk-050)、
[执行设计](../design/execution.md)、[ADR-0004](../adr/0004-formulation-and-code.md)与
[ADR-0005](../adr/0005-factory-collector-isolation.md)。覆盖 FR-21～25/29、DD-04/05、AC-03/10/13/24 的当前 HiGHS 路径。

## 实际交付

Direct `output_mode=python_factory` 接受 `{representation, python_factory}` 回复。
独立安装的方法用 `FactoryCodeProposal/0.1.0` 返回源代码／hash／当前 bindings，
并关联原五元素 Formulation；不需要 core method-ID 特例或任意 plugin config 推断。
配置能力经 `resolve_capabilities(config)` 显式声明；旧静态 grounded profile 不变。
参数化路径只准容器，离线或 trusted_local 在生成前拒绝。此路径不需要 compiler 配置。

`build_model(data)` 真正读取 ID→CSV bytes，构建具体 Pyomo 模型，并返回 Worker-local
`ModelHandle(model, decision_map)`。工厂构建／导出位于子进程，可信 Worker 不执行提供的 Python。
父进程禁用 dumpability，阻止同 UID 子进程读取父内存／文件描述符；镜像与输入只读，网络关闭。
父进程校验导出的线性实例，再用既有严格 IR 编译器／HiGHS 独立求解。
工厂打印与子进程模块修改不能构成 SolveResult；源 Code 一直标为 method_generated。
原 Formulation 保留，具体实例和 component-name 决策映射保存为 factory_exported_instance 派生视图。

支持闭区间连续／整数／binary 域、有限线性系数、目标和约束常数、范围约束。
拒绝非线性、开放／非区间域、固定变量、未知 active Pyomo component、错误 handle、缺失或重复决策映射。
所有当前 public data ID 必须有匹配 raw-byte hash；问题 revision 和源 hash 独立记录。
失败保留原源文件、Formulation、Code proposal 和实际执行诊断，且不制造 SolveResult。
公开 Code validation 为 factory_contract；NL4Opt 后置评测也按真实 Code 来源报告。

## 可复查的本地验证

环境：Linux，Docker 29.6.2，Worker Python 3.12，Pyomo 6.10.1，highspy 1.15.1。
以下命令不调用付费 LLM；HTTP 响应是明确的手工 fixture。

```bash
uv sync --locked --extra dev --extra solve
uv run --locked python scripts/build_worker_image.py --offline
uv run --locked --extra dev --extra solve python -m unittest discover -s tests -p test_factory_run.py -v
uv run --locked --extra dev --extra solve mypy
uv run --locked --extra dev --extra solve python scripts/render_references.py --check
uv run --locked --extra dev --extra solve python scripts/check_repository.py
uv run --locked --extra dev --extra solve python -m unittest discover -s tests -v
uv build --offline
```

小步 red → green 在已批准的 CLI/SDK 与 Backend/Solver seams 进行。
首次 factory local/offline 预检测试在旧模式返回 invalid_config 时失败；声明接口后通过。
真实 Direct HTTP→factory→Docker→HiGHS 测试在旧 Direct 不接受 factory 时失败，完整实现后通过。
后置 Evaluator 错标 deterministic_compilation 的测试失败，来源判断修正后通过。
PositiveReals 测试揭示开放域会被静默变成闭界，增加端点 membership 校验后通过。
测试没有内部 collaborator mock 或私有函数调用。

| 输入与检查 | 实际结果 |
|---|---|
| public products：A 利润 3、B 利润 2，原资源容量 8/8 | 整数 A=3、B=2，真实 HiGHS optimal，目标 13 |
| revision=2，A 利润 2、B 利润 3，其余结构不变 | 整数 A=2、B=3，真实 HiGHS optimal，目标 13；源模板/hash 相同，data binding 改变 |
| 目标加 7，约束两侧加 5 | 目标 20；提取视图保留目标常数 7、约束 body 常数 5 |
| factory 打印 objective=999999，并 monkeypatch 子进程 Solver 模块 | 可信父进程仍独立求得目标 13；打印保留为 stderr 诊断 |
| factory 尝试改写 installed Solver 文件 | 只读容器产生 factory_exception／OSError；无 SolveResult，原 Code／Formulation 保留 |
| 非线性、非区间／开放域、错误 handle／map、异常 | 拒绝；实际错误码、源文件与执行记录保留 |
| 陈旧 data binding、错误源 hash、未知 Code proposal version | 独立安装方法经 SDK 返回时拒绝；supplied source／Formulation 保留；未发送 LLM 请求 |
| 无限循环／大输出 | execution_timeout／execution_output_limit；无 SolveResult，Code 保留 |
| 独立安装方法（普通 entry point、自己的 config） | 版本化 factory proposal 经同一 SDK 路径求解目标 13，无核心特例 |
| synthetic NL4Opt case 的 factory 后置评测 | Code level=factory_contract；semantic not_available；私有 annotation 不进 prompt／公开 bundle |
| 旧独立安装 grounded fixture | 聚焦 20 个测试通过，目标常数变体仍为 20 |

完整最终检查结果在本文件末尾记录。

## 限制与父任务验收

未调用付费 LLM，未读取实际 .env、密钥、私有运行 archive、其他代理日志或商业许可证。
真实外部模型 factory case 和独立 Standards／Spec 审阅由父任务执行。
本次只做本地 Standards／Spec 自查；不启动其他代理、不提交／推送、不改 GitHub／CI／可见性。

工厂导出的实例是候选证据；任意工厂可构建或导出错误业务模型，因此不证明原 Formulation、Python
与业务需求等价。Solver 结果只来自对已验证导出实例的独立 HiGHS 调用。LPIR 的数值范围限制沿用
S02-A；Gurobi／native gurobipy、非线性、恢复和一般 benchmark 数学检查不在本切片。

任意 factory 与 collector 的隔离验收限 Linux Docker。子进程共享容器 CPU／内存／PID／总输出限制与
墙钟 deadline；工厂可造成容器失败，但不能用 stdout 生成有效 SolveResult。资源 CPU 计入父与已回收
子进程，peak_memory_bytes 是实测的最大单进程 RSS 高水位，非容器聚合峰值。子输出最多 8 MiB，
受更小的配置 output_limit_bytes 限制。缺少环境在方法运行前拒绝，尚未生成的 Code 不会被虚构。

## 最终本地结果（2026-10-09）

- Python 3.12.11：完整 154 tests，178.575 s，全部通过。
- Python 3.11.13：独立 venv 安装构建的 0.5.0 wheel，完整 154 tests，180.458 s，全部通过。
- factory 聚焦 11 tests：55.894 s，全部通过；真实 HTTP fixture／Docker／HiGHS，没有付费请求。
- 两个 Python 环境的 mypy 均通过（19 source files）。仓库校验通过（108 files），参考资料 check 与 git diff --check 通过。
- SDK wheel／sdist 离线构建通过；3.11 的锁定依赖与 wheel 安装通过。首次 3.11 离线安装因该平台 Pyomo wheel 未缓存失败，随后按锁定 hash 下载依赖并安装成功。
- 真实 Worker：Python 3.12.15、SDK 0.5.0、Pyomo 6.10.1、highspy 1.15.1。
  image ID 为 `sha256:3c36fdcc4f55e4a787c4fc3b7b01c1241dc46326df9a21ab5aa4673a65173e8f`。
- 原 production factory source hash 为 `6d518a30e6be25eb838dd324d8a089181c8bd7ec59a16b7ca7e8136d466a6544`，两个数据 revision 保持相同源 bytes/hash。
- 新测试还验证连续 LP 的 A=B=8/3、目标 40/3；以及直接写 `/proc/<collector>/fd/1` 被 PermissionError 拒绝，不能伪造 Solver 输出。
- 本地 Standards 自查：公开 seams、契约／调用方／fixture／版本同步、来源标记、新文件 audit rows 和信任边界已检查。
  本地 Spec 自查：参数化构建、换数据、真实独立求解、插件接入、失败保留和旧路径回归已覆盖。
  外部模型 factory case 与独立 Standards／Spec review 仍由父任务执行。

完整日志位于任务指定的仓库外目录 `/tmp/llm4om-s02b/`（factory-tests.log、suite312.log、suite311.log、mypy311.log、package-build.log、install311.log、doctor.json）。日志为本任务的本地检查结果，不提交仓库。基线保持 fb7e276；未提交、推送、切换分支或修改 GitHub／CI／可见性。


## 父任务真实外部模型验收

2026-10-09，同一公共 CLI 使用用户指定 deepseek-v4-pro-0813，生成参数化 Formulation／Python
工厂并在容器真实求解。run_id=68a2c5f6774340c39176d776ce16f12f；整数 x[A]=3、x[B]=2、目标13，
termination=optimal。Code origin=method_generated，输入930、输出8294、total9224；reasoning7109
包含在 output 中，成本未知。未使用隐藏 oracle／参考代码，也未自动降级。

复用该实际生成的原始代码，以新 CSV 利润 A=2/B=3 和新 revision 经公共 Executor／可信 Worker
运行，得到整数 x[A]=2、x[B]=3、目标13。源 SHA-256 始终为
5dae2c057516f5b954ac5b929058a6dbf2c10eb93fa59b6b2dc58c9ec5003165，数据 hash 与绑定变化。
这次重绑定不再调用 LLM；与首次外部模型生成分别记录。证据在版本控制外的
/tmp/llm4om-s02b/live 和 /tmp/llm4om-s02b/rebind-result.json。

独立 Standards／Spec 审阅固定 fb7e276…a7a5774：Standards 无具体问题；Spec 有一项 P2，普通
异常丢失资源具体原因。公共 CLI 负例 ValueError("missing capacity for resource R7") 先失败，补充
有界 stderr traceback 后通过，仍无 SolveResult。子进程入口也改为调用模块入口函数，消除重复
执行已导入模块的 runpy 警告。修复为作者 red→green 核验，未冒称独立复审通过。


## 最终父任务检查

修复后 Python 3.12.3／3.11.13 各完整 155 项测试通过（176.617s／176.065s）。19 模块 strict mypy、
109 源文件、参考导出、diff 检查通过。wheel／sdist 和 Worker 构建通过；不安装 Pyomo／highspy 的
干净基础 SDK 环境，免费 doctor 通过，并经公共 Executor 真正完成上述真实代码的新数据求解。
运行公开文件、wheel／sdist 不含实际凭据值。最终 Worker 为
sha256:2e7c6b2bf1fa02d2afd753ee227bf5e190cb4ee2151e6ef57f1f105a70e8b011。

当前切片完成不代表 1.0 完成。固定变量及非线性仍不在此工厂导出子集；支持矩阵按实际边界记录。
S06 的 [Gurobi 环境考察](s06-gurobi-research.md) 已独立验证 size-limited 本机微型 LP/MILP；
平台 Gurobi／native 接入仍需实现和真实验收。Actions 仍仅手动触发。
