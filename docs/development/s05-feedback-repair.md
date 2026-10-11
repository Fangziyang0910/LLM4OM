# S05-C2 公共反馈修正策略

SDK／Worker0.16.0 开发切片，工作项为 [#34](https://github.com/Fangziyang0910/LLM4OM/issues/34)。接口事实来源为 [插件契约第21节](../plugin-contracts.md#21-s05-c2-bounded-feedback-repair-sdk-0160)，方法时序见 [DD-02](../design/modeling-methods.md#dd-02-方法内部生成修正与选择)。真实外部修正已验收；独立审阅仍待完成，完整1.0未完成。2026-10-11独立Standards／Spec审阅通过：五个模块全部PASS-WITH-NOTES，无P1/P2，仅P3打磨项（报告/tmp/llm4om-reviews/s05-group.md）。

## 方法与支持范围

`llm4om.methods.feedback_repair` 是本项目编写的基于提示的工程对照。它复用 Direct 的紧凑输出约定，读取公开诊断，生成有界子候选，并按 `legal-primal-completeness-latest/0.1.0` 选择：合法可信 primal 优先，再比较公开阶段完整性与尝试顺序。它不比较不同模型的自报目标，也不读取隐藏评测材料。

当前本机已验证 grounded LPIR／Pyomo／HiGHS、参数化 Pyomo 工厂／HiGHS 和 native gurobipy 工厂／微型 Gurobi。生成的工厂代码只在既有隔离 Worker 内运行。Code-only 修正保留原 Formulation 引用与生成来源，新 Code 记录本次实际调用；修改变量域、目标、参数或约束需要声明 Formulation 修正并产生新引用。LPIR 本身属于可执行数学表示，其修改声明为 Formulation 阶段。

数学变化记录实际声明的变化章节、约束 ID 增减与丢失的 requirement_ids。丢失已有公开业务需求追踪的候选会被拒绝。声明比较不能证明自然语言需求已完整建模，也不能证明两个模型语义等价；原问题独立检查保持独立。

## 使用

先设置 [配置](../../examples/specs/feedback-repair.yaml)的 Provider URL／模型，并把凭据留在本地 `.env`。当前字段不对 URL／模型字符串执行 shell 展开。

```bash
uv run --locked llm4om doctor --config examples/specs/feedback-repair.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/feedback-repair.yaml --output runs
```

`max_repairs=0` 合法。运行使用共享候选、修正、LLM、Solver 和绝对截止预算。解析失败通过绑定实际 call_id／response hash 的 GenerationFailure 入账，不导出原始 Provider 回复。没有可选候选时保存明确的 `method_exhausted` 终态与已有尝试。合法 infeasible 结果可以保留，不强行删除约束。版本化 checkpoint 区分已开始的请求与新请求；已开始请求只由 Gateway 的既有重放／未知结果规则恢复。

## 当前证据与后续

Python3.12.11完整本机回归333项／799.113秒通过，包含10项修正行为：公开编译反馈、JSON 解析失败、零修正与 LLM 上限、业务约束丢失、Code-only修复与数学变化误标、真实HiGHS／Gurobi、无凭据崩溃恢复与真实不可行性。另补充一个方法pending-request的聚焦检查：未知结果恢复保留预留且不重发，不重复完整回归。干净Python3.11.13 wheel的10项／55.989秒及补充未知请求检查通过；已有候选9项／31.406秒与Provider应用8项／12.830秒回归通过。没有触发 GitHub Actions。

真实修正运行 `d1cfa1fdc21b4ba9b0f58ce06f119fdb` 使用一次受控本机无效JSON回复和一次已授权 `deepseek-v4-pro-0813` 修正。候选002在容器HiGHS得到x_A=3、x_B=2、目标13。账本为2次HTTP请求（本机1／远程付费1）、2候选／1修正／1Solver，合计报告5107 tokens，cost未知。该配置明确是不同角色资源的工程验收，不是两次真实模型生成或论文成绩。

完成后恢复无需凭据，不新增请求。按所选公开变量x_A／x_B与数学表述记录A／B人工检查映射，ProductionChecker用原始CSV复查整数域、非负域、全部容量与利润，通过且原问题目标为13。该检查是选择后的工程检查，不修改冻结benchmark协议，也不产生数据集正确率。原始Provider回复保持私有。

源码／wheel／Worker代码hash一致：`aae1d15c0645875563ba050c4ea677b067f77569bc233f47108ede7e721d4221`；image为 `sha256:697d5aff452ff0d5fa1278d67f425f81ce24e362ff0e2e842a54b20823c1bc1a`。证据、运行、原业务检查与恢复记录在 `/tmp/llm4om-s05c2-evidence/`。

完整平台仍待澄清／派生问题、其余插件维度、批量实验与报告、Web工作台及剩余发布验收。该方法不加载任务专用训练权重，也不声称复现某篇论文的成绩。
2026-10-11 P3 备注：澄清确认后沿用上一候选 feedback 进入修复，与"resume fresh generation"字面表述存在偏差；数据全公开、计费保守、循环双重限额不变，按语义备注保留。
