命令行和Python调用与工作台相同的建模图，适合批处理、保存运行状态和接入已有程序。先按[安装指南](../installation/)准备环境与Worker，再选择模型预设。

## 命令行运行一题

将[快速开始](../quickstart/)的生产题保存为UTF-8文本 `problem.txt`。使用工作区中已有预设运行：

```bash
uv run llm4om run --file problem.txt --workspace runs/web --method direct --language pyomo --solver highs --output result.json
```

终端显示阶段和最终模型、代码、结果。`result.json` 保存最终状态与步骤，便于后续脚本读取。

## 添加附件与选择预设

```bash
uv run llm4om run --file problem.txt --data production.json --method bind --language pyomo --workspace runs/web --preset your-preset-id --output result.json
```

`--data` 可重复使用，代码通过附件原文件名读取文本。`--preset` 使用工作区中保存的ID；省略时选择默认预设。数据样例可从[附件指南](../attachments/)下载。

| 选项 | 用途 |
|---|---|
| `--problem` / `--file` | 直接输入题目或读取文件 |
| `--method` | 方法ID，如feedback_repair、sac_opt |
| `--language` | 库ID，如pyomo、ortools、cvxpy |
| `--solver` | 原生后端ID，省略为AUTO |
| `--workspace` / `--preset` | 预设所在工作区与预设ID |
| `--output` | 保存最终JSON状态 |

## Python最小完整调用

```python
from llm4om import run_problem

state = run_problem(
    "生产A、B，均为非负整数。利润分别为3、2。"
    "切割约束2A+B<=8，装配约束A+2B<=8，最大化总利润。",
    method="direct",
    language="pyomo",
    solver="highs",
    workspace="runs/web",
    explain=True,
    locale="zh",
)
print(state.get("failure") or state.get("solve"))
```

返回状态包含问题、配置、公式、代码、求解与步骤。`explain=True`生成业务解读，`locale`选择解读语言。

## 在Python中传入完整数据

```python
from pathlib import Path
from llm4om import run_problem

state = run_problem(
    "按production.json确定非负整数产量并最大化利润。"
    "usage为资源×产品的小时/件矩阵，capacity为可用小时。",
    method="bind",
    language="pyomo",
    data={"production.json": Path("production.json").read_text(encoding="utf-8")},
    workspace="runs/web",
)
print(state.get("solve", {}).get("variables"))
```

`data`是文件名到文本的字典，与页面附件采用同一输入形式。

## 显式提供模型配置

通过 `llm=LLMSettings(...)`可在脚本中提供服务配置。密钥从环境变量读取，完整参数定义见[LLMSettings源码](https://github.com/Fangziyang0910/LLM4OM/blob/main/src/llm4om/llm.py)。

流程参数来自各方法预设。要集成异步应用，可使用底层 `run` 与 `Resources`，接口入口见[公开Python模块](https://github.com/Fangziyang0910/LLM4OM/blob/main/src/llm4om/__init__.py)。

## 处理运行状态

先读取 `failure` 和 `solve.status`，再根据实际结果进入后续数据处理。步骤记录可定位模型调用、执行与验证反馈。需要保留可浏览历史时，工作台服务提供固定运行链接、标签、备注和导出，见[历史记录](../history/)。
