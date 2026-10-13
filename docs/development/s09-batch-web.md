# S09-B 网页批量实验

用途：记录SDK／Worker0.25.0的批量网页入口、当前实际支持与验收。功能代码已实现，本机HTTP批量流程通过验收；2026-10-11独立Standards／Spec审阅通过：五个模块全部PASS-WITH-NOTES，唯一P2（批量评估非原子写入的崩溃窗口丢失已完成评估）已当场修复并补回归测试，其余为P3打磨项（报告/tmp/llm4om-reviews/s08-s09-group.md）。对应 [Issue53](https://github.com/Fangziyang0910/LLM4OM/issues/53)、FR-34／35、DD-08；批量语义由 [契约](../plugin-contracts.md#8-experimentspec-与单问题-runconfig)和 [S08](s08-benchmark.md)维护。

2026-10-13 状态更新：`/api/experiments` HTTP 接口、调度与公共 ZIP 导出保留并由 `tests/test_web_experiments.py` 覆盖；工作台的"开发者工具 → 实验管理"页面入口按用户要求移除（工作台面向单问题交互用户，开发者批量实验走 CLI）。下文"使用"一节描述的是验收时的页面流程，保留作为接口语义记录。

## 使用

先在当前实现版本导入冻结任务至项目`runs/`或Web工作区`tasks/`。页面只列任务来源、协议、选中数量和Adapter，不传递私有评估材料。

```bash
uv run --locked llm4om import --config examples/specs/import-checker.json --output runs/web-production-task
uv run --locked llm4om serve --host 0.0.0.0 --port 8767 --workspace runs/web
```

点击“批量实验与比较”，选择任务，编辑配置变体、重复次数、总预算和明确排除。新建时使用当前单问题配置作为第一个变体；每个变体包含完整RunConfig。方法、模型、后端与求解器的选择由同一预检核验。该窗口用于配置研究运行；凭据仍留在服务端环境或.env。

## 当前功能

Web调用既有benchmark CLI／应用与Task/Evaluator，不实现第二份建模逻辑。后台保存实验ID和状态；页面轮询计划运行数、保存数、状态、分组指标、逐样本run_id与来源。页面先显示200条样本，完整JSONL／CSV通过公开ZIP下载。按来源／协议／配置／repeat分组，分别显示独立可行、目标匹配和verified solution；tokens／费用缺失显示unknown。

取消通过实验invocation的持久化身份通知调度器。调度器先写拥有run的合作取消请求，保留响应与预算，超过短暂退出时限才终止自己的子进程。恢复核验原输入和版本，完成样本标记为result_reused；已取消样本的继续执行仍受原deadline、方法checkpoint能力和未知调用预算约束，不静默重置。

公开ZIP只有公开experiment.json和5种报告文件，不包含原任务私有清单、oracle内容、内部调度状态或Provider archive。绑定0.0.0.0时使用服务器IPv4地址访问；当前仍为可信网络中的单用户工作台。

## 验证与后续

本机HTTP提交使用synthetic文本Provider与真实HiGHS，检验批量执行、原问题检查、分组、ZIP与完成继续。实际HTTP提交两个样本，真实HiGHS与原问题检查均通过；公共ZIP6文件，完成后继续保持run_id及2次Provider请求不变。本机完整公共入口检查18.580s通过，包含活动取消和继续；40模块类型检查及233文件仓库检查通过。浏览器布局未实际观察；S09的完整问题／代码派生编辑、三方法真实比较、规模性能与独立审阅仍需完成。

活动中的Python工厂已通过网页取消：调度器保存取消结果，停止拥有的执行，保留单样本分母；继续后完成同一run，未新增Provider请求。该检查用synthetic Provider和实际容器／HiGHS，工程结果不作为真实LLM准确率。检查结束后没有遗留llm4om.execution容器。浏览器控制工具当前返回零个可用surface，未取得浏览器渲染证据。
2026-10-11 P3 处置：submit_experiment 在写 spec 前本地校验 repeats/budget/exclusions（非法值即时 `invalid_request`，不再延迟到子进程失败）。备注（保留）：`--host 0.0.0.0` 下 check_origin 是 CSRF 缓解而非认证——单用户令牌模型不变，勿暴露于不受信网络；最新 run 按时间选择与进行中 resume/edit 存在瞬时竞态，影响限于显示/取消目标。
