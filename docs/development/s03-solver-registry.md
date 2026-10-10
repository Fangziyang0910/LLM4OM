# S03-C3b：独立 ModelBackend／SolverBackend 注册

用途：记录SDK／Worker0.21.0开发中的构建／求解插件扩展。工作项为 [#43](https://github.com/Fangziyang0910/LLM4OM/issues/43)。契约来源为 [插件契约](../plugin-contracts.md)，完整范围由 [开发计划](../implementation-plan.md)维护。本切片尚未交付。

## 已接入的行为

共同Registry增加model_backend和solver_backend。Backend具有load／export接口，返回Worker-local ModelHandle；Solver具有runtime／solve接口。真实HiGHS与Gurobi可接收同一Pyomo Handle。原compile_ir→solve_highs／solve_gurobi入口保留。Backend校验公开决策覆盖与线性结构；显式零界内部变量只用于常数模型，不作为业务决策导出。

Manifest分别声明handle_profile、handle_profiles、result_profile和Solver options_schema。兼容性按实际Handle／结果profile匹配，实际配置的第三方ID保留并执行。原内置ID声明可以引用已注册的相同profile；这不更改方法生成的源码。grounded Compiler支持声明的Pyomo Handle profile，记录真正选择的Backend。

宿主冻结Backend／Solver的Manifest、配置、包来源与适用的宿主依赖。容器的SDK依赖在Worker预检，宿主基础安装不强制安装数值SDK。跨安装器身份比较保留执行包内容、Manifest与配置；Worker实际依赖版本进入runtime与admission。Runtime输出仍有界，生成代码不获得密钥或oracle。

独立 [工程wheel](../../examples/plugins/fixture_execution/README.md)改变实际变量组件名称，再由另一个Solver插件检查该组件并真实调用HiGHS。CLI／owned Worker已求得MILP目标13，且保存实际插件ID与组件配置。参数化工厂子进程和可信收集器均选择相同Backend；native Backend独立读取MPS，所选Solver接收重新读取的Handle。原生脚本保留原始代码与执行，再由绑定的Backend／Solver收集结果。恢复按冻结profile判断证据来源与SDK版本。

## 本机证据与剩余范围

首轮公共接口与CLI组合7项／3.606s通过。原HiGHS微型语义11项／0.141s与Gurobi10项／0.260s通过；类型检查37个模块通过。Registry、非法配置／不匹配Handle和非线性拒绝均从公共入口验证。容器与版本0.21.0的最终证据待完成后记录。

SDK0.21.0的源码7项／5.427s、独立wheel→容器HiGHS1项／6.377s和原Compiler9项／20.714s通过。原solve_run7项中缺SDK诊断发生兼容失败，已保留solver_unavailable语义并单独重验1项／0.428s通过；其余6项通过。仓库214文件校验通过。当前镜像是开发快照，源码后续变化将重新绑定最终镜像；尚未开始整套回归。

独立工厂1项／5.220s、独立native工厂1项／4.800s与原始CoE脚本／独立收集器1项／7.822s通过，分别求得13、13和12。原工厂12项／104.950s、Gurobi6项／48.749s和CoE10项／76.410s通过。完成后恢复与包变化拒绝1项／3.764s、缺Worker插件且预算未消耗1项／1.503s通过。公开Solver调用已走Registry，独立配置与实际求解1项／0.618s通过。

最终聚焦源码17项／38.599s、干净Python3.11 wheel17项／46.037s通过。独立连续LP的源码1项／4.121s及容器1项／6.092s求得40/3。异常结果测试发现并修复了请求选项伪报；非有限值与私有异常细节拒绝或脱敏，1项／7.661s通过。实际Handle的MILP不能绕过LP-only范围，red→green1项／0.111s通过。运行版本与安装版本不一致在生成前拒绝，1项／0.901s通过。

原稳定快照的源码／wheel／Worker代码hash均为e63b6c322e9f79ffac3618db31e4a770f0b93f6f629248750614edc361f78eb8。其镜像50f822fbc04c4024550973fe840386c7136342093ed5a51fcb07cafa8cf61ccc与含工程插件镜像ca012905d7cfccfb0efd7cf562c183cc1a01abe6149d1df23134077ded0ed41f仍供原回归与持久运行使用，已另存原wheel／pilot标签。持久运行5d963c23ee9844b99fe40d54b7b291e1通过独立原始CSV业务检查和预算不变的完成后恢复。214个源码文件、wheel58项与公开pilot80文件的已知密钥检查未发现密钥；根目录.env保持忽略且权限0600。

预检审查的负例证明Backend输入表示未参与匹配；该遗漏在独立工作树修复，red→green1项／0.533s通过。修复后源码18项／50.103s、干净Python3.11 wheel18项／48.552s与新标签容器1项／7.286s通过。修复后源码／wheel／Worker代码hash为670f09920b88a9512c5d80a53a6c4defa7de5a6597e025daf22da31353f4a478；两种新标签镜像分别为11ba391d144f089d82d4d60b58ab40288531426a5d33d6222b1966f38ddeb99c与e71bf15bd4a2d23e98e01bf739d32e2d7df30b549d0216bb0582d2285898083f。原回归的源码与标签未更改，旧pilot不静默迁移。

一次必要的完整本机回归正在运行。此快照不改源码或镜像标签；后续实际失败以独立工作树修复并聚焦重验。不触发Actions或新增付费模型调用。独立Standards／Spec审阅仍待CLI用量条件恢复；全1.0中的其他插件、批量报告、Web与发布验收继续推进。
