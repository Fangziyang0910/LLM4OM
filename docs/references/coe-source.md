# CoE 固定源码观察

本文描述 [Chain-of-Experts 固定提交 afb89bf](https://github.com/xzymustbexzy/Chain-of-Experts/tree/afb89bf602690ea621f13a23c42722f20f653a43)。当前平台使用独立提示和可配置模型工厂，差异见[方法说明](../methods.md)。

## 路由与协作

固定实现依次由 conductor 选择专家，共享评论，再由 reducer 生成 Python。专家顺序动态决定，注册表顺序不是固定执行链。

| 角色 | 实际职责 |
|---|---|
| Terminology Interpreter | 从描述中解释难词 |
| Parameter Extractor | 从描述与评论提取变量、约束和目标 |
| Modeling Expert | 生成变量、约束和目标的文本/JSON 声明 |
| Programming Example Provider | 根据公开 code_example 和评论编写代码 |
| Programming Expert | 按 starter 接口落实代码 |
| Modeling Knowledge Supplement Expert | 补充实现意见和代码 |
| Code Reviewer | 根据描述和评论审查代码 |

conductor 接收问题、专家描述、已参与/剩余角色和次数，不接收实际评论正文。它按名称匹配角色，允许重复匹配；无有效结果时随机选择。原实现没有固定该随机来源。

专家的反向提示接收原问题、该专家先前输出和累计反馈，声明归因及 refined_result。声明不等于已经修改最终代码。

## 反思与返回值

启用反思后，源码生成测试输入，检查程序导入/执行，再按逆序向专家归因。下一 trial 会新建评论池，先前反向修订不会完整进入下一轮。

最终返回最后一次 reducer 输出，不是经过独立评分的最优结果。把修订带到下一轮属于可识别变体；当前平台明确采用这一行为。

原始输出是函数代码，不是 build_model 工厂。建模专家可不参与，因此没有保证提供最终数学表述。当前平台 reducer 同时提供表述与工厂，并记录这种适配差异。

## 输入与预算

原入口读取 description 和 code_example。通用公开 starter 与含答案的参考实现必须区分。基准中的测试、参考模型和最优解不能默认变成公开提示输入。

设参与专家数为 k，每轮前向调用为 k 次路由、k 次专家和 1 次 reducer，即 `2k+1`。反思增加测试生成和最多 k 次反向调用。实际供应商重试、token 和超时依赖运行环境，源码本身不能给出完整固定预算。

## 来源与许可

考察的固定树未提供可确认的顶层许可；相关依赖许可不能授予上游代码或提示的复制权。平台的 CoE 移植现在逐字使用上游提示，只用于研究复现；对外分发前需取得作者许可（见 [NOTICE](../../NOTICE)）。

固定提交晚于论文实验，源码观察不能直接归为论文实验条件。代码入口、提示来源、公开输入和实际运行配置分别记录。
