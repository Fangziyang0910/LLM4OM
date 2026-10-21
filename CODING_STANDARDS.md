# 开发规范

工作步骤见 [CONTRIBUTING](CONTRIBUTING.md)，术语见 [GLOSSARY](GLOSSARY.md)。

## 设计

- 不重复造轮子。LLM 调用、重试、回调和图编排使用 LangChain 与 LangGraph；Web 使用 FastAPI。
- 先用最简单的实现。只为实际出现的问题增加抽象；仅转发、没有独立职责的层直接删除。
- 平台核心只管建模、求解和记录。方法内部的阶段、状态和策略留在方法里。
- 方法提示不写求解器 API；代码提示拼接 `context.target.prompt`。
- 研究方法保留核心编排和提示。改动只做适配或避错，并记录在 [建模方法](docs/methods.md)。改变机制的改动先与维护者确认。
- 密钥不进入运行记录、方法输入或生成代码环境。

## 文字

文档约按 ASD-STE100 原则的 80% 整理：短句、具体动词、明确主语；一段一个主题，先写结论；一个概念一个词；复杂比较用表格。用户界面使用“数学模型”“求解代码”“求解结果”等名称。

每项内容只在一个地方维护：

| 内容 | 位置 |
|---|---|
| 功能与使用 | README |
| 模块与接口 | `docs/architecture.md` |
| 方法、来源与适配差异 | `docs/methods.md` |
| 术语 | GLOSSARY |
| 架构取舍 | `docs/adr/` |
| 论文元数据 | `docs/references/catalog.json` |

## 文件

- UTF-8、LF、结尾换行；遵循 `.editorconfig`。
- Python 四空格缩进、`snake_case` 名称、`PascalCase` 类型；公开函数标注类型。
- 注释只解释代码无法直接说明的原因。
- 随包分发的上游文件（`methods/optitree/source/`、`server/examples_data/`）保留原始字节、许可和来源清单。

## 测试

测试通过公共入口验证行为：方法用 `tests/conftest.py` 中的脚本化聊天模型，求解用本机 Worker。确定性测试证明流程正确；真实 LLM 和求解器的支持需要真实运行证明，两者分别报告。
