# Method selection

Use the method requested by the user. The CLI executes each method's existing LangGraph graph, prompts, parsers, tool loops, and stopping rules. Read `llm4om methods` for installed IDs, fixed parameters, sources, and scope. Third-party method sources and adaptations remain maintained in the repository's `docs/methods.md`.

| CLI ID | Preserved workflow | Scope |
|---|---|---|
| `direct` | Generate formulation and code, then execute the final code. | General; default. |
| `feedback_repair` | Generate, execute, review semantics, and repair format, execution, or modeling defects. | General. |
| `trival` | Semantic validation, parallel formulation experts and selection, formulation validation, code tools, execution, and validation with backtracking. | General. |
| `optimus` | Extract components, check constraints, formulate clauses, generate clause code, assemble, execute, and debug. | LP/MILP. |
| `coe` | Conductor-selected experts, comment pool, reducer, and the method's optional reflection path. | LP/MILP. |
| `optitree` | Follow the problem-type tree, retrieve a thought template, reason, execute, and inspect failures. | LP/MILP. |
| `or_llm_agent` | Mathematical model, code generation, conversation-based fixes, and infeasibility or model-recheck recovery. | LP/MILP. |
| `orthought` | Expert-guided solution path, formulation, code, execution, and debugging. | General. |
| `llmopt` | Five-element formulation, code, execution, and self-correction routed to the rejected stage. | General. |
| `autoformulation` | Candidate generation, executable checks, equivalence filtering, ranking, UCT rollouts, pairwise voting, and final selection. | LP/MILP; expensive search. |
| `sac_opt` | Semantic anchors, component checks, code backtranslation, comparison, selective constraint repair, and execution feedback. | LP/MILP. |
| `bind` | Data-schema prompts, full attachment access in code, generation, execution, and feedback repair. | General. |
| `optimind` | Problem-class hints, generation, execution, reflection, and bounded iteration. | General; uses the published hint bank. |

The modeling library is a separate choice: `pyomo`, `gurobipy`, `ortools`, `cpmpy`, `pulp`, `cvxpy`, `pyscipopt`, `casadi`, or `coptpy`. A method's problem scope does not expand because another library is selected. The target library and backend must support the required variable domains and problem class.

`llm4om target --language LIBRARY --solver BACKEND` prints the maintained build contract and native references. Internal API selection remains in the generated code; a backend is an optional native engine/plugin identifier, not another modeling library. `llm4om backends` reports the actual worker's available engines and interfaces.
