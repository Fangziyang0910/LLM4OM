# S03 Reporter插件与公开报告

用途：记录SDK／Worker0.29.0的Reporter注册、单问题／实验输出与报告重试。状态：功能及本机聚焦验收已完成；2026-10-11独立Standards／Spec审阅通过：8个注册模块全部PASS／PASS-WITH-NOTES，无P1/P2，仅P3打磨项（报告/tmp/llm4om-reviews/s03-registry-group.md）。工作项为[Issue63](https://github.com/Fangziyang0910/LLM4OM/issues/63)。规范来源为[插件契约](../plugin-contracts.md)、FR-01／02／06／32／34／36与AC-01／02／21／22。完整1.0未完成。

## 已实现行为

JSONL、CSV、Markdown、HTML是共同Registry中的四个Reporter。外部包通过llm4om.plugins声明工厂实例；独立fixture包演示选取公开结果并产生自己的文件，不改核心调度或评分。

RunConfig.reporters支持plugin_id与可选config；省略或空列表仍保存RunBundle，不额外呈现报告。ExperimentSpec.reporters可明确选择；省略沿用四种现有默认格式，summary.json始终由核心生成。配置、依赖版本、结果scope、声明文件名与冲突在模型调用前检查，Reporter binding保存于admission／实验快照。后续渲染拒绝不一致的SDK／插件身份。

Reporter只接收已形成的公开rows与summary的深复制。它不能改变原结果、资格、评分或预算。ReportDestination暂存声明文件的bytes与引用，核心校验实际文件集合与hash后发布；相对文件名、namespace与总64MiB上限明确。第三方Reporter是已安装的可信Python插件，此接口不是恶意插件沙箱。

渲染异常、越界文件或伪造引用记录为report_errors；其他选中Reporter继续执行，模型／Solver结果不改成失败。单问题报告进入RunStore的不可变历史引用；实验报告保存公开hash／size引用。网页ZIP按照实际report_refs导出，不假定一定存在四种文件。

## 已保存结果的报告重试

当前CLI入口为llm4om report --run runs/RUN_ID和llm4om report --experiment runs/EXPERIMENT。SDK提供report_run(run)，实验沿用report_experiment(output)。单问题重试使用已保存的公开配置、结果与账本，并检查Reporter与SDK身份；不读取外部凭据、不创建Provider、不调用Solver。建模状态及其预算不变，报告诊断与新公开引用保存到运行记录。它不将新Reporter配置静默代入旧实验。

## 验收范围

独立Reporter wheel安装到独立target目录，经CLI发现／配置／真实HiGHS得到13。四格式、公开引用hash、结果副本修改隔离、异常／非法路径／伪造引用、建模前拒绝、报告重试及完成恢复均有聚焦检查。批量检查保留artifact_ready／budget_exhausted两行及各自分母，HTML和CSV使用公开Reporter契约检验注入字符的转义。合成／Mock结果属于工程证据，不作为模型准确率。

原0.28.0镜像、1000任务性能与100CLI故障证据保留；本切片不重复这些验收。Executor／ArtifactStore注册、真实100任务批量故障恢复、真实三方法三基准完整成功与独立审阅仍在范围内。没有Actions、付费模型请求、merge或公开发布。

最终4项公共Reporter检查24.319s通过，受影响离线／批量HiGHS两项9.070s通过，公共HTTP批量／取消／继续23.924s通过。类型42模块、仓库249文件、diff通过。独立fixture的entry point最初误指向未实例化工厂，已按既有工厂实例约定修正；初次测试误收集了导入的其他TestCase，已收窄为当前4项。没有重复全量回归。

SDK／Worker代码hash为c82179c5524cde4327600f19916d151fe6b01a366d6e6648c87bd7a0f3fd013d，镜像为sha256:37ddc82284e7f00b4b1ec203cb296ab51d81dcccfd10810d742e6612a987979b。本机证据在/tmp/llm4om-s03-reporters-evidence。Standards／Spec由父代理自查；当前没有可用的独立双路审阅者，draft PR不合并。完整1.0仍继续开发。

单问题Markdown保留明确模式、状态、方法、资源可用性和候选目标，避免将原始JSON作为可读报告主体；对应两项最终检查5.490s通过。仅选Markdown的网页ZIP实际导出三个公开文件，报告bytes变化时拒绝导出。
2026-10-11 P3 处置：ReportRef 核对改为对已存引用的多重集匹配，不再要求插入顺序完全一致；上限、转义与 summary.json 语义不变。
