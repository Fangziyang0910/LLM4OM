# S06-A Gurobi environment research

Date: 2026-10-09. Status: primary-source investigation and local SDK evidence, not feature implementation. Scope follows [S06-A](../implementation-plan.md#s06-原生代码与经典方法适配), [Backend/Solver contracts](../plugin-contracts.md), [glossary](../../GLOSSARY.md) and ADR-0001/0003.

## Finding and actual environment

**The smallest usable environment here is CPython 3.12.3 on Linux x86_64 plus pinned `gurobipy==13.0.3`, using normal SDK license discovery. Tiny native LP/MILP solves succeed under an actual size-limited license.** No separate full Gurobi installation, NumPy, license acquisition or configuration change was needed for these probes.

[PyPI](https://pypi.org/project/gurobipy/) and its [JSON metadata](https://pypi.org/pypi/gurobipy/json) identify current release 13.0.3, Python >=3.10, and the CPython 3.12 Linux x86_64 wheel uploaded 2026-08-25. The [official installation guide](https://support.gurobi.com/hc/en-us/articles/360044290292-How-do-I-install-Gurobi-for-Python) documents pinned pip installs; pip does not supply license-management tools. Actual package metadata and `gp.gurobi.version()` both report 13.0.3.

Isolation and reproduction:

```bash
uv venv /tmp/llm4om-gurobi-probe --python /usr/bin/python3.12
uv pip install --python /tmp/llm4om-gurobi-probe/bin/python \
  --index-url https://pypi.org/simple 'gurobipy==13.0.3'
cd /tmp/llm4om-s06
/tmp/llm4om-gurobi-probe/bin/python probe.py
```

Evidence stays in `/tmp/llm4om-s06`: `probe.py`, `probe-result.json`, `lp.mps`, `milp.mps`, `pypi.json`, `pypi-raw.json`. The successful recorded run began at 09:26:13 UTC. Assertions compare with hand-derived optima. Normal initialization uses `gp.Env(empty=True)`, sets `OutputFlag=0` and `LogFile=""`, then calls `env.start()`; models receive this environment explicitly. No license parameters are supplied. Only a boolean remote-solve check is recorded; it was false.

| Actual model | API termination | Primal / objective / variables |
|---|---|---|
| LP: minimize `2x+2`, continuous `1.5 <= x <= 2.5` | `Status=2` (`OPTIMAL`) | `SolCount=1`, `ObjVal=5`, `x.X=1.5` |
| MILP: maximize `2x+2`, integer `1.5 <= x <= 2.5` | `Status=2` (`OPTIMAL`) | `SolCount=1`, `ObjVal=6`, `x.X=2`; `ObjBound=6`, `MIPGap=0` |
| Binary maximize `x`, `TimeLimit=0` | `Status=9` (`TIME_LIMIT`) | `SolCount=0`; objective/vector unavailable; bound `+Infinity` |

LP/MILP use `TimeLimit=5`, `Threads=1`. Both MPS roundtrips preserve the optimum, variable value, `ObjCon=2`, and `ModelSense` (1/minimize, -1/maximize). Re-read models have default options: MPS did not preserve the five-second limit or thread setting. Infinity is a string in temporary evidence, not a JSON numeric value. The first evidence serialization rejected infinity; the corrected recorder completed successfully.

## License evidence versus documentation

A separate bounded, 2001-variable linear model returned **`GurobiError.errno=10010`**, with logging disabled and no exception text retained. The [official error table](https://docs.gurobi.com/projects/optimizer/en/current/reference/numericcodes/errors.html) identifies this as `SIZE_LIMIT_EXCEEDED`. Together with successful tiny solves, this identifies size-limited availability for this SDK session. It does not identify a license holder, key, expiry, or broader rights.

Documentation says pip/conda include a restricted license: at most 2000 variables and 2000 linear constraints, or 200 variables with quadratic terms. [Official restricted-license guidance](https://support.gurobi.com/hc/en-us/articles/360051597492-How-do-I-resolve-a-Model-too-large-for-size-limited-Gurobi-license-error). These documented limits were not exhaustively tested. No capability or licensing right is inferred from installation alone; no full academic/commercial license was evidenced.

## APIs and S06-A implications

The [native Model API](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/model.html) supplies `optimize()`, `getVars()`, `getAttr()` and `write("model.mps")`. Extract trusted results from the worker's actual `gp.Model`, rather than script-printed numbers. Keep the model inside Worker per ModelHandle; export model files, symbol mapping and SolveResult. Native→HiGHS must still be rejected under S06-A's compatibility contract.

[Model attributes](https://docs.gurobi.com/projects/optimizer/en/current/reference/attributes/model.html) define `Status`, `SolCount`, `ObjVal`, `ModelSense`, `ObjCon`, `ObjBound`, `MIPGap`, and `Runtime`; [variable attributes](https://docs.gurobi.com/projects/optimizer/en/current/reference/attributes/variable.html) define `VarName` and `X`. Gate objective/vector access on `SolCount>0`; unavailable attributes raise errors. Preserve solver gap and represent nonfinite bounds explicitly under the platform contract.

[MPS semantics](https://docs.gurobi.com/projects/optimizer/en/current/reference/fileformats/modelformats.html): omitted `OBJSENSE` means minimize; maximization uses `OBJSENSE MAX`; objective constant is the **negative** RHS of the objective row. Actual exports contain `OBJ -2`; MILP includes `OBJSENSE MAX` and integrality markers. This is Gurobi roundtrip evidence, not cross-solver fidelity evidence.

[Status semantics](https://docs.gurobi.com/projects/optimizer/en/current/reference/numericcodes/statuscodes.html): map 2/3/4/5/9/11 to optimal/infeasible/infeasible_or_unbounded/unbounded/time_limit/interrupted. Unbounded alone does not establish primal availability. Retain raw status for other limits rather than falsely claiming optimality. `INF_OR_UNBD` can be investigated with `DualReductions=0` and another solve; that consumes another call.

[Options](https://docs.gurobi.com/projects/optimizer/en/current/reference/parameters.html) use `model.Params.TimeLimit` or `setParam`; TimeLimit is seconds and can overrun during final computations. It does not replace Worker wall-clock enforcement. [Environment initialization](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/env.html) applies pre-start parameters after default configuration discovery; suppress logging before `start()`. Model parameters are copied at creation, so apply solve options to the actual model.

No unresolved local SDK blocker remains. Container license availability, CLI/Worker integration, time limit with an incumbent, other termination paths, and cross-solver exports remain untested. No secrets/license files, other agent logs, paid LLM calls, cloud tests, main environments or GitHub state were accessed or changed. No additional agents were used, as requested.
