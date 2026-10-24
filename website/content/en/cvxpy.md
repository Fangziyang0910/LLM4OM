CVXPY constructs optimization problems through expressions and mathematical rules. It supports convex quadratic and conic formulations; the platform also recognizes DGP and DQCP modes.

## Modeling rules

Use DCP-compatible expressions for ordinary convex models. DGP needs its positive-domain and geometric structure, while DQCP needs the corresponding quasiconvex rules. The platform detects the mode from the returned `Problem` rather than bypassing these rules.

Common expressions include `sum_squares`, `norm`, `quad_form` and matrix multiplication `@`. Do not use Python `if`, `max` or control flow that depends on symbolic variable values.

## Select a backend

AUTO follows CVXPY's native solver_path through installed compatible engines and records the one actually used. Explicit backend selection is not replaced after failure.

| Example backend | What to check |
|---|---|
| OSQP | Continuous convex quadratic objectives and linear constraints; no other cones or integer domains |
| Clarabel, SCS | Their respective continuous conic capabilities |
| MOSEK and others | Problem capabilities, installation and license requirements |

Integer and Boolean decisions need a compatible mixed-integer backend. Choosing CVXPY does not make a continuous solver valid for them.

## Code and results

`build_model(data)` returns `cvxpy.Problem` for platform solving. Results retain native status and numerical-accuracy meanings. The current platform does not provide IIS/MUS explanations for CVXPY.

## Official references

See [CVXPY solver features](https://www.cvxpy.org/tutorial/solvers/), [DGP](https://www.cvxpy.org/tutorial/dgp/) and [DQCP](https://www.cvxpy.org/tutorial/dqcp/). Actual availability is established by the sandbox backend list and a real solve.
