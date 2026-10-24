OR-LLM-Agent writes a mathematical formulation before generating code and repairing execution errors. After the main round, it performs an infeasibility check or model recheck.

## Workflow

```text
Formulation → code → execution → error repair
            → result-dependent infeasibility check or recheck
```

The main round, infeasibility check and recheck use their separate `attempts` preset budgets rather than an unbounded retry loop.

## How to use it

Select OR-LLM-Agent for LP/MILP problems when you want to inspect a standalone formulation followed by execution feedback and rechecks. Agent here names the modeling workflow. The website's [Chat Agent](../chat-agent/) is the conversational entry point that can call different methods.

## Match final code to execution

Repair conversations use a copy, with only the final code returned to the main conversation. Upstream may leave its last repair unexecuted. The platform preserves such code as an intermediate artifact and associates final numerical results with the last actually executed code. Check versions together with execution steps.

## Source and adaptation

The core follows the [pinned OR-LLM-Agent source](https://github.com/bwz96sco/or_llm_agent/tree/5dccdaab89ab91c3cb28066fe849423dc124d287). Prompts and recovery routes are retained, with Gurobi-specific code requests replaced by the selected library contract and execution moved to the sandbox.
