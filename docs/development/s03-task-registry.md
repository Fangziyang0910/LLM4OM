# S03-C2：独立 Task／Evaluator 注册

用途：记录SDK／Worker0.19.0的benchmark扩展与验收范围。工作项为 [#40](https://github.com/Fangziyang0910/LLM4OM/issues/40)。规范见 [插件契约](../plugin-contracts.md#24-s03-c2-installed-task-and-evaluator-sdk-0190)；完整发布范围由 [开发计划](../implementation-plan.md)与 [验收清单](../acceptance.md)维护。

## 当前行为

共同Registry支持method、llm_provider、task_adapter、evaluator。TaskAdapter拥有import_source、iter_cases、load_case；Evaluator拥有evaluate。开发者通过独立安装包接入，不修改核心的适配器ID分支。[工程示例](../../examples/plugins/fixture_task/README.md)保存原始公开生产问题及CSV，私有数值材料另存；它只比较候选自报目标，不提供一般语义证明。

```bash
llm4om plugins list
llm4om doctor --task-config /path/to/import.json
llm4om import --config /path/to/import.json --output /path/to/snapshot
llm4om run --problem /path/to/snapshot/public/problem.json --config examples/specs/solve.yaml
llm4om evaluate --manifest /path/to/snapshot/manifest.json --case-id CASE_ID --run runs/RUN_ID --output evaluation.json
```

doctor仅验证注册组合、配置、依赖和协议，不读取隐藏原始材料或创建snapshot。import在独立staging中完成投影与检查后才发布；源数据适用范围、清洗／资格和参考条件仍由相应Adapter维护。adapter_config与evaluation配置在导入时冻结，原始 source 配置字段保持独立。

privileged manifest记录Task／Evaluator的Manifest、包来源／版本／文件hash、依赖版本、配置及SDK源码身份；private/import-seal.json绑定最终manifest字节。改变配置、协议、包或导入环境后不能按原snapshot静默评估。public/及MethodContext不包含这些隐藏材料。旧格式内置snapshot保持只读，评估明确标为legacy_unbound，保存当前实际评分器身份，不冒充具有新绑定。

公开评估结果校验case／manifest及实际run绑定、冻结分母、计数／状态一致性、有限数值、声明证据与字段。导入清点匹配实际选中的唯一案例；不能虚增样本数。私有引用和oracle字段拒绝；原run的公开诊断引用核对实际hash后保留。评估器异常保存安全错误并保留事前eligible分母；不能通过失败后排除样本提高指标。

## 本机验收

开发按CLI／Task／Evaluation／OS／真实Solver接口逐步red→green。已验证独立wheel安装、导入→HiGHS目标13→评分、无oracle导出、包／配置变化拒绝、协议／依赖预检、错误分母和旧格式读取。最终隔离源码11项／59.558s、干净Python3.11 wheel11项／53.916s及容器流程1项／6.277s通过。独立检查器15项／70.020s、NL4Opt5项／9.018s与NLP4LP5项／9.012s通过；MAMO组合检查中的受影响数值用例因源码变更失效，最终单独重验1项／27.549s通过。一次完整本机回归在原稳定快照运行362项／976.592s并全部通过。最终审查补充的run绑定、计数一致性和清点规则以源码／wheel／容器聚焦测试单独验证；没有第二次运行整套回归。不增加本次变更不需要的付费模型调用，不触发Actions。

2026-10-11独立Standards／Spec审阅通过：8个注册模块全部PASS／PASS-WITH-NOTES，无P1/P2，仅P3打磨项（报告/tmp/llm4om-reviews/s03-registry-group.md）。其余插件种类、批量报告、Web与完整1.0继续推进。

本机保存的独立Task／Evaluator运行1d7cee11f27b49a6987d5cde94d6a646经Mock生成、容器HiGHS真实求得A3／B2／13，候选自报目标匹配1/1，原始CSV另作独立业务检查通过；没有真实模型准确率声明或额外付费调用。该pilot的源码0847b1fb4e055fe6b72ec94cf14ea2478af53dc2a74fd6beba7a9310cc68d33a与镜像3248c1411ba92813fefe75fefbbe98ee9d4efa6a4815f56979420cd6f840c87c分别保留为原wheel及0.19.0-task-pilot。

最终代码已补齐实际run绑定、状态／计数一致性和案例清点，源码／wheel／Worker hash24fa3ba72dd8ddf8af3c010dcfcabb2fd0c717e0dd801d22579a3b622bd6dacf一致，镜像34dbfc10259ef0c4338f80a29d0bd888ca9cabbfdf5522fa80076c57869ab9ad。Worker不含独立Task包；源码202文件与wheel56项的已知密钥检查未发现密钥。旧pilot不使用最终环境静默恢复。

旧0.18.0 wheel实际创建的NL4Opt工程快照可按原字节只读评估，结果标为legacy_unbound；缺失run仍记录错误与零eligible，不伪造成功。
2026-10-11 P3 处置：`evaluation_error` 的指标块改为按 `evidence_levels` 门控（原先无条件写 `objective_match: error`）；`_prepare_task` 对传入 settings 的消费语义已在 docstring 说明。load 路径 adapter 身份仍依赖冻结清单 seal＋导入期断言保证，属防御纵深备注（不可利用，不改行为）。
