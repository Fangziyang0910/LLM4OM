# S03：方法发现与运行预检

日期：2026-10-09。SDK 0.2.0 的 S03-A／B 实现范围；工作项为 [#3](https://github.com/Fangziyang0910/LLM4OM/issues/3)／[#4](https://github.com/Fangziyang0910/LLM4OM/issues/4)。规范字段见 [插件契约](../plugin-contracts.md)，目标流程见 [DD-03](../design/execution.md#dd-03-插件接入与兼容路径)，完整发布条件见 [验收清单](../acceptance.md)。

## 当前公共入口

```bash
uv sync --locked --extra dev --extra solve
.venv/bin/llm4om plugins list
.venv/bin/llm4om doctor --config examples/specs/solve.yaml
.venv/bin/llm4om doctor --offline --config examples/specs/run.yaml
.venv/bin/llm4om run --problem examples/specs/problem.json --config examples/specs/solve.yaml
```

plugins list 输出 Manifest 和分发包／entry point 来源。doctor 输出 preflight_ok、实际选择的路径、环境版本、预算与字段级原因；失败退出 1。默认不加载 .env、不发 Provider 请求，不创建运行目录。离线计划只准备方法回放，编译／求解为跳过，不要求 solve extra；真实计划检查 Pyomo／HiGHS 和显式 trusted_local。

独立构建／安装及运行见 [工程方法示例](../../examples/plugins/fixture_method/README.md)。不需要改核心或在源目录注册插件。加载可信 Python 插件会执行其 import／describe，属于宿主代码信任；生成模型代码的隔离是另一条流程。

## 当前运行 profile

Manifest 0.2.0 使用 method_profile=`grounded_single_candidate/0.1.0`。这是一条已实现的窄路径，完整目标 Protocol 仍按后续切片扩展。

- entry point 分组为 llm4om.plugins，导出 describe()／create(config) 对象。Manifest kind 当前只接受 method；Registry 键为 (kind, plugin_id)，重复键拒绝。
- plugin_version 当前接受稳定的 major.minor.patch；contract_range 接受 `>=X.Y.Z,<A.B.C` 区间，必须包含核心契约 0.2.0。包版本、插件版本与契约版本分别记录。
- config_schema 使用 Draft 2020-12、自包含结构及本地片段引用。当前拒绝 $id 和非本地 $ref／$dynamicRef，避免配置校验隐式联网。dependencies.python 声明分发包名称；检查存在并保存版本，暂不解释版本范围。
- async run(problem, context, checkpoint=None) 返回 MethodOutcome。当前接受 status=candidate_selected、final_candidate_id=001，以及含 artifact／formulation／structured_ir 的 ModelProposal；引用由核心投影到运行目录。其他选择状态／多候选／checkpoint 尚未接入。
- MethodContext 提供公开 CSV bytes 的只读 data、只读预算上限、原问题 SHA-256 和 LLM Gateway。它没有 oracle、评估器、凭据或任意路径读取接口。Mock Gateway 接受 role／content 文本消息，返回带 call_id／来源的 LLMResponse.text；请求次数在核心计数，不由方法自报。
- 方法与构建器分别负责输出和 Code。实际 IR 必须属于公开问题／revision、匹配数据 hash、处于允许的 LP/MILP 类型范围。模型来源／版本和变体写入候选、环境及共同封装。结构通过不说明原问题语义正确。

核心 run 使用同一个 prepare_run 预检并保存 admission-plan.json 及经私有字段检查的 requested-config.json；失败 admission 同样保留请求方法和参数。最终 bundle 的阶段状态仍表示实际已执行情况，不能把预检通过当作求解完成。SDK 保持同步入口，在专用线程中运行 async 方法，可从已有 event loop 调用。当前不提供并行运行的完整调度保证。

## 预检与错误

方法声明必须匹配当前五元素／grounded profile、产物、后端、Solver、Provider 功能和执行模式；缺失能力不当作支持。allowed_problem_types 缺省为 lp／milp，可显式收窄；运行后再次检查实际 IR 类型。当前 profile 的表示与资源声明固定在已有路径，兼容性不做枚举的笛卡尔积。

未知方法为 unknown_plugin；重复键为 duplicate_plugin；坏 Manifest／工厂为 invalid_plugin_manifest／plugin_load_error；不支持区间为 incompatible_contract；配置、依赖、预算和能力分别给出明确 admission 错误。整个发现环境中出现无效活动方法时，清单和运行均拒绝，不依安装顺序覆盖。

构造缺少依赖为 dependency_missing，其他构造错误为 invalid_config；方法未知异常为 method_error，保存异常类别与文件名／行号／函数组成的脱敏 traceback，不保存异常参数或源码行。插件 Python stdout／stderr 被抑制，CLI 保持 JSON 输出；它不构成对任意可信宿主插件的系统隔离。原存储 OSError 边界、离线回放和真实 HiGHS 保留。

当前提供方为工程 Mock；连通性检查、真实 LLM、其他插件种类、native_code、参数化工厂、token／墙钟的完整限制与容器隔离仍待实现。验证环境、测试、包安装和两路审阅见 [校验记录](../spec-validation.md)。
