# S09 用户建模界面

用途：记录面向用户的单问题 Web 流程、实际支持和验收。状态：SDK／Worker0.34.0 开发实现。规范来源为 [插件契约](../plugin-contracts.md)、[阶段设计](../adr/0004-formulation-and-code.md)和 [#64](https://github.com/Fangziyang0910/LLM4OM/issues/64)。

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

结果页的编辑入口展示问题描述、已有规则／假设、求解代码、修改原因和可调整总预算。已有严格IR提供数值表单；完整编辑文档仍可在高级区查看／应用，自由文本Formulation沿用高级入口，不将文本当作可执行模型。原数据绑定保留，不在此入口修改数据。

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

## 模型声明与需求原文

数学模型页中，目标、变量和约束记录的requirement_ids可以展开阅读原始需求。需求关联表列出原始需求与当前显示模型条目的声明关联；不存在关联时标为未记录，未知需求ID标明原问题未声明。页面不从目标值、关键词或求解成功推断关联，也不把关联表作为正确性分数。

模型声明来自对应Formulation引用的ModelArtifact，展示保存的假设、确认状态、来源和警告。其他格式的requirement_traces保留原表达并折叠显示，不猜测字段含义。未记录假设／警告与独立检查通过分别呈现。没有独立Formulation的方法可以在产物来源中查看声明和警告，仍不补造数学表述。

选中表述来源快照时，页面依据formulation_ref.artifact_id找到已公开的Formulation；不会把来源快照误标为缺失表述。方法中间state不套用最终模型的严格IR或声明；没有表述引用的输出也不使用其他候选IR补造数学模型。查看过程不触发模型、求解器或编辑请求。

本机Chrome使用既有真实Direct／HiGHS记录的隔离副本，核对利润／变量域需求原文、关联表、展开状态在轮询后保持、来源快照解析和390px布局；无页面错误、零POST。公开UI.records接口的合成输入分别验证待确认假设、警告、未知／未关联需求、其他候选声明不混入、无表述方法不借用其他IR，以及HTML文本不生成图片元素。合成输入不写入真实运行记录。入口tests/web_model_flow.cjs沿用本机浏览器环境变量；证据位于/tmp/llm4om-web-model-evidence。

本轮只修改前端呈现，SDK／Worker仍0.33.0，Python运行身份和镜像不变。没有新增付费模型请求、求解、batch、全量回归或Actions。

SDK／Worker0.34.0新增脱敏连接诊断，网页可以按已保存的attempt解释TLS、DNS、拒绝连接、重置和超时；旧失败无类别时仍显示通用错误，不事后猜测原因。实现、间歇性实际网络观察与本机复查入口见 [连接诊断](s05-connection-diagnostics.md)。

## 页面视觉与使用入口

首页以问题输入为中心，提供生产计划、项目选择和配餐优化三个示例。示例只填入描述，用户选择方法后主动提交。深色导航、流程引导卡片和分段结果页签统一页面层次；宽屏并列展示变量与约束，窄屏使用单列。

运行上限可通过普通表单调整模型请求次数、总Token、时间和求解次数，沿用现有RunConfig与服务端校验。模型声明和需求关联可以展开查看；有假设或警告时，模型声明默认展开。目标、变量、约束和求解结果保持主要展示位置。

本机Chrome一次检查覆盖三个示例、预算写入RunConfig、已保存真实运行的目标13、声明与需求展开，以及1440px／390px布局。没有页面错误或横向溢出，没有POST、模型调用或求解。脚本与截图位于/tmp/llm4om-web-session-evidence。此次只修改前端，SDK／Worker仍为0.34.0；未运行全量回归、批量benchmark或GitHub Actions。

## 交互式决策试算

结果区可以调整当前候选模型的变量值，即时查看线性目标与约束的代入结果。上限约束显示右侧减左侧的余量，下限约束显示左侧减右侧的余量，等式显示左侧减右侧的偏差。正上限、非负活动值的约束另显示容量条。恢复按钮重新填入已保存解；试算不会改写目标值、运行记录或触发求解。

入口只接受最终ModelArtifact关联Code的确定性编译source_ir_ref，并要求保存的解包含全部变量值。不从其他候选、自由文本、原生代码或人工编辑前的IR猜测当前模型。原生方法的结果与决策值照常呈现，当前没有这一试算入口。页面计算用于理解候选模型，不替代独立Evaluator。

本机Chrome使用既有真实DeepSeek／容器HiGHS运行的隔离副本：原解目标13；将A从3改为2时试算目标10，改为5时目标19且两项约束余量为-4／-1，页面以红色标出；保存结果仍为13。恢复、轮询保持与390px无溢出通过。入口tests/web_decision_flow.cjs，截图位于/tmp/llm4om-web-decision-evidence。受影响的模型展开检查也通过。全部零POST／零模型和求解调用，SDK／Worker不变，未运行全量回归或Actions。

## 候选与修正卡片

候选页展示同一运行的全部已保存候选，优先使用candidate.json的后续状态，生成快照只作尚无后续记录时的来源。每个候选显示父候选、修正原因、Formulation／Code／Solve的实际状态、候选目标和公开诊断。最终选择与规则来自保存的选择记录；方法未单独记录理由时明确显示未记录，不猜测选择机制。

有输出比较记录时，可以展开表述／IR变化、增加或删除的约束及丢失的需求关联。这些是方法声明输出的比较，不代替语义验证。候选目标属于各自模型，页面不按目标值自动排名。数学模型与代码按钮定位对应公开引用；查看原始候选记录仍保持全部候选卡片。

引用解析复用同一前端函数，核对公开namespace、relative_path、SHA-256和大小；完成时读取public_projections，进行中使用HTTP返回的已校验公开artifacts。页面不沿引用下载其他路径。

本机Chrome使用既有真实反馈修正运行的隔离副本：候选001未通过检查，候选002修正自001、真实HiGHS目标13并被选择。两张卡片、保存的选择理由、声明变化、模型／代码跳转、原始记录切换时保留全列表、轮询展开状态和390px布局通过；公开引用检查拒绝不匹配hash。入口tests/web_candidates_flow.cjs，截图位于/tmp/llm4om-web-candidates-evidence。零POST／模型／Solver调用，SDK／Worker仍0.34.0，未运行全量回归或Actions。

## 可读的严格IR编辑

“修改数学模型”在已有严格线性IR时显示普通表单：目标方向、常数与已有项的系数；变量类型、上下界；约束常数、系数、关系和右侧值。只有边界允许留空，表示无界。增加变量、约束或表达式项仍通过高级完整文档编辑；原生和自由文本表述沿用高级入口，不隐式编译。

数值改变后，新五元素表述的变量、目标与约束由编辑后的grounded IR机械排版，保留需求ID。集合、参数和数据仍表示原输入；改变输入规则或数据需要对应的问题修订／重新导入。执行继续使用已有Compiler与assisted流程，不新增模型调用。所有修改形成派生run并标记人工辅助，父记录保留，预算包含既有消耗。

本机Chrome在真实运行的临时副本中，把两个变量上界改为1、目标常数改为1、A系数改为4、两项资源限额改为3，容器HiGHS求得A=1、B=1、目标7。父bundle bytes保持不变，external_llm_requests不增加，Solver增加1，派生结果assisted=true。表述同步、预算填写、390px布局和页面无错误通过。编辑模板载入时暂时禁用范围切换与提交，避免并发读取同一运行。入口tests/web_model_edit_flow.cjs，截图与实际运行副本位于/tmp/llm4om-web-model-edit-evidence；SDK／Worker仍0.34.0，未运行全量回归或Actions。

## 保存运行页面链接

浏览器地址记录当前job、显式选中的run、结果页签和手动选中的公开产物。刷新时从同一公共HTTP接口载入结果，仍遵守原运行版本的导出和编辑绑定。地址未指定run时显示最新版本，与版本选择器的“最新版本”一致。

“此版本链接”固定当前已显示的run，可以保存或复制；它在普通HTTP远程访问时也可使用，不依赖浏览器剪贴板权限。链接不带凭据、编辑草稿、原始问题内容或运行数据，也不提交任务。新建问题时清空运行定位；进入开发者实验界面也清除单问题定位。

本机Chrome使用已保存原版13／派生版7的临时副本，核对最新版本链接、历史原版的代码产物书签、刷新恢复、选定版本导出、轮询保持、新问题清空和390px布局。入口tests/web_links_flow.cjs通过，零POST／模型／Solver调用。SDK／Worker仍0.34.0，未运行全量回归或Actions。

## 可读运行资源与求解摘要

运行详情显示累计模型尝试、外部请求、候选和求解次数，以及保存的总预算。Token总量、已知量和未知预留分别呈现；缺失费用与资源不填零。父版本消耗按账本保留，不从当前显示的调用列表重新统计。

求解摘要依据当前版本的最终SolveResult／ExecutionResult公开引用，展示原始与归一化状态、候选模型可行解、目标值、Best bound、报告Gap、Solver与Executor耗时、CPU时间和峰值内存。Gap保留报告原值，不重算；执行资源不冒充包含LLM的全运行资源。调用列表保留每次尝试的实际角色、模型、状态、耗时和用量；最近事件与完整原始记录可以展开。

公开父历史中的调用按attempt_id去重；当前版本记录优先，来源显示当前／父版本。过程区方法名也读取选定版本的public-config，不把原始job方法名当作人工修订的方法。

本机Chrome以既有真实13／派生7记录核对累计调用／预算、Best bound／Gap、CPU／内存、父调用来源和版本切换；合成公开UI输入核对总Token未知、已知0、预留37和费用未提供，缺失求解记录不补造求解摘要。390px无溢出／页面无错误通过。入口tests/web_runtime_flow.cjs，截图位于/tmp/llm4om-web-runtime-evidence；零POST／模型／Solver调用，SDK／Worker0.34.0不变，未运行全量回归或Actions。
