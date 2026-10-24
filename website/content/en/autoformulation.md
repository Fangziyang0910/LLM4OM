AutoFormulation searches multiple candidate models. It builds a component tree, uses Monte Carlo Tree Search (MCTS) to explore complete models, and ranks them with pairwise comparisons.

## Workflow

```text
Parameters → decision variables → objective → equalities → inequalities
   Sample, check execution, remove equivalents and rank at each level
                            ↓
              MCTS rollouts → complete-model comparisons → select a solved model
```

Candidate components run check scripts. Equivalence uses LLM grouping or symbolic scripts. Relative comparisons between complete models produce search rewards that propagate through the tree.

Initial solved models form comparison baselines. Later models are compared in both directions against them, with win rates as rewards. UCT balances established high-scoring paths against less-explored paths, and Bradley–Terry ranking selects a solved model at the end.

## How to use it

Select AutoFormulation for LP/MILP research workflows where candidate search is useful to inspect. State parameters, indices, domains and units explicitly so component assembly remains consistent.

Its default budget is substantially larger than single-generation methods and can involve many LLM responses and sandbox checks. Inspect current parameters and deployment limits before a full run. Parameters are changed in deployment code, rather than per run.

## Inspect the search

Review retained and pruned candidates, whether complete models were actually solved, and their rankings. Equivalent candidates may leave a single complete model, without meaningful inter-model comparison. Check the selected model against the problem; LLM ranking does not certify business correctness.

## Source and adaptation

See the [pinned AutoFormulator source](https://github.com/jumpynitro/AutoFormulator/tree/52148018d04de23dc2d36d4281eb6244c2a42ffc) and [ICML 2025 paper](https://proceedings.mlr.press/v267/astorga25a.html). The platform preserves search, uses shared library components and sandboxed scripts, and documents explicit fixes such as the two-candidate comparison direction. Your preset is used rather than automatically reproducing the paper's model and evaluation setup.
