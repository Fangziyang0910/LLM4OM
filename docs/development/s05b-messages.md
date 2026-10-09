# S05-B Messages 实现与验收

状态：SDK／Worker 0.8.0 的本机工程与真实指定模型端到端验证已通过；独立审查和最新恢复修复的集成仍待完成。
规范来源为 [Issue18](https://github.com/Fangziyang0910/LLM4OM/issues/18)、FR-15/16/17、AC-07/08、
[Provider 契约](../plugin-contracts.md#13-s05-b-messages-adapter-sdk-080)和 [S04-B 恢复](s04-resume.md)。
[此前协议探针](s05b-anthropic-research.md)只证明配置服务接受 Messages，不是本 Adapter 的平台验收。

## 使用与实际支持

[完整示例](../../examples/specs/messages.yaml)选择独立 `llm4om.providers.anthropic`，配置模型保持
`deepseek-v4-pro-0813`。示例使用占位 HTTPS 地址；真实验收使用已授权的
`https://api.x5m5x.com/v1` 和项目本地凭据。这里的 Anthropic 指 Messages 协议，不代表 Anthropic 模型权重。
先在本地复制配置并填入端点，再运行：

```bash
llm4om doctor --config /path/to/messages.yaml
llm4om run --problem examples/specs/problem.json --config /path/to/messages.yaml
```

SDK 使用相同 `run_problem(problem, config)`／`resume_run(run)`，不添加新的客户端入口或依赖。
Doctor 不发送 HTTP。普通新运行缺少凭据则 admission 失败；已保存回复恢复和 completed 身份检查
无需 API key，不加载凭据文件。确需新 HTTP 的恢复仍使用原预算，并在发送前加载与校验凭据。
凭据校验先于 Gateway 的 attempt／token 预留落盘。缺少或非法本地凭据不计外部请求，
不会制造 unknown outcome；补回凭据后可按原 run／request_id 继续。两种 HTTP Adapter 共用此规则。

| 能力 | 当前行为 |
|---|---|
| 文本 Messages | POST /messages、版本2023-06-01、x-api-key；system 独立，user／assistant 与文本块有序 |
| 输出 | text 顺序拼接，thinking／redacted_thinking 保留私有；max_tokens 转为 Direct 截断错误 |
| 证据 | 实际 model／message id／request-id／stop_reason、raw body hash、可知 usage；未知值保持 null |
| 资源 | 共同 Gateway 的 retry、并发、预留、取消、deadline 与原子 journal，不另开预算 |
| 不支持 | tools、structured schema、images、streaming；提前拒绝，不 fallback |
| 求解 | Direct 的既有 Formulation／Code profile 与实际 Backend／Solver 矩阵保持，不新增原生兼容声明 |

输入 token 由未缓存输入、cache creation 和 cache read 相加；缓存是输入子集，不再加到 total。
缺任一分量时对应总量未知，仍持有预留。thinking 不说明 reasoning token 数。
没有版本化定价来源，不记录已知成本。HTTP 错误 body、原始回复和认证 header 不进入公开 bundle。
包含凭据回显的成功响应也在私有 archive 写入之前拒绝。

## 工程证据

`tests/test_anthropic.py` 从公共 factory/Gateway、CLI/SDK、实际 loopback HTTP 和 OS rename seam
检查 wire、文本块顺序、usage、身份、capability failure、错误／重试、取消子进程回收、截断与 HiGHS。
独立手算生产 MILP 为 A=3、B=2、目标13。HTTP 响应为合成 fixture，不冒充真实模型生成。
OS 硬退出覆盖成功 private commit 先于 core 回调和 journal 先于 mutable head；无 key 的恢复
仍只发原一次请求，未知 token 保留预留。未知 admission 不重发；私有 mutable、immutable 和
公开 bytes 损坏拒绝。原 OpenAI、S04-B、工厂与原生求解的回归预期保留。

已保存 red→green 记录：注册／真实 wire；数组文本块；doctor 能力诊断；两处硬崩溃后的无凭据回放；
解码后嵌套凭据回显。执行命令、最终本机回归、干净 Python3.11 wheel、包与 source-matched Worker
证据汇总在 `/tmp/llm4om-s05b/implementation-evidence/author-report.md`。

后续 admission 回归在 Direct 保存请求 checkpoint、Gateway 尚未 admission 时硬退出。
缺失、空值、控制字符和非 ASCII 凭据均保持零 attempt／HTTP 子进程／预留与空 trace；
补回合成凭据后，两种协议各以同一请求的一次 loopback HTTP 和一次真实 HiGHS 求解得到目标13。
Gateway 准备期间的取消与 deadline 也在 admission 前拒绝；成功回复与未知请求仍免凭据恢复。
此次修复证据单独保存在 `/tmp/llm4om-s05b/admission-fix-evidence/author-report.md`；
以下220项为修复前基线，不证明新修复。新全量回归留待 parent 独立审查和最新核心修复集成后执行。

SDK、Direct Manifest、默认 Worker 和 lock 同步0.8.0；独立 fixture 方法的依赖范围扩至<0.9.0。
OpenAI 旧 journal 的字段布局保持，完整 run 的精确 SDK／源码身份检查不放宽。
这次交付不迁移已有0.7.0运行，需保留原运行环境恢复。
真实模型验证已完成；独立 Standards／Spec 审查、最新恢复修复集成与交付尚未完成，包未发布。
完整1.0、OptiMUS／CoE、Web、batch、角色路由与结构化功能均未因此完成。

## 最终本机校验

2026-10-09，已将 parent `dc511e3` 的完成状态提交、genesis 恢复与 Gateway.recover 修复纳入源码。
Python3.12.11 一次完整回归220项，437.810秒，全部通过；原回归预期保留，真实 Docker 未跳过。
strict mypy22模块、仓库128文件、参考资料与 diff 检查通过。集成后的干净 Python3.11.13 wheel
执行9项聚焦兼容检查，28.097秒，通过；不重复完整版本矩阵。

同一 wheel 经合成 Messages HTTP 和实际新 Worker 得到 A=3、B=2、目标13，一次请求；
fixture 报告 input40、output18、cache0、total58，reasoning／cost 为 null。completed 恢复不需凭据，容器已删除。
源码、安装 wheel 和 Worker 的 SDK hash 均为 `8646329f40826be4c5124111e54c33d2f6965cfe87b8c68a4e9b84dcf3c68f08`。
镜像 ID 为 `sha256:9b4e9ed77cbf2a0300bcd783254339777c32f2ab14e13413c23c8e4e5f1191d1`。
以上合成响应验证工程行为；实际服务／模型的生成结果单独记录如下。

## 实际服务与模型

2026-10-09，同一源码与镜像经 CLI 发出一次真实 Messages 请求，没有重试。
`deepseek-v4-pro-0813` 返回五元素 Formulation 与 GroundedLPIR，编译后在隔离 Worker 中由 HiGHS 求解。
得到 A=3、B=2、目标13。公开 CSV 的两条资源约束、整数域和利润目标与生成 IR 一致；
独立枚举121个整数点核对可行性和最优值。检查约束的归一化系数、非负整数域及目标系数，不只比较目标值。

服务报告 input1042、output4513、cache0、total5555；reasoning 和费用未知。
一次 LLM 请求、一次 Solver 调用，容器已删除。移除环境凭据、离开项目 .env 所在目录后，
CLI 恢复已完成运行仍成功，没有增加请求／求解次数。公开 bundle 密钥扫描通过，原始回复仍在私有 archive。
实际模型标识匹配请求，原始响应 hash 为 `d64f15edf25886ad0557f721b7bedaf180e9eea79bf701c270f4d927fa0e720e`。
证据位于 `/tmp/llm4om-s05b/real-acceptance/verification.json`，run_id 为 `4a113fd56d764d2782d6d2f21f78854f`。

这验证配置服务的 Messages 兼容性与此微型问题的生成／求解，不是完整 benchmark 成绩。
本次源码基于 `dc511e3`；随后发现的 S04-B 完成记录发布、资源回退等边界修复仍需集成和复审。
