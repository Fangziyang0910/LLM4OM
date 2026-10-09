# S07-B NLP4LP public input and supplied-reference comparison

Status: SDK/Worker0.11.0 development implementation; final acceptance is pending.
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

Actual configured model/container acceptance, package/Worker/independent wheel
checks and one complete local integration regression remain pending. Independent
Standards/Spec review is unavailable due the local Codex CLI usage limit; parent
self-review will be recorded separately. No cloud CI, package/dataset release
or full benchmark score is claimed. Whole1.0 remains active.
