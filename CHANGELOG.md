# 更新日志

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。1.0 之前，次版本号变化可能包含不兼容的改动。

## [未发布]

### 修复

- gurobipy 写法的不可行模型现在也列出冲突约束。Gurobi 预求解常把这类模型判为“不可行或无界”；沙箱现在关闭对偶约简后再求解一次，得到确定的状态。沙箱镜像升级为 `llm4om-worker:7`。

### 文档

- 新的 README（中英文）、[使用指南](docs/user-guide.md)、[部署指南](docs/deployment.md)、开发指南、演示动图和截图。
- 增加 CHANGELOG、SECURITY 和 CITATION.cff。

## [0.41.0] - 2026-10-22

### 新增

- 两种建模方法：**LLMOPT**（五要素模型和自我校正）和 **ORThought**（专家建模思路和按错误调试）。
- 两种代码写法：**PuLP**（CBC）和 **CVXPY**（Clarabel，连续凸优化）。
- **多方法对比**：同一问题一次发起最多 12 个运行，并排比较结果、用时和 token。
- **不可行诊断**：模型不可行时列出一组冲突约束（Gurobi IIS 或 CPMpy MUS），只给人看。
- **备注与标签**、`#标签` 搜索和 **Markdown 报告**导出。
- **Excel 导入**：每个工作表转换为一个 CSV 文件。
- **英文界面**，以及浅色、深色主题。
- **Docker Compose 部署**：服务器上只需要 Docker；可选 Caddy 自动 HTTPS。
- **共享部署的用量上限**：每个预设的每日 token 预算、每个客户端地址的每小时运行数。
- Playwright 浏览器测试，在 CI 中运行。

### 修复

- 通过 `http://<IP>` 打开时，多方法对比报错 `crypto.randomUUID is not a function`。
- 复制链接在 HTTP 下失败。
- 运行被每小时上限拒绝后，历史中留下一条显示为“成功”的空运行。
- 对比中途碰到上限时，已启动的运行不显示。

### 移除

- 已被取代的 ADR、上游源码笔记和学生任务文档。

## [0.40.0] - 2026-10-22

### 新增

- **预设模型**：运行只能选择固定的预设。预设固定服务商、地址、密钥、模型和请求参数，只能添加和删除。密钥不出服务器。
- `.env` 的 `LLM4OM_LLM_*` 给出默认预设 `env`。
- `llm4om serve` 默认监听 `0.0.0.0`，供课题组访问。

### 安全

- json-repair 升级到 0.60.1（GHSA-xf7x-x43h-rpqh）。沙箱镜像去掉 pip，`docker run` 只用本地镜像。

## [0.38.0] - 2026-10-22

### 变更

- 平台以 LangChain 和 LangGraph 重建：每个方法是一张 LangGraph 图，运行、流式推送和历史由 LangGraph 服务器承担。
- 工作台用 Tailwind v4 和 shadcn/ui 重新设计：结论卡片、建模过程、解的矩阵视图、版本对比。
- 全部方法参数集中在 `methods/presets.py`。

[未发布]: https://github.com/Fangziyang0910/LLM4OM/compare/5795d5d...HEAD
[0.41.0]: https://github.com/Fangziyang0910/LLM4OM/compare/bd07e9c...5795d5d
[0.40.0]: https://github.com/Fangziyang0910/LLM4OM/compare/272405d...bd07e9c
[0.38.0]: https://github.com/Fangziyang0910/LLM4OM/commit/dc25f67
