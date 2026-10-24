# 0017: Host-model skills reuse method graphs and local solver execution

Status: Accepted

## Context

Users want to model with the current Codex or Claude Code model, without configuring another LLM API or deploying the Web platform. Copying the methods into prompt-only summaries would lose search, voting, tool state, selective repair, and stopping rules. The existing `Context` already separates model calls from solver execution.

## Decision

Provide one portable `llm4om` skill. The current coding agent answers each method task. A LangChain `BaseChatModel` adapter emits native LangGraph interrupts instead of calling a model provider. The existing method graphs continue to own orchestration, prompts, parsing, tools, and stopping conditions.

`host start/resume/status` runs locally with native SQLite checkpoints and `task` boundaries around model requests, solves, and helper scripts. Small local execution records retain actual results, counts, and steps across CLI processes. Progress callbacks use a separate SQLite database to avoid blocking the async checkpointer's transaction. Session locking uses SQLite and is released on process exit.

The original Web/API graph remains unchanged in purpose and keeps its coarse checkpoint policy. Host sessions checkpoint method internals because each model answer requires a resumable handoff. Their extra storage cost is necessary for preserving complex method flows. OptiMUS propagates native graph control exceptions through its existing parsing retry loops.

The base package contains method execution and solver tools. Provider clients and Web dependencies are optional extras. The Web Docker image explicitly installs its extra. The skill does not install or launch another chat agent, request platform credentials, or call `llm4om run`.

## Consequences

All existing methods and code targets are reused. `Sandbox` and the worker retain solver semantics and isolation. Standalone solve, contract, method, and backend commands need no LLM. Artifact steps use the same callback in both modes.

The host controls its own model, temperature, context isolation, and token accounting. Original method sampling settings are task metadata, not enforceable host settings; token usage is unknown. Control-flow preservation does not imply identical API sampling or experimental results. An operation killed before its result is recorded may need to run again.
