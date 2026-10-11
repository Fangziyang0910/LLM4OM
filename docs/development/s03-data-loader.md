# S03-C4：公开数据加载与有限视图

用途：记录SDK／Worker0.22.0的数据加载扩展及本机验收。工作项为 [#45](https://github.com/Fangziyang0910/LLM4OM/issues/45)。规范来源为 [插件契约](../plugin-contracts.md#27-s03-c4-public-dataloader-and-dataview-sdk-0220)，领域词由 [GLOSSARY](../../GLOSSARY.md)维护。本切片已完成实现与本机验收；2026-10-11独立Standards／Spec审阅通过：8个注册模块全部PASS／PASS-WITH-NOTES，无P1/P2，仅P3打磨项（报告/tmp/llm4om-reviews/s03-registry-group.md）。包未发布。

## 实际行为

公开CSV／JSON和独立安装的DataLoader使用共同Manifest、entry point及配置／依赖校验。核心先检查公开路径、8 MiB有界读取、原始hash与既有数据规则；加载器只收到原始公开bytes、复制的schema和路径无关元数据。原始快照、求解数据绑定和视图hash分别保留。

CSV支持完整原始bytes、有限原始行列和结构摘要。JSON对象支持完整原始bytes或顶层结构摘要，尚无嵌套数组行选择或数值汇总。核心独立校验真实行列、原值与重复次数、来源hash和大小。完整数据要求不接受不完整视图。Direct／feedback_repair把实际视图与元数据写入提示；旧方法默认要求完整视图，MethodContext.data仍保留原始公开bytes。

运行保存data-views.json及每份视图内容；在线llm-trace引用不可变视图记录。Loader身份、配置和视图限制进入admission／恢复。独立 [工程wheel](../../examples/plugins/fixture_data_loader/README.md)真正改变暴露列顺序；核心没有为该插件ID增加分支。示例配置见 [data-view.yaml](../../examples/specs/data-view.yaml)。

## 本机证据与剩余条件

前10项源码聚焦测试／21.778s通过。负例发现并修复了行列伪报、SDK原始hash遗漏；CSV错误现在给出实际row／column，私有Loader异常不进入公开材料。原始参数化工厂的实际容器1项／5.011s通过：LLM只收到产品A的一行／利润列，工厂仍读取完整原始CSV，实际HiGHS得到A3／B2／目标13。独立原问题容量／整数域／利润检查通过。固定本地HTTP响应只证明工程与数值求解行为，不证明模型准确率。

最终稳定源码14项／38.194s、干净Python3.11 wheel14项／38.837s通过，包括实际参数化容器与原问题独立检查。类型38模块、仓库221文件、参考资料和包构建通过。源码／wheel／Worker的代码hash一致，为8ccf44da8a83627269d15f778bea7f4435e61c005fea76ce78acbedcd47ed323，镜像为844ef15d2b4669ad4827b0079488c2c454f2621c3b164c1a82c314c2e26ef244。源码221文件与wheel59项的已知密钥检查未发现密钥；根目录.env保持忽略且权限0600。CSV字节截断改为逐行计数，1000行头部超限微型测试从0.586s降到0.002s；这不代表大型benchmark性能。一次完整本机回归405项／993.864s结束，三项旧镜像配置失败；对应源码与干净wheel重验通过，详见下文。没有第二次整套回归。独立Standards／Spec审阅另行进行；自查不替代独立审阅。本轮不触发Actions或新增付费模型调用。完整1.0范围保留其他插件、批量／报告、Web和发布验收。

原完整回归发现三条旧Backend测试仍指定0.21.0插件镜像。独立工作树把默认值改为由DEFAULT_IMAGE派生，并为本机／手动CI补齐独立wheel镜像构建前提。修复后源码工厂1项／5.741s、native／原CoE脚本2项／12.044s，以及干净Python3.11 wheel工厂1项／6.904s、native2项／14.507s通过。SDK代码hash未改变，原回归继续使用原测试快照；没有第二次完整回归。0.22.0插件镜像为6cef384a894329c8adaba6d06b0972a7a56fb34f1393cde94e81a48908e62410，旧0.21.0镜像保持原身份。

持久运行f35da2fb10bb490fb73b247afc3b0673保存了独立Loader的实际有限视图、原始工厂和真实HiGHS13，原问题独立检查通过。完成后恢复不增加预算或HTTP请求。来源是固定本地HTTP响应，不是实际模型准确率实验。公开91文件已知密钥检查未发现密钥，私有Provider archive不公开导出。

交付审查明确OptiMUS／CoE需要完整原始数据，避免继承Direct的有限视图声明。两个公开SDK实际运行均在生成前拒绝部分视图，LLM／Solver预算均为零。交付源码／wheel／Worker代码hash为d127059576252b3a9659dae55356555fd0d780d1740cc7fc2709ec223c02405e；早期8ccf快照的wheel与pilot镜像另行保留，旧运行不静默迁移。
2026-10-11 P3 处置：allow-list 缺失列经复核为合法路径——投影列允许来自关联文件而非本文件，故不在边界拒绝（曾尝试收紧并回退）。`PublicDataFactory.create` 忽略 config 与其空 schema 一致。
