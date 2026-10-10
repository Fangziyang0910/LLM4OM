# S09 用户建模界面

用途：记录面向用户的单问题 Web 流程、实际支持和验收。状态：SDK／Worker0.33.0 开发实现。规范来源为 [插件契约](../plugin-contracts.md)、[阶段设计](../adr/0004-formulation-and-code.md)和 [#64](https://github.com/Fangziyang0910/LLM4OM/issues/64)。

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

## 方法配置与中间版本浏览

前端依据Method的solvers声明和Solver接受的ModelHandle profile过滤选项。OptiMUS／CoE默认只显示Gurobi；Direct的Pyomo路径保留HiGHS和Gurobi。高级配置的不可用原选择保留并明确标记，提交被阻止，用户须选择有效选项。没有把配置静默改成另一个求解器；应用层prepare_run仍负责完整兼容预检。

方法已发布的artifact_ref可以直接连接过程条目与当前公开内容。页面匹配namespace、相对路径和SHA-256，只展示已由服务端加载的公开版本，不沿事件引用下载任意路径。如果事件引用的旧版本不在当前公开投影中，不将新版本冒充它。

OptiMUS六个保存状态按实际事件顺序出现：问题与参数、优化目标初稿、约束识别、约束数学表述、完整数学表述、数学表述与代码片段。点击选择对应状态；轮询保留用户选择。未形成数学模型时展示原问题与参数定义，代码片段保留真实bytes文本。最终源码仍在求解代码中。历史角色清单使用实际source-calls.json，不能从文件名猜测调用数量。

本机Chrome以既有真实OptiMUS记录验收六个状态的逐次定位、代码片段、历史选择保持、390px无溢出、无页面错误；方法选择与不可用配置标记通过。整个浏览器检查零POST／零LLM调用，不重建Worker或重跑求解。入口为tests/web_process_flow.cjs，环境变量LLM4OM_BROWSER_MODULE／LLM4OM_BROWSER_EXECUTABLE／LLM4OM_WEB_TEST_URL沿用上节。

## 可读的派生编辑

结果页的编辑入口展示问题描述、已有规则／假设、求解代码、修改原因和可调整总预算。原数据绑定保留，不在此入口修改数据。完整编辑文档仍可在高级区查看／应用；自由文本Formulation和严格IR的详细编辑继续使用这个高级入口，不将文本当作可执行模型。

问题修订显示新revision及重新调用模型的提示；代码修订保留原问题和表述，使用现有assisted执行，不新增模型请求。总预算包含父消耗，界面不自动重置或提高。空修改原因和不足的候选总上限被阻止；提交前重新检查当前run_id，版本已改变时要求重新载入。新结果与方法名称显示人工辅助，避免误认自动建模。

本机浏览器在隔离的完成运行副本中，经可读代码编辑器把两个变量上界改为1，实际容器HiGHS目标5。原bundle bytes不变，external_llm_requests不增加，Solver增加1，RunBundle.assisted=true；空原因拒绝、问题表单／revision／调用提示及390px无溢出／无页面错误通过。原服务的用户记录未用于修改测试。入口tests/web_edit_flow.cjs要求明确的临时workspace；不触发真实云调用，不重建镜像。

## 运行版本与指定父版本

存在多个已保存运行时，结果页提供版本选择，显示完成状态、人工修订标记和父运行。选择后，数学表述、代码、结果、导出和编辑共同绑定该版本；轮询保留选择。最新版本继续展示实际进展。历史版本不提供当前任务的取消／恢复／重跑按钮。

用户可以从原始自动建模版本再次修订问题。代码手工版本仍保留其实际无模型执行配置；页面不会替它找回或替换Provider。预算、数据和方法支持检查沿用共同应用用例，原bundle不覆盖。不同SDK的历史阅读不等于checkpoint恢复兼容。

本机公共HTTP验收：确定性Provider加实际HiGHS得到原始13，手工Code派生用容器HiGHS得到5，再明确选择原始父版本修订问题并重新建模得到13。只有两次合成Provider请求，父bundle bytes不变；读取和导出选定版本、父lineage及非法路径拒绝通过。tests/test_web_versions.py单项16.308s通过。

Chrome通过原始13／派生5的版本切换、对应导出链接、原始父版本编辑、轮询选择保持及390px无溢出／无页面错误。入口tests/web_history_flow.cjs只读检查，零POST／零模型调用。证据在本机/tmp/llm4om-web-history-evidence，不提交运行数据。Worker0.32.0最终身份为sha256:2e02db6e72b1477c4403a5068aa23c71a0b59afcad2c6fb4ed3d959769d769cd；初次预检查镜像保留为0.32.0-precheck，没有用它验收。

## 可读的输入数据

输入数据页显示原问题、输入规则和输入假设。假设区分原文声明、待确认和已确认，不把方法推断当作用户确认。CSV模型数据视图显示为行列表格，JSON显示为字段与值；视图完整性、原始行数／视图行数和页面截断分别标记。数据版本区可展开查看原始／视图SHA-256和视图字节数。

页面预览只读取已保存的公开content_ref。标准库CSV解析保留引号内逗号、多行文本和前导零；JSON中的false／null保持原类型的序列化表达。页面最多20行／16列，JSON最多20个字段，长单元格显示前256字符。完整已保存视图仍在公共导出中；预览不变更方法输入，也不声称已经查看全部原始数据。

本机公共HTTP单项5.420s通过：确定性Provider和Worker0.33.0容器HiGHS目标13；25行CSV页面仅20行但模型视图仍完整，逗号／换行／003保留，JSON数值／数组／false／null正确显示，原始来源hash一致。入口tests/test_web_data_previews.py不使用真实云模型。Chrome以既有真实运行的隔离副本核对products／capacities表值、完整视图标记、来源hash、原始记录折叠、轮询和390px布局，无页面错误、零POST。入口tests/web_data_flow.cjs只读，沿用本机浏览器环境变量。

证据位于/tmp/llm4om-web-data-evidence。Worker0.33.0身份为sha256:374489b868185d15b4a5d0c6047a666ba6b5edaf76d69a18789c20f548cc7b92；只构建此开发身份一次。未新增付费请求、批量benchmark、重复全量回归或GitHub Actions。
