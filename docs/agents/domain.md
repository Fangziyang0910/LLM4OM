# Domain docs

## Before exploring

先读根目录 [GLOSSARY.md](../../GLOSSARY.md)。进入具体建模、执行或评测设计前，再读 `docs/adr/` 中相关决策。

未提供的领域文档可以跳过，继续工作；在真正确定术语或作出架构取舍时再补充。

## Layout

Single-context：一个根目录 GLOSSARY 和一个 `docs/adr/`。当前没有多包或多领域上下文，保持这一布局。

领域定义只在 GLOSSARY 维护。接口字段和类型标识使用 [插件契约](../plugin-contracts.md)。

## Vocabulary and decisions

issue、规格、测试和设计使用 glossary 的规范词。发现新概念时，先判断它是否属于领域，再按 domain-modeling 更新。

glossary 写一到两句定义与必要的 `_Avoid_`，配置、实现细节和待办归到对应文档。

ADR 使用顺序编号与短标题，以一至三句记录背景、选择与原因。仅为难逆转、容易误解且存在真实取舍的决定新增 ADR。

与既有 ADR 冲突的提议指出对应 ADR 和新的证据；已接受决定的修改保持可追溯。
