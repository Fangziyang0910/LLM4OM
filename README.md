<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.svg">
    <img src="docs/assets/banner-light.svg" alt="LLM4OM：用自然语言描述优化问题，得到可核对的数学模型、代码与最优解" width="100%">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/Fangziyang0910/LLM4OM/actions/workflows/checks.yml"><img src="https://github.com/Fangziyang0910/LLM4OM/actions/workflows/checks.yml/badge.svg" alt="Checks"></a>
  <img src="https://img.shields.io/badge/version-0.41.1-4f39f6" alt="版本 0.41.1">
  <img src="https://img.shields.io/badge/python-3.11%E2%80%933.13-3776ab?logo=python&logoColor=white" alt="Python 3.11–3.13">
  <img src="https://img.shields.io/badge/LangGraph-server-1c3c3c?logo=langchain&logoColor=white" alt="LangGraph">
  <img src="https://img.shields.io/badge/deploy-Docker%20Compose-2496ed?logo=docker&logoColor=white" alt="Docker Compose">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="Apache-2.0"></a>
</p>

<p align="center">
  <b>中文</b> · <a href="README.en.md">English</a>
  <br>
  <a href="#快速开始">快速开始</a> ·
  <a href="#建模方法">建模方法</a> ·
  <a href="docs/user-guide.md">使用指南</a> ·
  <a href="docs/deployment.md">部署指南</a> ·
  <a href="CONTRIBUTING.md">开发指南</a> ·
  <a href="CHANGELOG.md">更新日志</a>
</p>

---

**LLM4OM**（Large Language Models for Optimization Modeling）是一个自动优化建模平台。你用自然语言描述问题，选择建模方法和代码写法。平台调用 LLM 写出数学模型和求解代码，在隔离的容器中求解，并展示每一步的中间产物。

平台内置 **13 种 LLM 建模方法**，包括 Direct、Feedback Repair 两种自有方法，以及 11 种来自公开研究的方法。你不需要手写求解代码，可以直接输入问题、运行建模，再查看模型和结果。

<p align="center">
  <img src="docs/assets/demo.gif" alt="演示：选择运输问题和 ORThought，开始建模，查看解、数学模型和代码" width="100%">
  <br><sub>真实运行录屏：运输问题 · ORThought · Pyomo/HiGHS · DeepSeek。建模阶段已加速 2 倍。</sub>
</p>

## 亮点

| 能力 | 说明 |
|---|---|
| 🧠 **13 种建模方法** | Direct、Feedback Repair、TriVAL、SAC-Opt、BIND、OptiMind 等；每种方法都有独立 LangGraph 图 |
| 🧩 **12 条求解路径** | 9 种建模接口、11 个求解器，覆盖 LP、MILP、约束规划、凸优化和非线性优化 |
| 🔍 **全过程可见** | 每次 LLM 调用实时显示；保留中断前已完成的步骤和产物；历史可分页，运行配置固定记录 |
| ⚖️ **多方法对比** | 同一问题一次运行最多 12 个方法或模型，并排比较目标值、用时和 token |
| 🧯 **不可行诊断** | 模型不可行时，列出一组不能同时满足的约束（Gurobi IIS / CPMpy MUS） |
| 🔒 **隔离沙箱** | 生成代码在无网络、只读、非 root 的容器中运行，用完即删 |
| 👥 **团队部署** | 一条 `docker compose up` 启动；预设模型的密钥不出服务器；可选 HTTPS 和用量上限 |
| 🌗 **好用的工作台** | 备注与标签、Markdown 报告、Excel 导入、2033 道公开题、中英文界面、深色模式 |

## 截图

<table>
  <tr>
    <td width="50%"><img src="docs/assets/home.png" alt="新建页面"><p align="center"><sub>写问题，选择方法、写法和模型</sub></p></td>
    <td width="50%"><img src="docs/assets/run.png" alt="运行结果"><p align="center"><sub>结论先行：目标值、建模过程和解的矩阵</sub></p></td>
  </tr>
  <tr>
    <td><img src="docs/assets/formulation.png" alt="数学模型"><p align="center"><sub>数学模型用 LaTeX 渲染，每一版都能对比</sub></p></td>
    <td><img src="docs/assets/compare.png" alt="方法对比"><p align="center"><sub>5 种方法同题对比</sub></p></td>
  </tr>
  <tr>
    <td><img src="docs/assets/conflict.png" alt="不可行诊断"><p align="center"><sub>不可行模型：Gurobi IIS 找到 3 条冲突约束</sub></p></td>
    <td><img src="docs/assets/dark-en.png" alt="深色英文界面"><p align="center"><sub>深色模式和英文界面</sub></p></td>
  </tr>
</table>

## 快速开始

### 方式一：Docker（推荐）

