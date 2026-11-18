# TriVAL 移植说明

本目录是 [SCUT-EIPI/TriVAL@380a529](https://github.com/SCUT-EIPI/TriVAL/tree/380a529) 的 LangGraph 实现。上游提示词集中在 `prompts.py`（除下表所列平台适配与示例大括号修正外均保持原样），单张状态图、工具循环与阶段路由集中在 `graph.py`。研究阶段的路由、验证准则和循环上限保持不变，平台补充输入映射与退出状态报告。

## 流程

| 阶段 | 构建 | 验证 | 修订 | 上限 |
|---|---|---|---|---|
| 语义 | `semantic_fact_extractor` 提取事实和歧义，`ambiguity_resolver` 处理歧义 | `semantic_validator` | 按失败项重新提取或重新处理歧义 | 5 次验证 |
| 数学模型 | 参数/索引、变量、约束、目标四个专家并行，`formulation_selector` 选择 | `formulation_validator` | `revise_formulation`（局部）或重新构建 | 5 次验证 |
| 代码 | `code_agent` | `code_executor` → `code_validator` | `code_agent`；若错误归因于数学模型，回到数学模型阶段 | 5 次验证、20 次执行 |

某阶段达到验证上限时，图带着最新产物进入下一阶段。平台直接运行这张图：入口节点 `receive_problem` 把平台的 `problem` 映射为 `problem_description` 并把计数器置零；出口节点 `finish` 汇报仍未通过的验证，保留实际模型、代码和求解结果；`__init__.py` 只定义步骤标题和隐藏的状态键。

## 与上游的差异

| 位置 | 改动 | 类型 |
|---|---|---|
| `graph.py`、`prompts.py` | 合并上游分散的 19 个模块与重复的每节点子图包装：无工具节点直接调用聊天模型，带工具节点直接绑定结构化工具并顺序应用更新；模型由 `runtime.context.llm("trival.<节点>")` 提供 | 适配 |
| `graph.py` | 增加入口节点 `receive_problem` 与出口节点 `finish`：退出前将仍未通过的语义、数学模型或代码验证写入 `failure`；不改变修复路由、循环上限或求解结果 | 适配 |
| `graph.py` 的 `code_executor` | 改为异步，调用平台 `solve()`；`code_executable` 取 `result.executed`，`execution_feedback` 取 `result.feedback()` | 适配 |
| `prompts.py` 的 `code_agent` 提示 | 删除求解器选择和 OR-Tools、CP-SAT、CVXPY 语法段落，改述核心职责；系统提示末尾拼接平台代码契约 | 适配 |
| `graph.py` 的 `code_agent` | 生成代码后清除入口预设的失败标记，避免成功运行携带“未生成代码”的错误 | 避错 |
| `prompts.py` 的 `code_validator` 提示 | 删除“代码是否输出可解释的求解结果”一条 | 适配 |
| `prompts.py` 的 `formulation_validator` 提示 | 将上游普通字符串中遗留的双层大括号 `{{...}}` 示例修正为单层合法 JSON 示例 `{...}` | 避错 |
| 读取模型回复 | `AIMessage.content` 改为 `.text` | 避错 |
| 三阶段验证器 | 通过普通结构化工具收集单一合法验证结果，不再强制 `tool_choice`；使用所选预设的模型及思考参数 | 适配 |

适配类改动让代码在平台沙箱中运行，并支持每个求解器。避错类改动兼容返回分块内容的模型与合法 JSON 示例。两类都不改变 TriVAL 的验证机制。

## 已知限制

- 模型需要支持工具调用；模型、接口和思考参数沿用运行预设，不为 TriVAL 单独覆盖。
- 图在生成代码前结束时（上游的异常停止路径），运行记为失败。
- 阶段验证未通过仍可保留已执行结果；求解器的 `optimal` 状态不覆盖验证失败。
