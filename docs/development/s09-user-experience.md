# S09 用户建模界面

用途：记录面向用户的单问题 Web 流程、实际支持和验收。状态：SDK／Worker0.30.0 开发实现。规范来源为 [插件契约](../plugin-contracts.md)、[阶段设计](../adr/0004-formulation-and-code.md)和 [#64](https://github.com/Fangziyang0910/LLM4OM/issues/64)。

## 用户流程

输入自然语言问题，可选上传公开 CSV／JSON，选择建模方法、外部模型和求解器。方法说明和实际预算上限在提交前可见。高级配置保留完整 RunConfig。示例按钮只填入问题，不启动请求。

提交后，页面轮询实际运行记录。左侧按实际调用展示角色、所属阶段和完成时间；右侧提供数学模型、求解代码、候选方案、运行详情和输入数据。数学模型显示目标、变量域、约束、集合和参数；严格线性 IR 以可点击变量和公式呈现。原始记录默认折叠。求解结果显示最终选择的候选目标、终止状态、实际决策值和已知资源量，避免用首次中间求解替代最终结果。

Formulation 和 Code 保持两个建模阶段。Solve 表示求解。跨阶段的协调步骤单独标记，不增加第三个建模阶段。Direct 的一次联合生成如实显示为一个步骤；OptiMUS 展示原流程角色；CoE 展示实际选中的专家、协调者和汇总者。未产生独立 Formulation 的方法直接打开代码，页面不会从源码补造数学表述。

批量实验保留在折叠的开发者工具中。当前优先完成单问题核心流程和可视化，不追加集体 benchmark 运行。

## 进展与边界

方法通过现有 MethodResources.emit 发布版本化 modeling_step。运行中的 HTTP 只读取已校验 checkpoint 的 public projections，仍核对公开引用路径、大小和 hash；私有状态、LLM 原始 archive、凭据和 oracle 不进入页面。阶段产物可在最终 bundle 生成前出现。

界面不估计未知步骤总数或伪造完成百分比。历史运行没有步骤事件时使用已保存的调用清单和核心事件。未知费用仍显示未提供。候选最优与原问题正确性保持区别。

数值可视化当前支持实际线性 IR。OptiMUS原生状态中的目标、变量与约束按原表达呈现；运行中保存的状态也可查看，不将其伪装成严格IR。其他五元素文本保留原表达，只进行有限符号排版，不作为完整 LaTeX 解析器。原生代码显示真实源码和行号。支持键盘焦点、窄屏布局和减少动态效果设置。

## 验收

本机公共 HTTP 检查阻塞中的 Direct 调用：运行仍为 running 时读取公开输入和带时间戳的真实步骤；释放确定性 HTTP responder 后，真实 HiGHS 求得 A=3、B=2、目标13。该 responder 是工程 fixture，不代表外部 LLM 建模质量。

本机 Chrome 实际从页面输入、应用配置、提交、观察进行中的步骤、完成容器求解、查看公式和代码。检查变量关联、决策选中保持、JSON 默认折叠、角色详情和390px窄屏。历史真实 DeepSeek／HiGHS 与 CoE／Gurobi 记录用于确认最终引用和缺失 Formulation 的呈现。源代码类型检查与 JavaScript 语法检查用于受影响范围；不重复全量 benchmark、付费重试或 GitHub Actions。

外部模型可产生不完整或错误建模输出，页面保存实际失败和诊断；本切片没有改变方法算法、训练权重或独立评估协议。

本机记录：公共HTTP进展1项通过（3.503s）；CoE方法6项与OptiMUS方法9项通过（合计约1.4s）；42模块类型检查、252文件仓库检查与JS语法检查通过。Chrome页面实际容器HiGHS求解13，变量关联、选中保持、原始记录折叠、代码与390px窄屏通过，无页面错误。Worker0.30.0身份为`sha256:41549f695a5a7fef3fc7f7a2decfecaf4abe24bc9c4dee41e5984ad3901fd268`。截图和逐项观察保存在本机`/tmp/llm4om-web-experience-evidence`，不提交运行数据。

## 澄清、失败和角色输出

前端增强继续使用SDK／Worker0.30.0，不修改方法算法或Python运行身份，也不重建镜像。

反馈修正方法可以提出澄清。页面直接显示已保存的问题及原声明，用户选择确认，或填写完整的修订／补充文本。提交绑定原request_id。全部确认时继续同一run；新信息或修改声明时，页面显示将提交的问题描述，使用已有revised_problem接口创建新revision／派生run。原数据绑定和父历史保留。修订已存在的需求或假设时更新其原条目；新信息作为明确的用户需求保存。其他方法仍按各自声明，不因此声称支持澄清。

结果区分别展示表述结构、代码接口／构建、原问题可行性、参考目标匹配和业务语义证据。卡片来自已保存evaluation，缺失项目显示未提供。失败区解释实际错误code；运行详情保留诊断。点击CoE角色可展开该角色已保存的专家意见，多轮输出分别保留；这些意见不替代最终数学表述。

本机Chrome实际通过确认原声明→同run容器HiGHS13，以及补充A≤2→新revision／run容器HiGHS12。父bundle bytes保持不变；空回答被阻止；修订描述提交前可见；缺失独立检查仍显示未提供。真实历史超时与CoE专家输出的可读呈现也已观察。

### 本机复查入口

使用已安装的Playwright和Chrome，不触发GitHub Actions。先在一个终端启动确定性服务；workspace必须为空，不使用项目.env：

```bash
uv run --locked --extra solve python tests/helpers/web_guidance_server.py --workspace /tmp/llm4om-web-guidance-fixture
```

另一个终端执行，按本机安装填写Playwright模块和Chrome路径：

```bash
LLM4OM_BROWSER_MODULE=/path/to/playwright \
LLM4OM_BROWSER_EXECUTABLE=/path/to/chrome \
LLM4OM_WEB_TEST_URL=http://127.0.0.1:8774 \
LLM4OM_WEB_TEST_PROVIDER_URL=http://127.0.0.1:8775/v1 \
LLM4OM_WEB_TEST_WORKSPACE=/tmp/llm4om-web-guidance-fixture/jobs \
node tests/web_clarification_flow.cjs
```

此入口只接受本机fixture地址，生成确定性回复并调用已有真实HiGHS。它验证交互和工程流程，不证明外部LLM建模质量。结束后在服务终端按Ctrl-C；运行记录位于临时workspace。
