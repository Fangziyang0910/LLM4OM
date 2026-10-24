命令行和 Python 接口执行与服务器相同的建模图。它们适合脚本调用、保存最终状态和集成已有工作流。

## 命令行运行

在已安装依赖并配置模型的仓库中执行：

```bash
uv run llm4om run --file problem.txt --method direct --language pyomo --solver highs --output result.json
```

`problem.txt` 是你的 UTF-8 问题描述。添加附件可重复使用 `--data`：

```bash
uv run llm4om run --file problem.txt --data demand.csv --data costs.json --method bind --language pyomo
```

命令逐步显示过程，最终输出数学模型、代码和求解结果。`--output` 保存最终状态和步骤。用 `--preset` 选择工作区中的模型预设，`--workspace` 指定预设所在工作区。

## 常用选项

| 选项 | 含义 |
|---|---|
| `--problem` / `--file` | 直接问题文本或 UTF-8 文件 |
| `--method` | 方法 ID，如 `direct`、`feedback_repair`、`sac_opt` |
| `--language` | 建模库 ID，如 `pyomo`、`ortools`、`cvxpy` |
| `--solver` | 原生后端 ID；省略时 AUTO |
| `--data` | 输入数据附件，可以重复 |
| `--sandbox local` | 本机子进程执行，不隔离；仅开发使用 |

方法预设参数不能通过单次调用覆盖，实际值见各方法文章。

## Python 调用

```python
from llm4om import run_problem

state = run_problem(
    "工厂生产 A、B，数量为非负整数。利润分别为 3、2。"
    "切割资源约束为 2A+B<=8，加工资源约束为 A+2B<=8，最大化总利润。",
    method="direct",
    language="pyomo",
    solver="highs",
)
if state.get("failure"):
    print(state["failure"])
else:
    print(state["solve"]["objective"])
```

用 `preset=` 选择预设，也可通过 `llm=LLMSettings(...)` 提供模型配置。选择后端不会自动改写库内 API；代码表达与原生模型仍需兼容。
