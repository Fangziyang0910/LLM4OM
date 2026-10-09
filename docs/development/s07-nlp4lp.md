# S07-B NLP4LP public input and supplied-reference comparison

Status: SDK/Worker0.11.0 local implementation and actual model/Solver acceptance;
full local regression and independent review are pending. Delivery: [draft PR25](https://github.com/Fangziyang0910/LLM4OM/pull/25).
Scope: [Issue21](https://github.com/Fangziyang0910/LLM4OM/issues/21), FR-08–12/28–30,
DD-06, AC-04/05/25. Source facts: [fixed-source research](s07-benchmark-research.md).
Interface source: [contracts](../plugin-contracts.md#16-s07-b-nlp4lp-task-interface-sdk-0110).

## Source, public projection and consistency

Import reads authorized local bytes only. Official identity pins Hugging Face
release `f0f2abb5d4fa01812ab2c818dd350f6c34041d15`, aggregate hash and the2,127-file
hash/size/URL table. The original source card and CC BY-NC4.0/research-use
statements accompany snapshots. OptiMUS code's MIT license does not license
this dataset. SDK bundles only generated hash metadata, not dataset records.

All361 original IDs/difficulty labels remain. Public ProblemSpec0.3.0 has the
original description plus concrete parameters.json bytes, data hash/schema and
provenance. Scalars, arrays, keyed dictionaries and string counts retain their
types. No public parameter descriptions, domains or labels are fabricated from
the hidden problem_info. Code, formulation context, parametrized description,
keywords, solution and original aggregate/per-instance files remain private.
Reference code is copied as opaque bytes and never executed.

Before choosing per-instance parameter bytes, import compares the aggregate
with description, parameters, metadata, code, problem_info and solution files.
Descriptions/code compare exact bytes; nested JSON compares decoded values and
scalar types. Invalid private JSON compares raw bytes and becomes a diagnostic.
An ambiguous public source or changed fixed file fails admission. On the actual
fixed release all six correspondingly published fields match for all361records.
Remaining aggregate fields are retained privately as original source material.

Reference availability is separate from public import and eligibility:
37missing solutions,2invalid solutions (IDs3/51),322parseable supplied objective/
vector objects. None is labeled an independently certified optimum or feasible
vector. Missing/bad source solutions do not delete otherwise valid public tasks.
Malformed public parameters or duplicate/changed/ambiguous sources reject import.

## Public mathematical review and grading

A frozen review binds exact description and parameter hashes, LP/MILP/domain
interpretation, rounding, explicit data-binding policy and public evidence spans.
Difficulty labels and text keyword screens do not certify support. Selection,
eligible counts, unavailable-reference reasons and reviewer identity are frozen
before any model run. MAMO and NLP4LP share the public-review and candidate-only
numeric tolerance implementation, while keeping their source semantics separate.

Task/CLI/SDK reuse the existing import/evaluate entry points. Common run checking
allows the application's copied data paths to differ while requiring identical
public bytes, hash/schema and problem content. A public-seam red test reproduced
the previous incorrect cross-case rejection; the shared fix also rejects changed
snapshot/run data and retains error denominators. No modeling-method ID branch
or source-code execution was added.

`supplied_objective_reference_match` compares only an available candidate Solver
objective with the supplied private number. Abs/relative tolerances and rounding
are frozen; reference numbers are preserved. Variable mapping, independent
feasibility and full Formulation correctness remain unavailable without actual
independent evidence. Supplied nested vectors do not create a flat-vector or
checker contract. Public scores contain no reference values/differences, code,
oracle refs or raw supplied vectors. Failed generation/execution/checker attempts
stay in their declared denominators.

## Current local evidence and remaining checks

The full release imported361 public problems and observed the exact322/37/2
availability counts. One reviewed public LP selects original ID1. From the
description and parameters alone: maximize0.5C+D, C,D>=0, C+D<=760000,
C>=0.2(C+D), D>=20000. With T=C+D, objective<=0.9T<=684000; C152000/D608000
attains the bound. The public proof was recorded before supplied-reference
grading under `/tmp/llm4om-s07b/real-acceptance/public-proof.txt`.

Five public-seam tests pass: preserved parameter types/private isolation,
review/selection/binding, actual HiGHS objective matching, source ambiguity/
duplicate/mutation, and separate failed-run/reference diagnostics. Changed
snapshot/run data and private material become persisted errors with the same
eligible denominator. MAMO's five regression cases pass after policy reuse.
Strict mypy passes29 modules. Logs are under `/tmp/llm4om-s07b/`.

Wheel/sdist and actual Worker build passed; clean installed Python3.11.13 wheel
passed five NLP4LP cases in6.063s. One complete local integration regression is
running. Independent
Standards/Spec review is unavailable due the local Codex CLI usage limit; parent
self-review will be recorded separately. No cloud CI, package/dataset release
or full benchmark score is claimed. Whole1.0 remains active.


## Real configured model acceptance (2026-10-10)

Actual `deepseek-v4-pro-0813` first request failed with provider_connection_error
and no response. Run `b65d78dd88614454bfa05d3e34298113` retains that attempt,
unknown19800token reservation, null usage/cost and an eligible failed-case
comparison denominator1. It was not resumed as an automatic unknown replay.
After an unpaid endpoint HTTP200 check, a declared two-repeat pilot admitted
one fresh second run, retaining both attempts and the unknown first usage.

Second run `23429a27c47e402f9192f0811292f9a6` completed: one actual external
request,1998reported total tokens (cost unknown), one actual container HiGHS
solve, objective684000 and investments152000/608000. Supplied-reference numeric
match passed. Inspection of the actual IR confirmed continuous nonnegative
variables, public objective,760000budget,0.8C-0.2D>=0 and20000detached minimum;
the public upper-bound proof supports that concrete model. The benchmark's
independent-feasibility/full-semantic/vector-mapping layers remain unavailable.
This is a one-question/two-attempt pilot, not a full benchmark score.

All361 original public descriptions/parameters remain. Source163/public804/
package128 actual-project-key scans passed; all public projections omit hidden
source fields. Private snapshot and raw response storage stay0700/0600.
Actual container was removed; credential-free completed resume added zero
model/Solver calls. SDK source/wheel/Worker hash:
`1112f1e47d8af5d57ebacdecb0c0a3881318d6922b3ded8064bcc85211052d63`.
Worker image:
`sha256:214c85fe9d27f31f8bed13152b1ad6dba5b39dee1cbb1a2682aa060fdca15a21`.
Retained wheel/sdist, public proof, both original attempts, pilot budget and
verification are under `/tmp/llm4om-s07b/real-acceptance/`.

The generated release hash table was normalized to two-space JSON/LF. Original
research metadata artifact SHA was a2f2385b76eaf5bd3f55ae3acabfacf1c14f46fe563ac8c390c72e0025afd1d9;
normalized metadata SHA is a0a78906086b644156f079db1fdef9d10c6f8855a42ced9ab751e0fd1db49c66.
All2,127 original source file hashes/sizes/URLs remain unchanged.
