# 建模过程与阶段产物（取代候选）

用途：记录 [ADR-0006](../adr/0006-modeling-process-replaces-candidate.md) 的实际行为与本机证据。状态：已实现，SDK／Worker 版本仍为 0.37.0 开发版。规格见 [#102](https://github.com/Fangziyang0910/LLM4OM/issues/102)，切片 [#103](https://github.com/Fangziyang0910/LLM4OM/issues/103)–[#106](https://github.com/Fangziyang0910/LLM4OM/issues/106)。字段与名称映射见 [接口契约第25节](../plugin-contracts.md#25-modeling-process-and-public-checks-2026-10-15)。

## 实际行为

方法通过 `resources.check` 请求公开检查，通过 `resources.select` 做最终选择。平台照常编译、执行和求解，并计入预算。运行目录使用 `checks/<check_id>/`（record.json、check.json）与 `selection.json`；bundle 使用 `selected_check_id`。完成的检查发出 `check_finished`，首次保存的最终选择发出 `selection_saved`。只改代码的修正复用父检查的表述引用。

Web 删除“候选方案”页。数学模型与求解代码页在有两个以上公开检查产出该阶段产物时显示修正历史：版本、所属检查、父检查与改动理由、最终选择标记，并可切换查看。只改代码时，数学模型页说明多次检查使用同一份表述。建模过程保留真实上报的方法步骤、阶段产物、每次公开检查（可展开诊断）和最终选择（展开查看规则与理由）。工作区默认展示求解结果，数学模型和求解代码可直接切换。建模时自动展开右侧过程，完成后默认收起，可随时重开；需要补充信息时自动打开过程。点击产物步骤进入对应阅读区并收起过程，求解完成步骤进入结果页签。窄屏过程与产物在同一空间切换；运行用量默认折叠。

早于本变更保存的候选布局运行可在 Web 只读浏览；名称只在页面内存中映射，不改写文件。这类运行不能继续、派生重跑或人工编辑：恢复由源码身份检查拒绝，人工编辑返回 `checkpoint_incompatible`。

实验报告新增 `pass_at_k`：同一 case 在 k 次 repeats 中任一次成功即计一次，分母为符合条件的 case 数。运行内修正不计样本。

## 本机证据

- Python 完整回归 448 项通过（1366 秒），包含新增的 Pass@k、旧布局编辑拒绝与选择事件断言。
- 浏览器流程（Chrome、确定性 guidance fixture）：全部核心 `tests/web_*flow.cjs` 通过，包括新增的 `web_stage_history_flow.cjs`（检查 001 invalid_ir → 检查 002 修正后选中，目标 13）与 `web_legacy_run_flow.cjs`（同一运行映射回旧布局后仍显示修正历史与检查步骤）。
- mypy 55 个模块、仓库检查、资料渲染检查通过。

## 未改变的范围

评测协议字段 `candidate_primal`、`candidate_objective` 等表示“被评测模型”的证据，属于已版本化的评测契约，本次未改名。历史切片记录保留其当时的术语与版本。

## 本机服务配置同步修复（2026-10-15）

用户最近四次运行在 admission 阶段返回 `invalid_config`。复现发现，长驻 Web 进程仍提供 `max_candidates`，而新执行程序已要求 `max_checks`；旧服务中的校验也尚未更新。当前源码与安装依赖一致，问题来自更新后没有重启后台进程。

保留原工作区、环境和监听参数重启后，bootstrap 的全部方法模板与当前源码一致。现有 10 条运行及 1467 个工作区文件内容哈希不变，默认密钥继续可用。历史失败记录保留原样；刷新页面后使用新配置开始运行。

验收：运行中服务的七种方法 × HiGHS／Gurobi／OR-Tools 共 21 个配置全部通过真实预检；同一支持矩阵的确定性方法流程与真实容器求解全部得到目标 13。浏览器验收补充检查页面生成的全部 21 个配置能被真实预检接口接受。未调用付费 LLM，未增加热更新或部署组件。
