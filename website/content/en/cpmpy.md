CPMpy expresses discrete decisions through integer, Boolean and global constraints. It supports formulations for scheduling, assignment, logic and objective-free satisfaction problems.

## Modeling scope

Variables are finite-domain integers or Booleans, not continuous variables. Fractional data can be scaled to integers when mathematical meaning is preserved; rounding is not a substitute for a continuous decision model.

Common global constraints include `AllDifferent`, Element, Table and Cumulative. Availability depends on native backend support or valid transformations.

## Select it in the platform

Choose CPMpy. Its default is OR-Tools CP-SAT, with native ID `ortools`. The platform reads base backends and installed subsolvers from SolverLookup. Paths may include CP, SAT, SMT, MIP and MaxSAT, subject to actual deployment availability.

## Code and results

`build_model(data)` returns `cp.Model` or a native `SolverInterface`, without directly calling solve. A model may contain constraints without an objective. A valid assignment is then a satisfaction result and the objective can be empty.

An infeasible model can provide MUS conflict constraints for explanation. Actual evidence is required; not every infeasible status automatically yields a business diagnosis.

## Official references

See the [CPMpy solver documentation](https://cpmpy.readthedocs.io/en/latest/solvers.html). Check backend installation, domains and diagnosis separately. Registration as a known plugin does not establish that it can run in your environment.
