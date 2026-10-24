OR-Tools provides several native optimization interfaces. The platform has one OR-Tools library setting; code and backend selection determine the native interface.

## Supported paths

| Interface | Typical tasks |
|---|---|
| MPSolver, MathOpt, ModelBuilder | Linear, integer and interface-supported mathematical programming |
| CP-SAT / CpModel | Integer, Boolean, logical and discrete scheduling models |
| Routing | Vehicle routes and visit sequences |
| Original Constraint Solver | Constraint and search models |
| Maximum flow, minimum-cost flow, assignment, knapsack | Their respective graph and combinatorial problems |

## Select it in the platform

Choose OR-Tools and inspect native backend availability. `CP_SAT` selects CP-SAT, `ROUTING` selects Routing, and `HIGHS` can use MathOpt. The default MPSolver reference uses SCIP.

CP-SAT uses integer or Boolean variables rather than continuous decisions. The platform rejects integer models sent to an LP-only backend instead of silently solving a continuous relaxation.

## Return native models

Ordinary mathematical models return the native object. Routing also needs its `RoutingIndexManager`; maximum flow needs source/sink; the original Constraint Solver needs variables and optional objective; knapsack needs values, weights and capacities. Native return structures are documented without adding another interface setting.

## Results and references

Short heuristic Routing results are normally `feasible`; `optimal` is retained only when supported by the native status. Interpret graph-algorithm and satisfaction results using their native objective semantics.

See the official [Python guide](https://developers.google.com/optimization/introduction/python), [CP-SAT](https://developers.google.com/optimization/cp/cp_example), [Routing](https://developers.google.com/optimization/routing/vrp) and [MathOpt](https://developers.google.com/optimization/math_opt) documentation.
