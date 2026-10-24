CPMpy expresses discrete decisions with finite-domain integers, Booleans and global constraints. Arrays fit employees, dates, machines and tasks; `AllDifferent`, `Element` and `Cumulative` express common rules directly.

## How global constraints simplify a model

Three vehicles each serve one of three stores, with exactly one vehicle per store. Let `destination[i]` identify vehicle i's store. `AllDifferent(destination)` expresses distinct destinations; costs are indexed from each vehicle's cost row.

Each variable has domain 0 through 2, with each value identifying a store. CPMpy passes these finite-domain expressions to a native backend.

## Complete assignment model

```python
import cpmpy as cp

def build_model(data):
    cost = cp.cpm_array([[4, 8, 6], [7, 3, 9], [5, 6, 2]])
    destination = cp.intvar(0, 2, shape=3, name="destination")
    model = cp.Model(cp.AllDifferent(destination))
    model.minimize(sum(cost[i, destination[i]] for i in range(3)))
    return model
```

The default backend is OR-Tools CP-SAT. The optimum assigns vehicles 0, 1 and 2 to stores 0, 1 and 2, for `4+3+2=9`. Adding `destination[1] != 1` raises the optimum to 17.

## Expressions, compilation and solving

```mermaid
flowchart LR
  Rules["Integer domains, logic and global constraints"] --> Model["CPMpy Model"]
  Model --> Native["Native backend transformation"]
  Native --> Solver["CP / SAT / SMT / MIP paths"]
  Solver --> Result["Assignments and status"]
```

The platform accepts `cp.Model` and native SolverInterface. Backends come from `SolverLookup` and installed subsolvers. `ortools` is the default; run settings show the available alternatives.

## Common rule patterns

| Business rule | Expression pattern |
|---|---|
| Tasks use different machines | AllDifferent |
| Selected index determines a cost | Variable array indexing / Element expressions |
| A requires B | `a.implies(b)` |
| Tasks share limited capacity | Cumulative |
| Find any assignment satisfying rules | Model without an objective |

Integer variables have finite bounds; Booleans represent selections. Consistent integer units keep quantities and logical relationships clear.

## Conflict analysis and results

The platform's CPMpy path supports MUS conflict evidence, connecting inconsistent constraints to requirements. Clear names and indices help in [infeasibility analysis](../conflicts/).

Interpret `destination[0]` using the store-number mapping in the formulation. Export complete values, query a vehicle in plan conversation, or revise available destinations.

## Selection and references

Start here for finite domains, logic, exclusions and global constraints. See [Pyomo](../pyomo/) for continuous quantities and [OR-Tools](../ortools/) for Routing. The [official CPMpy solver guide](https://cpmpy.readthedocs.io/en/latest/solvers.html) describes native interfaces and backends.
