# S09 Web并发应用进程

用途：记录SDK／Worker0.28.0的并发运行和合作取消。状态：功能与本机聚焦验收已完成，独立审阅待完成。工作项为[Issue59](https://github.com/Fangziyang0910/LLM4OM/issues/59)。规范来源为[插件契约](../plugin-contracts.md)、FR-33／35和NFR-03／06。

## 行为

Web工作区保留两个执行槽和最多八个排队任务。每次run、resume、edit使用独立CLI应用进程；插件发现和doctor也使用独立进程。可信插件的输出重定向和模块状态不再与另一个Web运行或HTTP请求共享。应用进程继续调用同一run_problem／resume_run／edit_run，不新增建模、评估或恢复状态机。原公开HTTP字段与数据／oracle边界不变。

取消首先向拥有的应用进程组发送SIGINT，由原应用保存取消结果、未知模型预留和候选。最多等待十秒，仍未退出则清理拥有的进程；正常资源子进程仍采用原来的立即取消语义。任务自己的deadline保持有效。人工编辑的监督上限来自显式编辑budget；恢复使用所选run的保存配置。无法合作退出时公开job错误保留，不伪造完成bundle。

doctor临时配置位于原工作目录，保持相对配置资源的解析规则；内容不含密钥，结束删除。原0.27.0镜像、wheel、任务与运行记录保留，不静默更新冻结身份。

## 验收

公共HTTP验收同时提交两个问题，Provider用两方barrier确认调用真实重叠；两次运行分别通过实际HiGHS。之后验证已完成继续没有新模型请求，问题revision与Code编辑保留父bytes与累计预算，再取消正在等待HTTP响应的第三任务并检查终态bundle。它使用合成Provider响应，不作为真实模型准确率。已有真实DeepSeek证据继续由前序切片维护。

浏览器桌面／手机布局、方法选择、doctor、历史结果与批量配置入口已验收；完整压力／故障报告和独立Standards／Spec审阅仍待完成；完整1.0未完成。本轮不运行GitHub Actions或重复全量回归。

公共HTTP并发／恢复／编辑／取消验收22.485s通过；同源／远程IPv4/token检查0.278s通过。资源取消原行为检查与应用进程合作／拒绝合作检查通过，后者0.310s。mypy41模块、仓库241文件和diff检查通过。

最终源码／Worker代码hash为72b2f0d37365b3f32a94fdcb4cb73eef8c8d174bea159f385afe9a3a460a6b03；最终镜像sha256:35403f20b47bb16326e0facb49c5e6a294debb521ecc9e06a856267ec6fe7d3a。网页批量／取消／继续的既有实际HiGHS路径18.472s通过，见本机batch-check.log。Standards／Spec由父代理自查，不能替代独立双路审阅；PR保持draft，不合并、不公开发布。

本机Chrome通过真实10.150.68.218:8767页面验收，桌面1440×1100与手机390×844截图已查看。OptiMUS inline选择同步到Gurobi，doctor实际预检通过，四个历史job可读取，批量编辑器可打开；页面脚本错误为零。此次浏览器检查没有提交新模型任务。截图和运行脚本保存在/tmp/llm4om-s09-process-evidence；Cua控制接口没有提供浏览器，本次使用本机现有Playwright／Chrome，不将HTTP检查代称为浏览器验收。
