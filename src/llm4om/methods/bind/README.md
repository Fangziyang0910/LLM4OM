# BIND

固定参考：[SprocketLab/Text2Opt-Bench@1dac06be656c41d827ef20987cf8af0b48d382a2](https://github.com/SprocketLab/Text2Opt-Bench/tree/1dac06be656c41d827ef20987cf8af0b48d382a2)，[论文](https://arxiv.org/abs/2605.21751)。MIT，许可证见 `LICENSE.txt`。依据 `main/evaluation/run_eval.py::_run_agentic_openai` 默认 agentic 路径与 `agentic_offload.py` 的 schema offload 设计适配。

LangGraph：`prepare → generate → solve → (feedback → generate)*`，总计最多 3 次生成，温度 0、top_p 1。没有附件时直接按题面建模；有 JSON/CSV 附件时仅将结构、字段名、类型、数组长度/CSV 行数提供给 LLM。完整内容只由生成代码通过 `data` 读取。JSON 的异构、嵌套、非矩形结构会如实描述，CSV 表头和行宽在调用 LLM 前检查。

`llm4om:` 适配差异：

- 用户的完整附件取代基准 `instance_data`，不要求模型创建中间宿主机文件。直接传递原始题面，不从已包含数据预览的 `problem` 字符串中猜测边界。
- 不使用基准专有题面模板、已知最优值或参考模型行列数。代码成功执行且求解器返回状态即可结束；真实不可行不会强制触发改模。执行或回复格式错误用原对话历史修正。
- 采用通用、无数据值的 schema 提示；原版 schema 可以展示标量值和基准字段注释，这里要求题面说明字段语义，代码读取标量值。
- 原代码-only 输出改为数学模型与 `build_model(data)`；生成接口按所选代码写法切换。
- 只支持结构化 JSON/CSV 附件，Excel 通过现有前端转换为 CSV。没有引入上游非默认的两阶段提取、self-review 或参考答案评分路径。

这解决附件数据抄写与截断问题；它不证明生成模型与题意一致，也不隐藏求解反馈中合理出现的目标值和变量取值。
