# OptiMind

固定参考：[microsoft/OptiGuide@419cf7b9eee20b6af036abf15152fa775b20c951/optimind](https://github.com/microsoft/OptiGuide/tree/419cf7b9eee20b6af036abf15152fa775b20c951/optimind)，[论文](https://arxiv.org/abs/2509.22979)。MIT；原提示库、许可证、文件哈希位于 `source/`。

LangGraph：`classify → generate → solve → feedback → generate`。默认一条推理轨迹、最多 5 次生成，温度 0.6、top_p 0.95。成功求解也继续提供反馈，LLM 可以修正模型，或给出不含代码的最终答案后结束。后者保留最后一个已执行的模型和求解结果。

`llm4om:` 适配差异：

- 上游基准提供问题类型标签。平台增加分类节点，只能选择公开库中的类型或空集合；不匹配时仍使用通用建模检查提示。
- 公开 `hints_subset.csv` 只有 **TravelingSalesman** 一类，共六条错误/提示对。此处按原字节随包分发，不补造完整提示库。
- `eval.py` 的系统提示、`eval_utils/utils_general.py` 的通用检查提示和执行工具的反馈指令适配成平台代码契约；求解状态、目标和变量取代脚本打印结果。不向 LLM 提供参考答案或评测分数。
- 采用上游 CLI 默认 `num_majority=1`，未加入多数投票和训练流程。代码缺失且还没有有效执行结果时会继续请求代码，超过上限则失败；不把代码未运行的回复当成完成。
- 库名改为所选接口，保留 MILP 范围。没有下载或部署 OptiMind-SFT 权重；可通过现有 LLM 预设连接另行部署的模型服务。

这里接入的是公开提示和多轮求解反馈流程，不是完整训练模型及未公开提示库的复现。
