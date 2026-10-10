# S03-C3a：独立 Compiler 注册

用途：记录SDK／Worker0.20.0的编译器扩展与本机验收。工作项为 [#42](https://github.com/Fangziyang0910/LLM4OM/issues/42)。字段由 [插件契约](../plugin-contracts.md#25-s03-c3a-installed-compilers-sdk-0200)维护；完整1.0范围见 [开发计划](../implementation-plan.md)。

## 当前行为

共同Registry增加compiler种类。内置和独立安装的工厂使用describe／create(config)，实际编译接口为compile(ir,target_backend)→CompiledCode。当前profile为grounded_lpir_pyomo/0.1.0，明确支持IR0.1.0和Pyomo。配置、契约、声明依赖、目标及问题类型在方法生成前校验；未知组合拒绝。

独立 [工程示例](../../examples/plugins/fixture_compiler/README.md)通过AST改变实际源码格式，并使用配置marker；它复用原数学转换，不能据此宣称新增建模算法。Code／Build记录实际编译器版本、配置hash、源IR、符号映射及包来源。编译器接收公开IR的副本；源码大小、Python语法和映射范围在执行前验证，异常只保存安全类型／位置。

Worker重新选择相同编译器及配置，再编译并核对源码hash和完整符号映射。容器admission先检查Worker包身份，缺少或不同的编译器不消耗生成和求解预算。构建工具接受显式可信wheel，安装在不可变镜像中。宿主恢复核对完整安装身份；跨宿主／Worker核对包代码与资源内容、Manifest、配置和依赖，排除安装器元数据差异。SDK版本／源码与Worker镜像身份仍按原规则冻结。

五元素自由文本不直接进入确定性编译。参数化工厂和native Code保留方法生成来源；该切片没有扩展它们的Backend／Solver支持矩阵。

## 本机验收

已通过编译器聚焦8项／15.299s及公共Worker源码／映射漂移检查1项／0.556s。独立wheel实际通过CLI与owned Worker求得MILP目标13及连续LP目标40/3。能力不匹配测试先失败，补齐编译器问题类型校验后通过。原稳定快照完成一次完整本机回归373项／939.184s，出现3个测试方法中的4个失败子例；均为预检兼容问题，已在独立工作树修复并通过源码／wheel聚焦重验。其余完整回归用例通过，没有第二次运行整套回归。GitHub Actions没有触发；该切片不需要额外付费模型请求。

原稳定快照自定义镜像的2项真实HiGHS测试／12.025s及干净Python3.11 wheel的9项／24.982s通过。持久运行dfee5a6667274b99b3f4d975b933165d通过独立Compiler→容器HiGHS求得A3／B2／13；原始公开CSV的独立业务检查通过，完成后恢复不增加预算。生成使用Mock，不声明真实模型准确率。

该pilot与原回归快照的源码／wheel／Worker代码hash均为a7dda637b6b97495d04b3fc522f1d1a7581f002dac1646763c542da20f7da698。默认镜像80ad42dc81516309c98acbcbfa6fd2b05dd91d8ae23e3fcefb0292da04995285；含独立编译器镜像36eeeb20d505f9aee9d5c12307f3eb5129f74e95d55bd482f573beaff8bfd6d8。原wheel及镜像已按compiler-pilot保留。仓库208文件、wheel57项及公开pilot80文件的已知密钥检查未发现密钥。

预检修复保留executor_unavailable与compiler_unavailable的区别，损坏error字段不终止CLI。预检元数据采用至少64KiB有界输出，候选仍按配置限额执行。源码的损坏响应／错误求解响应／512字节限额分别1项通过；对应干净Python3.11 wheel分别1项／0.489s、1项／7.001s和1项／5.574s通过。修复后compiler源码9项／20.905s通过，最终wheel9项／20.796s通过。修复后的源码／wheel／Worker代码hash为c9fde82e2830cda2428c0649148824c7d324004e56dd5ba8bac1dabccb374969；新标签镜像9eed9a7dab1269d572e2e1ef4dcd905f247e4f8beb4b37b2bc33eb418ed2c20c与含插件镜像9ce55bb6904412c06e1c3edf4e44428b6ba8b2ad81449c7b3f4f914a58544fc2已构建。原回归结束后，默认标签更新为修复后的镜像；旧pilot按原wheel／镜像保存，不静默迁移。

独立Standards／Spec审阅待CLI用量条件恢复；自查不计为独立审阅，PR保留draft。其他插件种类、批量实验、Web与完整1.0继续推进。

最终含插件镜像的MILP／LP两项／11.509s通过。下一步Backend／Solver的共同接口与实际Worker路径由 [#43](https://github.com/Fangziyang0910/LLM4OM/issues/43)跟踪。
