# S09-C 人工辅助修订

用途：记录自SDK／Worker0.26.0接入的公开问题、Formulation和Code派生编辑。状态：功能代码与本机公共入口验收已完成；Web问题／代码／严格IR表单已验收，原生场景的浏览器验收与独立审阅继续补齐。对应 [Issue55](https://github.com/Fangziyang0910/LLM4OM/issues/55)、FR-26／32／35和AC-19／20；规范来源为[产物契约](../plugin-contracts.md)、[派生执行](../design/experiments-and-interfaces.md#dd-07-持久化恢复与报告)与[评测协议](../evaluation.md)。

## 使用

SDK使用`export_edit(run, operation="code")`取得公开编辑文档，修改后用`edit_run(run, edits_path)`创建派生运行。CLI对应：

```bash
uv run --locked llm4om edit --run-id RUN_ID --output runs --operation code > edits.json
uv run --locked llm4om edit --run-id RUN_ID --output runs --edits edits.json
```

网页打开已保存运行，点击“编辑并创建派生版本”，选择问题、Formulation或Code，填写reason后提交。新run保留parent_run_id及父公开历史，旧产物不改写。

当前按钮名为“编辑新版本”。选择“修改数学模型”后，已有严格IR显示目标、变量与约束的数值表单；无IR的原生表述保留高级文档入口。表单通过相同公开编辑文档提交，不增加新的执行路径。SDK／Worker0.34.0的实际HiGHS目标7、文本同步、父记录保持和零新增模型请求见 [用户界面](s09-user-experience.md#可读的严格ir编辑)。

公开编辑文档0.1.0包含operation、reason、problem、formulation、structured_ir、code、model_metadata与总budget。数据保持原始bytes/schema/hash；变更数据使用新问题导入。问题编辑必须保留problem_id并明确新revision，重新运行原建模方法；input-bound Mock不用于改变后的问题。Code-only保留原问题、源Formulation、IR与建模假设。严格IR修改使用现有Compiler生成Code；自由文本五元素不隐式编译为程序，原生Formulation/Code配对分别保留来源。

## 共同执行与预算

人工建模输出通过共同Method／ModelProposal／Compiler／Backend／Solver契约运行。`llm4om.methods.assisted`提供明确的human_assisted能力，不在普通自动建模菜单中呈现。人工Code不再请求LLM，且仅经容器执行；实际表示和求解器兼容性仍由统一预检约束。

编译器输出原为ConcreteModel工厂，原生Code契约要求ModelHandle。Code编辑模板公开附加保存symbol-map的适配代码，完整source对用户可见；执行时使用显示的手工版本，不宣称仍是原确定性编译的bytes。父原始编译源码和映射保留。

派生运行继承父paid/unknown调用、已知tokens、未知预留、Solver调用和候选。budget是包含父消耗的总上限，可显式改变并在lineage记录，不重置旧消耗。人工源与RunBundle标记assisted，自动实验报告单独记录N_assisted；不能作为未辅助的方法结果比较。

父公开checkpoint与引用按现有存储契约验证。显式新修订在当前SDK执行，lineage记录parent_sdk；这不同于继续旧checkpoint。私有Gateway链必须仍能验证，不能在缺少付费记录时猜测为零。公开导出不含Gateway原始archive、oracle或凭据。

## 验收

本机SDK修改IR和Code，在实际HiGHS得到可手算目标5，父目标13产物保持bytes不变；Code在实际容器执行，无额外LLM。HTTP公开问题revision1→2重新请求synthetic Provider，再人工修改Code，保持两次Provider请求，总Solver与候选各3，父bundle bytes不变。本机HTTP检查19.783s通过，40+1模块类型检查和JS语法通过。

native gurobipy与native_script的编辑路径通过同一表示契约实现，工厂及带／不带原生表述脚本三个分支已通过真实Gurobi，手工改界后目标为5，LLM请求为0；该公共入口检查31.893s通过。尚未取得浏览器视觉与独立Standards／Spec证据；全项目比较、性能与插件注册范围保持不变。

实际支持：严格IR→确定性Pyomo编译、Python工厂→容器HiGHS、native gurobipy工厂→容器Gurobi、带／不带原生Formulation的native_script→共同执行资源／独立Gurobi采集。工厂需ModelHandle；脚本仍保留原data.json。脚本在方法步骤中执行并保存checkpoint，最终复用相同执行记录。契约与原生表述版本按源产物保留；不能把native0.3表述误作five_element0.2。

当前Web已新增可读的问题／代码编辑、原因与总预算表单，完整文档保留为高级入口。SDK／Worker仍0.31.0，不改原执行契约。浏览器代码修订→真实容器HiGHS5、父bundle不变、零新增模型请求与assisted标记已观察，见 [用户界面](s09-user-experience.md)。问题重新建模仅在原Provider配置可用时执行；来自无LLM手工版本的后续问题修改仍遵循已有应用接口的拒绝规则，不自动切换方法或Provider。
