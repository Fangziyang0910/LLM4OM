# Method selection

Use the method requested by the user. The runtime executes each method's existing LangGraph graph, prompts, parsers, tool loops, and stopping rules. Use the runner’s `methods` command for installed IDs, fixed parameters, sources, and scope. Third-party method sources and adaptations remain maintained in the repository's `docs/methods.md`.

| Method ID | Preserved workflow | Scope |
|---|---|---|
| `direct` | Generate formulation and code, then execute the final code. | General; default baseline. |
| `or_llm_agent` | Mathematical model, code generation, conversation-based fixes, and infeasibility or model-recheck recovery. | LP/MILP. |
| `llmopt` | Five-element formulation, code, execution, and self-correction routed to the rejected stage. | General. |
| `trival` | Semantic validation, parallel formulation experts and selection, formulation validation, code tools, execution, and validation with backtracking. | General. |
| `bind` | Data-schema prompts, full attachment access in code, generation, execution, and feedback repair. | General; large CSV/JSON attachments. |
| `autoco` | Compact 4-tuple modeling, feature knowledge graph + sandbox pilot selection, and built-in 12-family metaheuristic/evolutionary pool. | Multi-objective Pareto, black-box, hard nonlinear/combinatorial (no external library). |
| `optitree` | Follow the problem-type tree, retrieve a thought template, reason, execute, and inspect failures. | LP/MILP. |
| `coe` | Conductor-selected experts, comment pool, reducer, and the method's optional reflection path. | LP/MILP. |
| `optimus` | Extract components, check constraints, formulate clauses, generate clause code, assemble, execute, and debug. | LP/MILP. |

The modeling library is a separate choice (for the 8 exact methods): `pyomo`, `ortools`, `cvxpy`, `pyscipopt`, or `casadi`. A method's problem scope does not expand because another library is selected. The target library and backend must support the required variable domains and problem class.

`target --language LIBRARY --solver BACKEND` prints the maintained build contract and native references. Internal API selection remains in the generated code; a backend is an optional native engine/plugin identifier, not another modeling library. `backends` reports the actual worker's available engines and interfaces.
