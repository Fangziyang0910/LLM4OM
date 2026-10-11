# S06-C CoE 实现

状态：SDK／Worker0.13.0 本机实现验收通过；2026-10-11独立Standards／Spec审阅通过：PASS-WITH-NOTES，无P1/P2，8条P3打磨项（报告/tmp/llm4om-reviews/s06-group.md）。[#28](https://github.com/Fangziyang0910/LLM4OM/issues/28)。基线9451afa的0.12.0已通过290项本机回归。规范见 [插件契约](../plugin-contracts.md)、[评测协议](../evaluation.md)与 [固定源码考察](s06c-coe-source.md)。此文件区分已实现行为与尚未完成的交付验收。

当前保留7个专家、动态 conductor、顺序评论、reducer、可选公开测试和反向追责。匹配先扫描尚未参与的名称，再扫描整个注册表；允许重复专家。无效路由使用记录 seed 的随机回退。下一轮重新建立评论池，反思修改不重新执行 reducer。最后选择实际最后一次 reducer 原生代码，保留未执行的反思结果。

实现使用独立编写的提示词，变体为 `coe-fixed_transitions-original_prompts-single_import-native_function`。不复制上游无已确认许可的代码或提示词。固定源码提交为 afb89bf602690ea621f13a23c42722f20f653a43；提示词、输入、模型、随机源、采样／输出限制和一次导入差异逐项记录，不宣称 source-exact 或论文性能复现。

## 接口与实际执行

原生 Code 复用公共执行／记录资源。默认接口 `prob_problem()` 支持自然语言与可选公开数据；也可指定公共 JSON 的 code_example、entry_point、input。starter 只直接进入程序相关专家和公开测试提示，不直接进入 conductor／reducer／其他专家。conductor 不接收评论正文。数学专家可选，所以此适配不合成最终 Formulation。

公共 `native_script/0.2.0` profile 允许 Formulation 不可用、Code 可用。ModelProposal 的 formulation 可为 null；公共产物、校验、事件、报告和恢复保留这一状态。已有 grounded／factory／native-script0.1 profiles仍要求其声明的 Formulation。原始函数、提取结果和实际 driver 各有真实来源，不改写成 build_model 工厂。

函数只在隔离候选子进程执行。反思按第一个字母序 prob_* 函数调用生成的公开参数，忽略函数返回值；stdout／stderr 与独立收集器结果分开。缺 prob_* 会停止反思，不静默改名；异常诊断是非受信任代码的公开反馈。原执行的 import＋reload在此变体中改为一次导入，避免未声明的双重副作用。固定行为差异在 fidelity report 中记录。

公开测试参数不替换原任务参数。反思结束后，选中的原生代码按原始公开接口再次调用和独立求解；这是单独的预算执行。collector失败不能触发基于它的反思，标量返回值不能制造 trusted SolveResult。原始公共测试失败、反思耗尽及最终解各自记录。

所有角色走同一 Gateway，使用配置的通用外部模型。当前采样与输出 cap继承 Provider配置，与上游 conductor cap10不同；这是显式适配，不能写为精确提示／运行对照。成功的最终执行复用已有收据，未知执行不重发。CoE未实现内部方法 checkpoint；完整 Code 发布后的核心恢复已测试，不冒充中间专家状态恢复。

## 当前证据与剩余验收

本机6项公共 Method／Context tape测试覆盖动态／重复／无效路由、代码提取、反向追责、解析失败、首次公开通过和下一轮清空评论。合成 HTTP＋实际 Gurobi测试覆盖原生函数、目标12、缺 Formulation、无模型的伪返回值、profile／预算拒绝、反思再试、非 prob_*、最终失败、自然语言默认接口、capacity7测试与capacity4原任务分离、取消与完整 Code 崩溃恢复。OptiMUS9项流程回归通过。

这些结果不代表真实模型质量。0.13.0的6项方法 tape与10项实际 HTTP／Gurobi聚焦测试通过；源码／Worker身份一致。真实指定模型与原问题独立检查已通过。干净 Python3.11 wheel的10项应用测试／70.573秒通过；Python3.12.11完整本机回归306项／702.09秒通过。mypy32个模块、仓库179文件、参考资料／diff和wheel／sdist检查通过。独立 Standards／Spec 审阅仍受本机 CLI 配额限制；不得将父自查当作独立审阅。GitHub Actions仅手动补充；本切片未触发远程 CI、发布包或改变私有可见性。完整1.0仍包括后续修正／澄清、角色配置、批量实验、Web和发布验收。

真实 run `f50a813f8da54e8aaad5db4db37ca25e` 使用指定 deepseek-v4-pro-0813，11次调用／12695个已报告 token，成本未知。公开测试生成器加入了多余的 description 参数，公开调用失败且反思耗尽；该状态未改写为通过。实际最后 reducer代码按原接口／原参数执行，独立 Gurobi得到 qty_A=3、qty_B=2；原始 CSV检查器确认整数域、全部容量和原利润13。两个结论分别报告，不能用最终解正确来宣称公开测试生成或整个模型语义已验证。

实际模型输入未包含私有参考目标、决策映射或性质点；检查器只在最终选定输出后运行。原生 Code 的有限 IR性质检查为 not_available。固定源码直接运行／精确提示对照仍为not_available；独立编写的流程与公开 transition tapes不标为原源码运行。完整材料在 `/tmp/llm4om-s06c-implementation/real-acceptance/verification.json`。

已验收代码 hash为 `036b919517a6fbe383245ad9d021f67bdc92708a06df6fa98d4cf6a8a4ce36df`，源码／wheel／Worker一致。镜像 `sha256:fcfa48c9913d9e0ca9e419ed1b385a27609072a28e7aac5066db220ead4d8afe`；旧0.12.0镜像保留。真实运行的无密钥CLI resume保持调用与预算账本不变。179个源文件、154个公开运行文件与wheel通过实际密钥扫描；私有oracle不进入方法提示或Worker。完整本机日志在 `/tmp/llm4om-s06c-implementation/verification.json` 及其相邻文件，不提交运行数据。
