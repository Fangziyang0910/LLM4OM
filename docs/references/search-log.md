# 文献检索与核验记录

日期：2026-10-08（Asia/Tokyo）。目的：为 LLM4OM 的需求、领域对象、架构和详细设计建立一手资料依据。使用 AI 辅助检索、筛选和归纳。

## 1. 检索范围与纳入规则

检索覆盖自然语言自动优化建模、推理方法与专用模型、建模表示、公开 benchmark、正确性评测、交互系统及同类科研平台。时间范围主要为 2023～2026，保留早期竞赛的后续正式记录。

纳入直接相关的作者论文、官方出版记录和作者仓库；相邻的算法／程序生成、模型分析与高成本仿真表述任务单独标识。排除搜索命中中的数据库查询优化、通用 MoE Chain-of-Experts 和无关手语视频论文。二手资料只用于发现候选，不用于确认书目身份、接受状态或设计事实。

本次是覆盖主要技术路线的定向代表性综述。没有枚举所有数据库、所有候选或全部引用图，也没有形成 PRISMA 意义上的穷尽检索。搜索引擎命中总数不可稳定取得，不报告虚构的召回率。

## 2. 实际查询与来源

| 查询组 | 使用的查询示例 | 核验来源 |
|---|---|---|
| 平台与交互 | `LLM4AD 2412.17287`、`ORPilot optimization`、`OptiChat paper`、`OptiGuide Large Language Models paper` | arXiv、作者 GitHub、固定提交源码 |
| 推理方法 | `Chain-of-Experts: When LLMs Meet Complex Operations Research Problems`、`LLMOPT optimization modeling paper`、`OptiMUS-0.3 site:arxiv.org` | arXiv、OpenReview、PMLR、作者仓库 |
| benchmark | `MAMO mathematical modeling large language models`、`OptiBench ReSocratic`、`OptiBench Equivalence-Detection evaluation` | arXiv、ACL Anthology、OpenReview |
| 2026 扩展 | `Constructing Industrial-Scale Optimization Modeling Benchmark`、`text-to-optimization binding`、`IR2Solve site:arxiv.org`、`SAGE Strategy-Aware Optimization Modeling` | arXiv、作者仓库 |
| 评测与任务边界 | `Towards Human-aligned Evaluation for Linear Programming Word Problems`、`EquivaMap optimization formulation`、`LLaMoCo optimization modeling` | ACL Anthology、arXiv 正文 |
| 模型训练 | `Solver-Informed Reinforcement Learning optimization modeling` | arXiv、作者 SIRL 仓库 |
| 建模与求解 | `Pyomo AbstractModel ConcreteModel overview`、`Gurobi Optimization Status Codes TIME_LIMIT` | Pyomo、HiGHS、Gurobi 官方文档 |

网页检索对论文／技术事实仅采用一手结果。正文阅读以参考资料逐项标注的范围为准，摘要与目录读取不标为全文精读。

### arXiv API 定向核验

端点为 `https://export.arxiv.org/api/query`，参数为 `id_list` 与 `max_results`。使用 paper-lookup 的 `arxiv_atom.py` 解析 Atom XML，核对返回条目数、标题、作者、版本和发表元数据；没有自行用不受校验的 XML 解析替代该脚本。

| 批次 | id_list | max_results | 返回数量 |
|---|---|---|---|
| 种子 | 2412.17287,2402.10172,2405.17743,2411.01679,2502.11102,2509.22979,2303.08233,2508.10047,2605.02728 | 20 | 9 |
| 扩展 | 2407.19633,2410.13213,2407.09887,2405.13144,2505.11792,2608.02641,2602.10450,2605.02545,2403.01131,2501.08406,2512.18682 | 20 | 11 |
| 后续 | 2605.21751,2506.17637,2402.16269 | 10 | 3 |
| 补充 | 2409.16709,2502.14760,2307.03875 | 10 | 3，其中 1 项排除 |

请求顺序执行，间隔超过 arXiv 的三秒限频。保留 25 条相关 arXiv 记录；另有 CoE、图编辑距离评测和匿名 OptiBench 投稿三条官方来源，共 28 条。按论文 ID 去重，预印本与正式出版入口合并在同一资料条目中。

