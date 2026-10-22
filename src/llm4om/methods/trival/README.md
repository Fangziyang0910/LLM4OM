# TriVAL 移植说明

本目录是 [SCUT-EIPI/TriVAL@380a529](https://github.com/SCUT-EIPI/TriVAL/tree/380a529) 的 LangGraph 实现。`graph.py`、`state.py`、`schema.py` 和 `nodes/` 从上游复制。图结构、节点、提示和循环上限保持不变。

## 流程

| 阶段 | 构建 | 验证 | 修订 | 上限 |
|---|---|---|---|---|
| 语义 | `semantic_fact_extractor` 提取事实和歧义，`ambiguity_resolver` 处理歧义 | `semantic_validator` | 按失败项重新提取或重新处理歧义 | 5 次验证 |
| 数学模型 | 参数/索引、变量、约束、目标四个专家并行，`formulation_selector` 选择 | `formulation_validator` | `revise_formulation`（局部）或重新构建 | 5 次验证 |
| 代码 | `code_agent` | `code_executor` → `code_validator` | `code_agent`；若错误归因于数学模型，回到数学模型阶段 | 5 次验证、20 次执行 |

某阶段达到验证上限时，图带着最新产物进入下一阶段。平台直接运行这张图：入口节点 `receive_problem` 把平台的 `problem` 映射为 `problem_description` 并把计数器置零；`__init__.py` 只定义步骤标题和隐藏的状态键。

## 与上游的差异

| 位置 | 改动 | 类型 |
|---|---|---|
| 全部节点 | 导入路径改为 `llm4om.methods.trival.*`；模型由 `runtime.context.llm("trival.<节点>")` 提供 | 适配 |
| `graph.py`、`state.py` | 增加入口节点 `receive_problem`，状态增加平台的 `problem` 与 `failure` | 适配 |
| `nodes/code_validation/code_executor.py` | 改为异步，调用平台 `solve()`；`code_executable` 取 `result.executed`，`execution_feedback` 取 `result.feedback()` | 适配 |
| `nodes/code_validation/code_agent.py` | 删除求解器选择和 OR-Tools、CP-SAT、CVXPY 语法段落，改述核心职责；系统提示末尾拼接平台代码契约 | 适配 |
| `nodes/code_validation/code_agent.py` | 生成代码后清除入口预设的失败标记，避免成功运行携带“未生成代码”的错误 | 避错 |
| `nodes/code_validation/code_validator.py` | 删除“代码是否输出可解释的求解结果”一条 | 适配 |
| 读取模型回复 | `messages[-1].content` 改为 `.text` | 避错 |

适配类改动让代码在平台沙箱中运行，并支持每个求解器。避错类改动兼容返回分块内容的模型。两类都不改变 TriVAL 的验证机制。

## 已知限制

- 结构化输出依赖强制 `tool_choice`。DeepSeek 需要关闭思考模式：`{"thinking": {"type": "disabled"}}`。
- 图在生成代码前结束时（上游的异常停止路径），运行记为失败。
