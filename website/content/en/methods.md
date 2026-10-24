A modeling method determines how the LLM builds the formulation and code, and when it validates, debugs or searches further. Configure it separately from the LLM preset, library and solver backend.

## Choose by workflow

Start with Direct for a first run. Consider Feedback Repair when you want a post-solve review. Use the table to explore specific mechanisms; it groups workflows rather than ranking accuracy.

| Method | Main workflow | Explicit problem scope |
|---|---|---|
| [Direct](../direct/) | One generation of formulation and code | Determined jointly by prompts, library and backend |
| [Feedback Repair](../feedback-repair/) | Generate, solve, review against the problem and repair | As above |
| [TriVAL](../trival/) | Semantic, formulation and code validation | As above |
| [OptiMUS 0.3](../optimus/) | Extract components, formulate, assemble and debug | LP/MILP |
| [Chain-of-Experts](../coe/) | Sequential expert selection and reduction | LP/MILP |
| [OptiTree](../optitree/) | Type-tree matching, guidance retrieval and code inspection | LP/MILP |
| [OR-LLM-Agent](../or-llm-agent/) | Formulation, code, execution and rechecks | LP/MILP |
| [ORThought](../orthought/) | Reasoning path, formulation, code and execution debugging | Determined jointly by prompts, library and backend |
| [LLMOPT](../llmopt/) | Five-part formulation and self-correction | As above |
| [AutoFormulation](../autoformulation/) | Component tree, MCTS and model ranking | LP/MILP |
| [SAC-Opt](../sac-opt/) | Semantic anchors, backtranslation and selective repair | LP/MILP |
| [BIND](../bind/) | Data structure, full-data binding and execution repair | Determined jointly by prompts, library and backend |
| [OptiMind](../optimind/) | Public type hints and multi-turn feedback | As above |

## Configure and compare

Select a method in Run settings or name it in a Chat Agent request. All 13 built-in methods accept nine libraries, but the library's expression capabilities, the backend's solving capabilities and the method's own scope must all fit the problem.

Deployment presets fix method parameters. Each method page generates its parameter table from current code. The UI, CLI and Python API do not accept per-run parameter changes; actual snapshots are saved with the run. [Method comparison](../method-comparison/) helps inspect behavior while keeping inputs and environment fixed.

## What a research method means here

Ports retain core orchestration, prompts and stopping conditions, with documented code-contract and execution adaptations. SAC-Opt is independently implemented. BIND and OptiMind have explicit public-scope and deployment adaptations. Their individual pages explain these distinctions.

Methods use your configured LLM. Integrating an inference workflow does not automatically deploy a paper's trained model or reproduce its benchmark results. Inspect the actual model, parameters, steps and result for each run.
