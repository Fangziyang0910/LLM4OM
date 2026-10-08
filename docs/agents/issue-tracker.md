# Issue tracker: GitHub

仓库：[Fangziyang0910/LLM4OM](https://github.com/Fangziyang0910/LLM4OM)。工作项和功能规格位于 GitHub Issues，使用 `gh` 操作。发布基线与研究设计由仓库文档维护；issue 引用对应基线，不复制完整文档。

## Operations

```bash
gh issue view NUMBER --repo Fangziyang0910/LLM4OM --comments
gh issue list --repo Fangziyang0910/LLM4OM --state open --json number,title,body,labels,assignees
gh issue create --repo Fangziyang0910/LLM4OM --title TITLE --body-file BODY_FILE
gh issue comment NUMBER --repo Fangziyang0910/LLM4OM --body-file BODY_FILE
gh issue edit NUMBER --repo Fangziyang0910/LLM4OM --add-label LABEL --remove-label OLD_LABEL
gh issue close NUMBER --repo Fangziyang0910/LLM4OM
```

读取 issue 时同时读取评论和标签。多行正文通过文件传入，保持原始换行；占位符在实际调用前替换。

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub issue 和 PR 共用编号；明确读取 `#NUMBER` 时先尝试 `gh pr view NUMBER`，不是 PR 再读取 issue。上述标志只控制 triage 的发现范围，不限制明确指定的 PR。

## Specs and slices

功能规格使用 Problem Statement、Solution、User Stories、Implementation Decisions、Testing Decisions、Out of Scope、Further Notes。开发切片使用 What to build、Acceptance criteria、Blocked by，并关联 parent spec。

用领域语言和可观察行为描述工作项。具体路径和代码由实现决定；prototype 验证过的决策片段可随规格保存，并标明出处。

已讨论并确认的完整规格使用 `ready-for-agent`；待评估或澄清的请求使用 `needs-triage` 或 `needs-info`。label 映射见 [triage-labels.md](triage-labels.md)。

## Dependencies and frontier

优先使用 GitHub native issue dependencies，引用阻塞 issue 的数据库 ID。不可用时在正文声明 `Blocked by: #NUMBER`。sub-issues 不可用时，parent 中维护 task list，child 声明 `Part of #NUMBER`。

只领取阻塞项均已完成且未被领取的工作。`wayfinder` 使用单个 map issue 和 child issues；map 标签为 `wayfinder:map`，child 类型标签为 `wayfinder:research/prototype/grilling/task`。这些标签仅在实际使用该技能时创建。

创建 issue、发布评论、关闭或分派工作，遵循当前用户请求或显式调用的技能。本地配置整理本身不产生远程写入。

## Authentication

`gh` 需要有效登录。认证失败时报告具体操作与错误，保留本地结果；保持当前 tracker 选择和真实 issue 身份。
