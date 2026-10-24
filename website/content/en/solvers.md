A modeling library expresses a mathematical model; a backend computes its solution. Start with the variables and constraints, then choose a combination that can express and solve them.

## Nine modeling libraries

| Library | Typical use | Default or native engine |
|---|---|---|
| [Pyomo](../pyomo/) | Algebraic linear, integer and other optimization models | Usually HiGHS for algebraic models; CBC for Kernel |
| [gurobipy](../gurobipy/) | Native Gurobi and matrix modeling | Gurobi |
| [OR-Tools](../ortools/) | LP/MIP, CP-SAT, routing, network flows and more | Selected for the native interface |
| [CPMpy](../cpmpy/) | Finite-domain integer, Boolean and global constraints | OR-Tools CP-SAT |
| [PuLP](../pulp/) | Linear and mixed-integer programming | CBC |
| [CVXPY](../cvxpy/) | Convex, conic, DGP and DQCP models | A native compatible solver path |
| [PySCIPOpt](../pyscipopt/) | Native SCIP linear, integer and nonlinear constraints | SCIP |
| [CasADi](../casadi/) | Smooth nonlinear models and other plugin-supported models | Ipopt for Opti NLP |
| [coptpy](../coptpy/) | Native COPT linear, integer, convex quadratic and conic models | COPT |

## Choose a combination

For production or transport LP/MILP, begin with Pyomo or PuLP and an open backend. For discrete scheduling and logic, examine CPMpy or OR-Tools CP-SAT. For convex quadratic or conic models, examine CVXPY; for smooth nonlinear models, examine CasADi. Method scope and the installed environment also matter.

Selecting CPMpy does not make a continuous decision an integer one. Selecting an LP backend does not relax integer domains. The platform reports incompatibility rather than silently solving a continuous relaxation.

## AUTO and explicit backends

AUTO uses native selection for the library and model. Run settings list backend availability and reasons from the actual sandbox. An explicitly selected backend is not silently replaced after failure. Results record the actual engine.

Generated code chooses a library's API, and the platform recognizes the returned native model. OR-Tools MPSolver, MathOpt, CP-SAT and Routing are not four additional library settings.

## How code reaches the platform

Usually, code defines `build_model(data)` and returns a native model. The platform solves it; generated code does not call solve or print the solution. Routing, network flows and some CasADi APIs also need managers, source/sink nodes or numerical arguments. See the individual pages and [native interface notes](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/references/modeling-libraries.md).

A registered backend, a loadable plugin and a usable commercial license are different conditions. See [Backends and licenses](../backends/).
