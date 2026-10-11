# S03-C1：独立文本 Provider 注册

用途：记录SDK／Worker0.18.0的Provider扩展与实际验收范围。工作项为 [#38](https://github.com/Fangziyang0910/LLM4OM/issues/38)。规范见 [插件契约](../plugin-contracts.md#23-s03-c1-installed-text-providers-sdk-0180)；完整发布范围仍由 [开发计划](../implementation-plan.md)与 [验收清单](../acceptance.md)维护。

## 公共行为

`plugins list`与SDK`discover_plugins()`列出已实现的method／llm_provider。内置和独立安装包经过同一Manifest检查，键为(kind,plugin_id)，冲突拒绝。`discover_methods()`保留为方法过滤入口。当前没有为其他种类建立空Registry。

第三方Provider通过llm4om.plugins导出Factory。配置指定其ID后，doctor与run共用预检；文本调用仍由共享Gateway计费与保存。HTTP子进程按已安装Factory选择实际协议和响应decoder，不按第三方ID增加内核分支。[独立示例](../../examples/plugins/fixture_provider/README.md)使用OpenAI-compatible协议；公共测试另安装不同请求与响应格式的Adapter，并检查显式api_version确实到达HTTP服务。

Manifest、entry point、分发包版本及已登记包文件hash进入默认和角色Provider的admission。包文件hash排除.pyc缓存；声明依赖保存实际安装版本。恢复验证身份并复用保存的原始响应；完成run的恢复无需再次读取密钥或发送请求。缺失插件／包文件或身份变化拒绝恢复，原问题、事件与预算记录保持不变。

Provider是可信宿主插件，配置和构造不得自行发送付费请求。当前扩展profile为非流式HTTP文本；继承HTTPTextFactory／HTTPTextProvider，沿用有界独立进程、凭据引用与URL规则。支持新协议不等于已支持tools、图片或流式响应。normalized response必须满足共同文本／usage契约；无法验证的结果保留未知usage与资源预留。

## 验收证据

开发已按公共入口red→green验证清单、独立安装、无付费预检、HTTP→HiGHS、角色路由、恢复、身份变化、版本／配置／依赖错误以及安全诊断。手算生产问题的预期为A3／B2／目标13。最终Provider聚焦10项／32.813s；Gateway26项／19.822s；Messages18项／63.533s；角色路由2项／5.945s；原HTTP应用8项／15.163s均通过。干净Python3.11.13 wheel的Provider10项与Messages错误分类、不同协议→容器HiGHS的补充检查均通过。一次完整本机回归运行353项／904.548s，初次有5个子用例失败，均来自Messages选项与Mock角色的预检错误分类；最终对应Messages18项与角色2项已通过，全部失败用例均已重验。没有第二次运行完整套件；不把初次回归写成全绿。最终干净wheel的Provider10项／32.204s、Messages分类1项／0.502s及自定义协议→容器1项／5.322s通过。

2026-10-11独立Standards／Spec审阅通过：8个注册模块全部PASS／PASS-WITH-NOTES，无P1/P2，仅P3打磨项（报告/tmp/llm4om-reviews/s03-registry-group.md）。其他插件种类、批量报告、Web与完整1.0发布验收继续推进。

真实指定DeepSeek经独立安装的Provider wheel完成run57304364895f4c5fb71da650db55f18b：1次实际请求、7556 reported tokens、cost=null；容器HiGHS得到x_A3／x_B2／目标13。原公开CSV在最终选择后用显式A→x_A／B→x_B映射重算，可行性通过、原目标13。这是工程验收，不是冻结benchmark准确率。完成态在无.env／无凭据环境恢复，ledger不变。

真实pilot使用源码hash7a4991226c59390fd6227bee7bbf63432a200392c3caba0b195795c00f43a6ac、镜像sha256:967aade20d44579762f6f40b489b01a27be5d1ce155d4030e0957230bcf8b302；原wheel与镜像别名0.18.0-provider-pilot保留。此后修复自定义参数转交及Messages错误分类，最终快照单独记录；旧run不使用最终环境静默恢复。没有重复付费调用或触发Actions。

最终源码／wheel／Worker代码hash均为9eba1b3f8164c736f9f33fbb37b6c646299bbe33891f4c078443704074651c65；最终镜像sha256:5381542849425389aeb2e84721139b7dae564d82b0e20a872e57cb32c57eace7。Worker中没有独立Provider包。196个源文件、83个公开run文件和wheel55项的已知密钥检查未发现密钥。
