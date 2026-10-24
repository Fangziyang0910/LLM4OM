PuLP builds linear and mixed-integer models with algebraic expressions. It suits LP/MILP problems described through costs, quantities and resource constraints.

## Supported expression

The platform recognizes `LpProblem`, including row-oriented objectives and constraints and column-oriented modeling through `LpConstraintVar`. These remain one library choice.

Variables can be continuous, integer or binary. Objectives and constraints stay linear; do not directly multiply two decision variables. Use an appropriate formulation or another library for nonlinear relationships rather than omitting them.

## Select it in the platform

Choose PuLP. The default backend is CBC, with native ID `PULP_CBC_CMD`. The platform uses native listSolvers/getSolver, so available backends are not restricted to CBC. Python, command-line and shared-library interfaces retain their own IDs.

## Code and checks

`build_model(data)` returns `LpProblem` without calling `solve()`. In row-oriented modeling, the first expression added without a comparison becomes the objective. Use unique, stable constraint names for interpretation and checking.

Review integer categories, bounds, objective direction and units. Statuses come from the native backend; missing dependencies, incompatibility or license failures retain their actual reasons.

## Official references

See the [PuLP modeling API](https://coin-or.github.io/pulp/technical/pulp.html) and [backend API](https://coin-or.github.io/pulp/technical/solvers.html). Use APIs supported by the deployment's locked version and recheck actual backends after dependency upgrades.