只需要 Docker（含 Compose v2.24 或更新版本）：

```bash
git clone https://github.com/Fangziyang0910/LLM4OM.git && cd LLM4OM
cp .env.example .env && chmod 600 .env    # 填写 LLM 服务商、地址、模型和密钥
docker compose up -d --build
```

打开 <http://localhost:8767>。同一网络中的其他人用 `http://<本机 IP>:8767` 访问。HTTPS、备份、用量上限和 Gurobi 许可证见[部署指南](docs/deployment.md)。

### 方式二：本地运行

需要 Python 3.11–3.13、[uv](https://docs.astral.sh/uv/) 和 Docker：

```bash
uv sync --all-extras
uv run llm4om build-worker      # 构建求解沙箱镜像 llm4om-worker:10
uv run llm4om serve --workspace runs/web --port 8767
```

仓库已包含前端构建文件，不需要 Node.js。

### 试一个问题

1. 没有在 `.env` 中设置模型时，点击左下角“预设模型”，添加服务商、密钥和模型 ID。
2. 点击首页的“生产计划”例子，或输入：

   > 工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。A 消耗 2 单位切割资源和 1 单位加工资源，B 消耗 1 单位切割资源和 2 单位加工资源。两种资源各有 8 单位。请确定生产数量，使总利润最大。

3. 点击“开始建模”。几秒后，页面给出最优解 A=3、B=2，总利润 13。

也可以在命令行或 Python 中运行：

```bash
uv run llm4om run --problem "……" --method orthought --language pyomo
```

```python
from llm4om import run_problem

state = run_problem("……", method="optimus", language="gurobipy")
print(state["failure"] or state["solve"]["objective"])
```

完整用法见[使用指南](docs/user-guide.md)。

## 建模方法

| 方法 | 流程 | 来源 |
|---|---|---|
| Direct | 一次调用，同时给出数学模型和代码 | 基线 |
| Feedback Repair | 生成、求解、复核题意一致性，按格式、执行或建模问题修正 | 自有方法 |
| TriVAL | 语义、数学模型、代码三阶段验证；每阶段构建、验证、修订 | [代码](https://github.com/SCUT-EIPI/TriVAL/tree/380a529) |
| OptiMUS 0.3 | 提取参数、目标和约束，逐条建模和写代码，组装后调试 | [v0.3 论文](https://arxiv.org/abs/2407.19633) · [代码](https://github.com/teshnizi/OptiMUS/tree/e182e9ef5841605c2a7e87467021fd83522b6484) |
| Chain-of-Experts | 协调者逐个选择专家，汇总器写代码；可选反向反思 | [ICLR 2024](https://openreview.net/forum?id=HobyL1B9CZ) · [代码](https://github.com/xzymustbexzy/Chain-of-Experts/tree/afb89bf602690ea621f13a23c42722f20f653a43) |
| OptiTree | 在问题类型树中匹配建模思路，再生成模型和代码 | [NeurIPS 2025](https://arxiv.org/abs/2510.22192) · [代码](https://github.com/MIRALab-USTC/OptiTree/tree/2e70ecfd0a3c8e9c0c16d36d7d498a7344cfdec9) |
| OR-LLM-Agent | 先数学建模，再生成代码，按执行错误调试，最后检查不可行 | [arXiv](https://arxiv.org/abs/2503.10009) · [代码](https://github.com/bwz96sco/or_llm_agent/tree/5dccdaab89ab91c3cb28066fe849423dc124d287) |
| ORThought | 按专家建模思路写出求解思路、数学模型和代码；出错时带上模型和错误调试 | [arXiv](https://arxiv.org/abs/2508.14410) · [代码](https://github.com/BeinuoYang/ORThought/tree/5293e24861a65d1e4a2f61f4fad0a81de901ee38) |
| LLMOPT | 先写五要素模型，再写代码；LLM 判断对错，回到错的一步重写 | [ICLR 2025](https://arxiv.org/abs/2410.13213) · [代码](https://github.com/antgroup/LLMOPT/tree/1492dd33e39ea13f1afe32a0adc13d4217334195) |
| AutoFormulation | 逐层采样并剪枝建树，再用 MCTS 和两两比较排名（调用量很大） | [ICML 2025](https://arxiv.org/abs/2411.01679) · [代码](https://github.com/jumpynitro/AutoFormulator/tree/52148018d04de23dc2d36d4281eb6244c2a42ffc) |
| SAC-Opt | 语义锚点提取、约束代码回译、比较与选择性修正（独立实现） | [论文](https://proceedings.mlr.press/v306/zhang26cb.html) · [适配说明](src/llm4om/methods/sac_opt/README.md) |
| BIND | 提示只读附件结构，代码读取完整数据，执行失败时修正 | [论文](https://arxiv.org/abs/2605.21751) · [适配说明](src/llm4om/methods/bind/README.md) |
| OptiMind | 公开类型提示、建模、求解反馈与多轮检查 | [论文](https://arxiv.org/abs/2509.22979) · [公开范围](src/llm4om/methods/optimind/README.md) |

各方法固定参考提交并记录差异。SAC-Opt 根据公开算法独立实现；BIND 不使用基准参考答案；OptiMind 接入公开推理流程，提示库目前只有旅行商问题。方法只开放实际支持的代码写法。详见[建模方法](docs/methods.md)。

## 代码写法与求解器

用户选择代码写法，写法决定求解器。生成的代码定义 `build_model(data)` 并返回模型，由沙箱用该写法自己的接口求解。

| 代码写法 | 求解器 | 适用问题 |
|---|---|---|
| Pyomo | HiGHS | LP、MILP |
| gurobipy | Gurobi | LP、MILP（无完整许可证时只能求解小规模模型） |
| OR-Tools `pywraplp` | SCIP | LP、MILP |
| PuLP | CBC | LP、MILP |
| CPMpy | OR-Tools CP-SAT | 约束规划：整数与布尔变量、全局约束、可满足性问题 |
| CVXPY | Clarabel | 连续凸优化：LP、凸二次规划、二阶锥等 |
| PySCIPOpt | SCIP 原生接口 | 混合整数线性/非线性约束 |
| CasADi | Ipopt | 连续光滑非线性问题，返回局部解 |
| coptpy | COPT | LP、MILP、凸二次/锥优化；无许可证时仅限小规模非商业使用 |
| CVXPY / OSQP | OSQP | 连续凸二次规划、线性约束 |
| CVXPY / SCS | SCS | 连续凸锥优化，含半正定、指数锥、幂锥 |
| CVXPY / MOSEK | MOSEK | 凸锥、半正定及混合整数锥优化（不含混合整数 SDP）；需要许可证 |

## 架构

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/architecture-zh-dark.svg">
  <img src="docs/assets/architecture-zh-light.svg" alt="LLM4OM 架构：浏览器和命令行经 LangGraph 服务器进入平台图，方法调用 LLM 预设，代码在沙箱容器中求解" width="100%">
</picture>

平台本身很薄。LLM 调用交给 LangChain，图编排、运行、流式推送和历史交给 LangGraph 服务器（内存运行时，无需许可证）。平台只提供代码契约、求解沙箱、步骤记录和工作台。详见[架构](docs/architecture.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [使用指南](docs/user-guide.md) | 工作台、对比、诊断、预设模型、题库、命令行、Python 接口、常见问题 |
| [部署指南](docs/deployment.md) | Docker Compose、HTTPS、多人使用、用量上限、Gurobi、备份、故障排查 |
| [开发指南](CONTRIBUTING.md) | 环境、项目结构、测试、接入新方法、增加代码写法、发布 |
| [架构](docs/architecture.md) | 模块、平台图、方法接口、沙箱和运行记录 |
| [建模方法](docs/methods.md) | 各方法的流程、固定来源、适配差异和真实运行验证 |
| [架构决策](docs/adr/README.md) · [术语](GLOSSARY.md) | 重要取舍和领域术语 |
| [参考资料](docs/references/README.md) | 相关论文、代码和 Benchmark |

## 参与贡献

欢迎提交 Issue 和 Pull Request。开始前请读[开发指南](CONTRIBUTING.md)和[开发规范](CODING_STANDARDS.md)。安全问题请按 [SECURITY](SECURITY.md) 私下报告。

## 引用

在研究中使用 LLM4OM 时，可以引用本仓库（见 [CITATION.cff](CITATION.cff)）：

```bibtex
@software{llm4om,
  author  = {Fang, Ziyang},
  title   = {{LLM4OM}: A Platform for Automated Optimization Modeling with Large Language Models},
  year    = {2026},
  version = {0.41.1},
  url     = {https://github.com/Fangziyang0910/LLM4OM}
}
```

使用其中的某个研究方法时，也请引用原论文。

## 许可

代码采用 [Apache-2.0](LICENSE)。随包分发的第三方提示、代码和数据保留原许可，见 [NOTICE](NOTICE)。LLMOPT 和 ORThought 的上游仓库在固定提交上没有声明许可证，其提示收录在本仓库中仅用于研究。

## 致谢

感谢各研究方法的作者公开代码和提示，感谢 [LangChain](https://github.com/langchain-ai/langchain)、[LangGraph](https://github.com/langchain-ai/langgraph)、[HiGHS](https://highs.dev)、[OR-Tools](https://developers.google.com/optimization)、[CPMpy](https://github.com/CPMpy/cpmpy)、[CVXPY](https://www.cvxpy.org) 等开源项目。
