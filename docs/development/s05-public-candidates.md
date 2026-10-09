# S05-C1 公共候选评估与选择

SDK／Worker0.15.0 的开发切片；工作项为 [#32](https://github.com/Fangziyang0910/LLM4OM/issues/32)。字段与错误语义见 [接口契约第20节](../plugin-contracts.md#20-s05-c1-public-candidate-assessment-sdk-0150)，方法流程见 [DD-02](../design/modeling-methods.md#dd-02-方法内部生成修正与选择)。本切片完成候选资源，不将整个 S05-C 或1.0标为完成。

## 实际行为

安装的方法声明 `grounded_candidates/0.1.0`，通过 `context.resources.assess` 提交五元素 Formulation 和 grounded LPIR。核心复用已有校验、确定性编译和实际 Solver 流程，返回公开阶段诊断及可信执行引用。每个候选有独立目录、原始公开提案、身份 hash、来源与状态。

修正生成新候选，parent_ids 指向已评估父候选，change_reason 保留方法声明的改动理由。共享候选和修正预算在工作开始前入账；预算拒绝不增加求解调用。最终选择通过 `select` 保存规则、理由和候选身份。应用复用该候选的已完成执行。

当前真实支持为五元素＋grounded LPIR → Pyomo → HiGHS，覆盖本机受控子进程和真实容器 Worker。原有 Direct／OptiMUS／CoE、工厂和 native Code 路径保持各自支持声明；此切片不将它们全部标为支持通用多候选修正。SDK与 Worker0.14.0 的已验收镜像保留，不自动迁移旧运行。

## 本机证据

新增 CLI／安装方法行为测试：错误变量引用的父候选返回 invalid_ir；保留两条业务约束的子候选由真实 HiGHS 得到 A=3、B=2、目标13，最终只求解一次。另有真实隔离 Worker 验证同一目标。其他测试覆盖 max_repairs=0、候选上限、重复评估、身份不可重绑定、选择冻结、方法硬退出、评估 publication 崩溃及未知执行不重试。补充自查修复了离线预检和最终选择 publication 恢复；已落盘选择不会让方法重新选择。

Python3.12.11主要本机回归321项／762.221秒通过。两处最终修复使用相应 red→green 与最终9项候选聚焦测试／29.279秒验证；完整回归没有重复运行。干净Python3.11.13 wheel的9项测试／29.784秒通过。源码、wheel和Worker代码hash一致：`77da4590ecd80b6a442844fffa0136a70dbe7f4c33de2c97202c1646bd4a6e0f`；Worker image为 `sha256:48cd900535ec1d3a1b467cbebef67323099727d8cde1c72b70592a6835dc55e6`。

最终保留的真实CLI运行 `255a6e07e90a4d76ab5e7a081374ae3a` 选择002，候选2／修正1／实际Solver调用1／外部LLM请求0；实际解A=3、B=2、目标13。完整运行、父子候选、选择和恢复记录保存在 `/tmp/llm4om-s05c-evidence/actual-run/`。更早两个修复前快照和运行单独保留，不用于当前源码的恢复声明。

类型检查32个模块、仓库184文件检查、资料导出和 wheel／sdist 构建通过。完整证据在 `/tmp/llm4om-s05c-evidence/`；最终 Worker 构建日志为 `/tmp/llm4om-s05c-worker-build-delivery.log`。本切片没有新增付费 LLM 请求，也没有触发 GitHub Actions。

## 后续范围与审阅

后续 S05-C 实现 feedback_repair 策略、解析失败后的生成修正、数学约束变化诊断及工厂 Code-only 修正与原 Formulation 引用复用。澄清／新问题 revision 属于 S05-D。当前测试验证工程反馈与执行流程，不能据此报告 benchmark 语义正确率。

Standards／Spec 自查和独立审阅分别记录。独立审阅仍受当前 Codex CLI 用量上限影响；PR保持 draft，最终独立审阅验收项保留未勾选。
