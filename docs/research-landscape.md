# 相关工作、参考系统与设计依据

调研日期：2026-10-08。依据公开论文、作者仓库与厂商官方文档；本次未部署这些系统。功能摘要是公开资料的归纳，平台定位与设计取舍是本项目的判断。

## 1. 自动算法设计的参考框架

[LLM4AD 官方仓库](https://github.com/Optima-CityU/LLM4AD) 与 [平台论文](https://arxiv.org/abs/2412.17287) 提供算法设计任务、搜索方法与 LLM 的统一接口以及评估和实验支持。LLM4OM 借鉴“不同方法与任务可统一接入”的平台思路，处理的主要对象是优化模型与建模证据。

## 2. 自动建模方法与数据工作

| 工作 | 公开贡献／定位 | 在 LLM4OM 中的接入位置 |
|---|---|---|
| [NL4Opt](https://arxiv.org/abs/2303.08233)／[官方数据仓库](https://github.com/nl4opt/nl4opt-competition) | 自然语言优化建模竞赛与 LP 结构表示任务 | TaskAdapter／dataset；不能假定所有版本都有可直接执行的参考答案 |
| [OptiMUS](https://github.com/teshnizi/OptiMUS)／[论文](https://arxiv.org/abs/2402.10172) | 建模与求解代码生成、调试、反馈；仓库含不同版本 | 1.0 Method Adapter，必须锁定上游版本和差异 |
| [ORLM](https://github.com/Cardinal-Operations/ORLM)／[论文](https://arxiv.org/abs/2405.17743) | OR-Instruct 数据合成、专用 LLM、IndustryOR | LLM 模型配置与任务数据；模型本身不是搜索方法 |
| [LLMOPT](https://github.com/antgroup/LLMOPT) | 学习型建模、代码生成、自修正及统一测试数据格式 | 后续模型／方法 Adapter 与数据导入参考；核对处理版本 |
| [Autoformulation](https://arxiv.org/abs/2411.01679) | 利用 LLM 与 MCTS 搜索优化模型表示 | 后续搜索 Method Adapter，不将内部树策略放进核心 |
| [OptMATH](https://arxiv.org/abs/2502.11102) | 双向数据合成与困难建模基准 | 后续 TaskAdapter；训练与测试来源分开 |
| [OptiMind](https://arxiv.org/abs/2509.22979) | 将优化专业知识与错误分析用于建模模型训练／推理 | 后续 LLM 模型与推理配置；专家证据参考 |

这里只归纳代表性贡献，不采纳不同论文的准确率作为可直接比较的平台 baseline。

## 3. 具有平台或工作台形态的系统

| 系统 | 公开文档描述 | 对本项目的意义与差异 |
|---|---|---|
| [ORPilot](https://github.com/GuangruiXieVT/ORPilot)／[论文](https://arxiv.org/abs/2605.02728) | 对话澄清、数据和参数处理、代码生成、多提供方／后端、IR 与修正 | 最值得深入检查的端到端开源系统；公开流程围绕其自身 Agent，本文未确认有多个论文方法的统一 registry |
| [OptiGuide](https://github.com/microsoft/OptiGuide) | 包含 what-if、MILP-Evolve 和 OptiMind 等项目 | 可参考优化分析与研究资源组织；多个子项目同仓库不自动等于统一运行契约 |
| [OptiChat](https://github.com/li-group/OptiChat) | 通过自然语言与已有 Pyomo 模型交互，提供诊断、敏感性、what-if／why-not | 后续模型审阅与分析入口，不等同于多方法自动建模实验平台 |
| [LLM4OR 门户与仓库](https://github.com/LLM4OR/LLM4OR) | 分类、benchmark、清洗标记和比较资料 | 用于相关工作及数据审计；公开仓库主要是门户资源 |
| [Gurobi Intelligence Hub](https://doc.gurobi.com/projects/intelligence/en/current/) | Modeler 生成数学模型、gurobipy 实现与测试；Explainer 处理模型分析 | 产品交互与验证流程参考；围绕 Gurobi 生态，不据此推断能插拔所有研究方法 |
| [MindOpt 官方发布记录](https://www.alibabacloud.com/help/en/optimization-solver/product-overview/release-notes) | 记载 Copilot 通过文本／表格生成模型和代码、求解与解释 | 产品案例；本次未确认其当前完整交互能力或外部方法扩展机制 |

本次检索未确认一个已公开且同时具备多种建模方法插件、独立 LLM／求解配置、统一基准与分层证据评测的通用开源实现；这是有限检索结论，不是“全球首个”的证明。

## 4. 建模语言与求解器

[Pyomo APPSI 官方文档](https://pyomo.readthedocs.io/en/stable/reference/topical/appsi/appsi.html) 列出 HiGHS、Gurobi 等求解接口。设计据此区分 ModelBackend 与 SolverBackend：Pyomo 是建模接口，HiGHS／Gurobi 才是数值求解器。实际兼容版本在实现时锁定并实测。

## 5. 接入前必须补齐的调查

上游具体分支／提交、依赖与许可证；数据实际版本、split 和参考材料；Provider 的 usage／工具／结构化输出差异；求解环境与模型提取行为；论文方法预算与实现偏差。本文没有完成这些源码级接入审计，因此 1.0 计划把它们作为各 Adapter 的验收工作。

不下载或直接复制第三方源码／数据以假装已经集成；本仓库当前只保存自己的需求、设计与自建 fixture。引用与参考不会改变第三方原有许可。
