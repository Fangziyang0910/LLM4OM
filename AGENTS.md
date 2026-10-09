# LLM4OM 工作约定

本仓库已实现 S01 离线、S02-A 严格 LPIR／HiGHS、S02-B 参数化工厂、S03 方法发现与预检、S04-A 容器执行、S05-A 文本 Provider、S07-A NL4Opt 导入／评测；当前能力见 README，切片证据见开发计划。文档完成与功能完成分别记录。

- 开工前阅读 README、GLOSSARY 及相关需求和 ADR；按可演示的纵向切片交付。
- 用户的明确指令优先于这些工程默认值；常规实现选择无需新增审批。
- 方法、LLM、任务数据、产物、建模后端、求解器和评估器通过声明接口协作；不要增加核心插件特例。
- 自动建模按 Formulation／Code 记录，默认五元素表述；方法内部步骤与来源保留，未提供的阶段如实标记。
- 首批优先 OptiMUS／CoE，使用通用外部 LLM；训练类工作的流程适配与专用模型复现分别命名。
- 明确实际支持矩阵。原生代码不能自动声称支持全部求解器。
- 隐藏 oracle 不进入方法 Context、LLM 提示、生成代码环境或公开导出。
- 正确性分层、失败分母和未知资源量按评测协议处理。
- 变更契约／范围同步文档与验收；引入上游实现记录固定提交与差异。
- 使用确定性 fixture 验证工程流程，真实 Provider／Solver 的支持声明必须有真实验收。
- 密钥、运行数据和商业许可证不提交版本控制；当前 private 可见性不自动更改。

修改文件前读 [CODING_STANDARDS.md](CODING_STANDARDS.md)；执行开发、校验或交付时读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## Agent skills

### Issue tracker

工作项与功能规格使用 GitHub Issues。读取或发布工作项时，先读 [issue-tracker.md](docs/agents/issue-tracker.md)。

### Triage labels

使用五种默认 triage 状态。分类或迁移状态时，先读 [triage-labels.md](docs/agents/triage-labels.md)。

### Domain docs

本仓库采用 single-context。探索领域、修改术语或设计时，先读 [domain.md](docs/agents/domain.md)。
