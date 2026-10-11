# S06-A actual Gurobi paths

Status: local implementation and genuine SDK/Worker validation, SDK 0.6.0 (unreleased).
Scope: [Issue #14](https://github.com/Fangziyang0910/LLM4OM/issues/14), FR-21–27, DD-03/04/05 and AC-11/12/13. Delivery: [draft PR #15](https://github.com/Fangziyang0910/LLM4OM/pull/15), stacked on #13. The
[research note](s06-gurobi-research.md) records official APIs and the earlier independent probe.
Contracts are defined in [plugin-contracts](../plugin-contracts.md#11-s06-a-gurobi-and-native-code-sdk-060).

## Supported paths and use

| Representation | Backend | Solver | Executor |
|---|---|---|---|
| grounded LPIR | pyomo_factory | HiGHS or Gurobi | trusted_local or container |
| parameterized python_factory | pyomo_factory | HiGHS or Gurobi | container |
| native_code (`native_gurobipy`) | gurobipy | Gurobi | container |

Native→HiGHS, generated Code→trusted_local/offline and undeclared capabilities fail admission.
Only LP/MILP is supported. Declared unsupported types fail before generation; actual unsupported
structure fails during construction/export or trusted model-file inspection, before optimization.
No fallback is used. OptiMUS/CoE and full 1.0 remain later slices.

```bash
uv sync --locked --extra dev --extra solve --extra gurobi
uv run --locked python scripts/build_worker_image.py
uv run --locked llm4om doctor --config examples/specs/gurobi.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/gurobi.yaml
```

The optional `gurobi` extra pins gurobipy 13.0.3, Pyomo 6.10.1 and packaging 25.0
(required by Pyomo's Gurobi discovery). It is not a base dependency. The default Worker builder
includes both solver extras; a base-only SDK can select container Gurobi without host solver packages.
A selected local environment or Worker missing its dependency fails admission. SDK/image versions
must match. Manual Actions remain manual; no remote CI is part of this evidence.

For Direct with a configured text Provider, choose `output_mode: python_factory` with the Pyomo
Backend, or `output_mode: native_gurobipy` with `llm4om.model_backends.gurobipy`.
Use `llm4om.solvers.gurobi`. Compact replies are respectively
`{representation, python_factory}` and `{representation, native_gurobipy}`; the latter field is
original Python source. Both define `build_model(data)` and return a Worker-local ModelHandle.
The [native fixture](../../examples/factories/production_gurobi.py) is hand-authored public data code,
not a claim about an external LLM. This slice used local HTTP fixtures and no paid LLM calls.

## Trusted results and provenance

Generated source executes only in the existing bounded construction child, inside the read-only,
network-disabled Linux Worker. Public bytes are the only inputs. prctl protection, clean environment,
closed inherited FDs, subprocess groups, timeout/output limits and container resource limits remain.
Pyomo exports an exact linear instance. Native gurobipy exports SDK MPS bytes and an explicit map
of every scalar variable (including range slacks). The trusted collector reads MPS into new SDK
objects, validates actual structure and mapping, derives a labeled view and independently optimizes.
Candidate optimize methods, solution attributes, stdout and patched child modules are not result sources.
No Python model/ModelHandle crosses the Worker boundary.

Original source, native Code identity and source Formulation remain. `native-model.mps`, decision map
and `native_exported_instance` are derived candidate evidence, not original Formulation or semantic proof.
Exactly one linear objective and closed continuous/integer/binary bounds are supported. Quadratic
objectives/rows, general/nonlinear constraints, multiobjective/scenario/SOS/PWL and semi-domains are rejected.
Gurobi uses a 1e20 bound/RHS threshold, distinct from its 1e100 infinity sentinel.
Finite Pyomo bounds and normalized row RHS with magnitude at least 1e20 are rejected before SDK
construction; the native collector rejects large RHS too. Pyomo coefficients below 1e-13 are rejected.
These checks prevent silent reinterpretation or dropped terms. Native extraction observes the SDK model;
it cannot recover literals already reinterpreted by candidate SDK calls. See the official
[variable bounds](https://docs.gurobi.com/projects/optimizer/en/current/reference/attributes/variable.html)
and [row RHS](https://docs.gurobi.com/projects/optimizer/en/current/reference/attributes/constraintlinear.html).

The Solver returns actual raw status, primal presence/vector/objective, bound/gap/runtime and effective
platform-controlled options. Unavailable/nonfinite metrics are null. Only finite nonnegative
`time_limit_s` is accepted; the run/Worker deadline caps it. Threads=1 and DualReductions=0 are
platform options. The latter separates infeasible and unbounded in the actual micro-fixtures.
CPU/RSS evidence retains the existing Worker measurement scope, not aggregate container peak memory.

## Actual availability and verification

Normal SDK environment discovery is the only license mechanism. Logging is disabled before startup.
Doctor runs a bounded micro-model and 2001-variable boundary probe, without paid requests. This local
Linux Docker environment, without license mounts, succeeds on tiny models and returns SDK error 10010
at the boundary: **size_limited**. Public evidence contains classification and numeric error code,
never license holder/key/expiry or license logs. A successful micro-probe without that error means
`micro_model_available_size_limit_not_observed`, not a full-license claim.

Focused tests use actual gurobipy objects. Hand-derived checks include LP min 2x+2=5 at x=1.5;
MILP max 2x+2=6 at x=2 with fractional closed bounds; LP MPS range/constant roundtrip;
production MILP A=3/B=2/objective13 across all paths; new public capacity data produces objective10.
Genuine infeasible/unbounded and TIME_LIMIT without primal preserve null values. A bounded
300-binary/20-row multidimensional knapsack with a feasible zero SDK MIP start produces genuine
TIME_LIMIT with incumbent/bound/gap; the optimizer accepts the start and supplies all recorded results.
The fixture is not a manufactured status. Actual timing remains hardware dependent.

Hostile-child quadratic MPS is rejected even after bypassing the child's own checker. Source retention,
monkeypatch/stdout spoofing, exceptions, construction timeout and output overflow are tested. Existing
Executor tests retain real isolation/parent-FD checks. Local red/green logs, final regression, packaging,
base-only SDK and Python3.11 wheel evidence are recorded in `/tmp/llm4om-s06a/author-report.md`.
Independent parent review and publication are separate from this author implementation.


## Final author checks (2026-10-09)

- Primary Python3.12.3: one full local regression, 168 tests in 186.613s, all pass.
- Python3.11.13: clean installed 0.6.0 wheel, seven focused real Solver/Backend tests in 0.505s
  plus genuine container doctor/run (objective13); no duplicate full suite.
- strict mypy: 21 source modules; repository:116 source files; reference export/diff checks pass.
  Wheel/sdist and real wheel-only Worker image builds pass; gurobipy stays extra-only.
- Base-only wheel has no Pyomo/highspy/gurobipy. Container Gurobi doctor/run succeeds, offline still
  produces artifact_ready, selected local Gurobi without dependencies rejects admission.
- Actual Worker Python3.12.15/SDK0.6.0/Pyomo6.10.1/gurobipy13.0.3:
  `sha256:56134cdb6a7f49f1dcbf5850812e813ad0e3895fe057ea2443888726cf888b04`.
  Normal SDK discovery, no license mounts, actual size boundary error10010.
- Retained public CLI bundles show Pyomo/native MILP objective13, LP objective40/3. Independently
  installed native entry-point method uses its own `binding` config and zero LLM calls; objective13.
  Solver evidence records genuine time-limit incumbent9654, bound9702 and gap0.004972032318210068;
  those are one actual run's values, not fixture expectations.
- Full commands, focused red/green history, actual results and public paths are in
  `/tmp/llm4om-s06a/author-report.md`, `progress.md`, `solver-results.json`, `live-summary.json`,
  `base-summary.json` and `installed-native-summary.json`. Parent owns independent review/publication.

## Parent delivery checks

One full local Python 3.12 regression passed 168 tests before review corrections. Parent public-seam
checks then reproduced two Interface failures: read-only Mapping rejection and finite 1e20/1e30
bounds or RHS being treated as absent. Three regression tests were red; the shared Mapping/range
checks made all ten Gurobi Solver/Backend tests green (parent-red.log / parent-green.log).
Strict mypy again passed 21 modules. The final source adds these three tests (171 total available);
no duplicate full matrix is claimed. Final package/image and actual container checks were performed after these corrections.
Python 3.12: ten Solver/Backend tests (0.191s) and six CLI/SDK container tests (19.396s) pass.
Python 3.11: the newly rebuilt installed wheel passes all ten Solver/Backend tests (0.258s).
Wheel/sdist build and the final Worker image pass, with image ID
`sha256:9beba6d537077df8233a8de159bd6bed546644d67ed6e7e9a4779ed3c8c9a9de`.
Repository check covers 117 files. Logs use the `parent-` prefix in `/tmp/llm4om-s06a/`.
The annotated native example was independently packaged/installed and solved objective13 with
zero LLM calls; its public bundle is under `parent-example/installed-native/runs/`.

## Standards

Independent review pinned `6445c60...1996468`: one P2 documented-standard finding, native
`build_model(data)` missing explicit input/output types. Parent added `Mapping[str, bytes] -> ModelHandle`
and verified the actual installed fixture. No actionable Fowler heuristics were reported.
The fix is parent-verified, not an independent second review. Report: `review-standards.md`.

## Spec

The independent review of the same pinned diff found no missing/incorrect S06-A requirements or
unasked implementation. It read Issue14, the contracts and connected code/tests; it did not rerun
runtime evidence. Report: `review-spec.md`. Source-only research for S07-B/C is explicitly unimplemented.

Standard/Spec reports and parent corrections are kept distinct. No remote CI or paid LLM call was
used for this slice; package remains unpublished and full 1.0 remains in the approved plan.

Parent credential-value scan passed for tracked files, rebuilt wheel/sdist and selected public Gurobi bundles. The project .env remains ignored with mode0600; its value was not printed.
2026-10-11 P3 处置：零目标 Pyomo 模型改为求解前显式 `unsupported_factory_expression` 拒绝，消除裸 `next()` StopIteration 误用隐患；gurobipy 13.0.3 锁版另已补记入 s03-solver-registry。