API 返回版本与实际选读版本可不同，例如 BIND 选读 v1，目录同时记录已检索到的 v2 元数据。源码提交与论文 revision 也分别记录。

## 3. 核验中的更正与不可用项

- 搜索到的其他论文把 Equivalence-Detection OptiBench 链接到 `2409.16709`。直接读取 arXiv 后发现它是手语视频生成论文，已排除，未填入资料库。该 OptiBench 保留官方 OpenReview ID `KD9F5Ap878`；作者与接受状态保持未核验。
- OpenReview 的部分网页／PDF直接读取触发 browser challenge，API 请求返回 HTTP 403。可用的官方索引摘要用于标题与摘要范围的核验，不能据此补写缺失作者或出版决定。CoE 和 ReSocratic 的书目另与作者仓库及 arXiv 正式记录核对。
- GitHub REST API 的提交查询返回 HTTP 403。随后使用公开 Git 协议取得四个系统的固定提交和选择性源码；没有伪造 API 获取成功，也没有把未读取的仓库记作源码审计。
- 部分官方文档直接读取失败，改用同一官方域的可访问记录。Pyomo 与 Gurobi 的实际依赖版本仍在实现时锁定，不把网页可读等同于本地兼容验收。
- OptiMUS 0.3 最新论文及 NLP4LP 的描述与早期版本不同；代码分支和数据发布版本必须单独冻结。
- ORPilot 的考察提交默认直接代码生成，IR 为可选节点，已据此修改相关工作表述。

## 4. 证据范围与后续维护

本次资料支持任务定义、方法分类、接口设计和接入准备。没有重跑作者实验、检验论文所有证明、完整审计所有数据，或将第三方数据复制到本仓库。性能数字不跨论文拼成排行榜。

后续适配时补齐实际数据 release／split、参考材料可用性、许可证、上游对照、预算与真实后端验证。新的检索按相同规则追加日期、出处和身份核验；不将旧资料自动标为当前验证结果。

## 5. 本轮两阶段与首批范围核验

2026-10-08：用户确认 Formulation／Code 两阶段及 LLMOPT 五元素默认表述，首批经典流程为 OptiMUS／CoE，模型以通用外部 LLM 为主。用户明确确认所写 nl4lp 指 NLP4LP，规范名采用 NLP4LP；外部项目使用相似别名时仍按出处、release 和内容 hash 判断身份。

- OptiDSL：arXiv API 请求 id_list=2608.07040、max_results=1；使用 paper-lookup 的 arxiv_atom.py，返回一条 v1 元数据。选读 HTML 方法／评测与 19 页 PDF 的补充 DSL 示例、提示；没有执行实现。匿名代码链接返回 HTTP 401/not_connected，不能核验其转换或兼容矩阵。资料增加为 R29，总计 29 项。
- LLMOPT：复核 §3.2.1、§3.4 和 Appendix H 的文本／LaTeX 五元素与代码生成模板；不将模板当作严格可执行语法。
- NLP4LP：[作者数据卡](https://huggingface.co/datasets/udell-lab/NLP4LP)列出 description、parameters、problem_info、参考代码及可用解；当前 CC BY NC 4.0／research-use 声明记录于导入来源，数据仍不复制进仓库。正式接入锁实际 release 和许可文本，不以本次网页观察代替数据验收。
- MAMO：[作者 README](https://github.com/FreedomIntelligence/Mamo)区分 ODE、Easy_LP 和 Complex_LP，并显示上游优化脚本使用 COPT；本版仅接入 LP/MILP 任务数据，不由此声称平台接入 COPT。
- CoE：复核既有固定提交中的专家路由与 evaluator 输入，补读 main.py 和 programming_expert.py。浅克隆按需取 blob 的 Git 请求出现 TLS 错误，随后从同一提交的公开 raw 文件读取成功；OpenReview 页面再次触发 browser challenge，保持原有官方记录与读取范围，不追加未读取的全文结论。

PyVRP 的 [VRPLIB 文档](https://pyvrp.org/dev/supported_vrplib_fields.html)用于核对“格式可读”与“约束特征已支持”的区别。本轮不重跑任何论文成绩。
