# S06-B OptiMUS fixed source workflow

Status: implementation and actual local acceptance in SDK/Worker 0.9.0,
unpublished; independent review is pending. Delivery: [draft PR23](https://github.com/Fangziyang0910/LLM4OM/pull/23). Scope: [Issue17](https://github.com/Fangziyang0910/LLM4OM/issues/17),
FR-14/22–26, DD-03/05, AC-12/13/25. The [source investigation](s06b-optimus-source.md)
records the upstream behavior; [contracts](../plugin-contracts.md#14-s06-b-native-script-resources-sdk-090)
define the implemented interface. This record distinguishes local workflow
evidence from real external-model acceptance.

## Behavior and support

Select `llm4om.methods.optimus` through the existing CLI/SDK. The adapter runs
the complete default main at `e182e9ef5841605c2a7e87467021fd83522b6484`:
supplied parameters and labels, objective extraction, constraint extraction,
redundancy/confidence checks and low-confidence actions, clause formulations,
variables/auxiliaries and reflection, objective formulation, per-clause Code,
original script assembly, and execution-driven whole-script debugging.

| Choice | Actual scope |
|---|---|
| Identity | `optimus0.3-source_main-ec_true-rag_none-external_chat` |
| Formulation | Original six source states; final `native_formulation` |
| Code | Original gurobipy `native_script`, not an LLM-rewritten factory |
| Backend/Solver | gurobipy/Gurobi; LP/MILP; container only |
| Model | Configured shared external text Gateway; upstream source specifies GPT-4o |
| Retrieval | RAG off; every requested RAG mode fails admission before paid calls |
| Debugging | Up to three source executions; final fourth script after three failures is retained but unexecuted |

Fixed MIT source and prompt bytes are shipped separately from platform bridges.
Their manifest records every original URL, hash and size; the original license
and [NOTICE](../../NOTICE) preserve attribution. Whitespace is retained and
verified by hash. Paper v3 and this source main are separate fidelity targets:
the inspected main does not contain the paper's full graph/structure/sifting
algorithm. No complete paper reproduction or retrieval support is claimed.

## Public inputs and resource mediation

ProblemSpec0.3.0 admits bounded JSON objects alongside existing CSV inputs.
`params_data_id` identifies an explicit symbol map whose entries contain
`value`, `shape`, `definition`; `labels_data_id` identifies explicit public
labels. Original JSON values and description bytes remain. Missing parameter
metadata is rejected instead of inferred from benchmark references. See the
[public example](../../examples/optimus/README.md).

Fixed stage code runs in a bounded, clean-environment subprocess. It uses
platform file, chat and execution bridges; generated Python runs only in an
isolated Worker child. Each chat request uses Gateway trace, stable request ID,
budget and credential isolation. States, scripts, source calls, revisions and
selection are public artifacts; raw model replies remain in private storage.

The raw script's exit/stdout/stderr determine the original source repair path.
A capture hook exports a candidate MPS before optimize; its observations are
untrusted. A fresh container collector reconstructs SDK objects, validates the
actual LP/MILP and independently solves it. Collector failure is recorded
separately and does not add a source debug request. Unsupported/multiple models,
missing capture or successful stdout cannot manufacture trusted SolveResult.

The ledger counts script attempts and collector attempts separately, using two
Solver slots when a supported capture is collected. `source_optimize_calls`
remains null; untrusted hook observations cannot prove every optimize call in
arbitrary generated Python. Admission license probes are recorded separately.
Source, data, bindings and admission identity must match for execution reuse.
Unknown interrupted execution is rejected; a verified completed publication
receipt can be recovered without another model or Solver call.

## Current local evidence and remaining acceptance

Nine public MethodContext tape cases compare prompts, roles, six states, raw
scripts and selections with the actual fixed `main.py __main__` reference on
the same responses/exits. They cover low-confidence keep/remove/modify, missing
scores, auxiliary variables, non-mutating reflection, parser retries/collision,
and zero through three failures. This proves source workflow fidelity on those
tapes, not external-model quality.

Six synthetic-HTTP SDK cases with actual isolated Gurobi passed after rebuilding
the source-matched Worker: final result reuse, completed publication recovery,
continuous LP, collector/source feedback separation, Solver budget and requested
RAG admission. Additional local tests verify cancellation/container removal and
unknown admitted execution refusal. Cancellation initially left an async source
pipe alive; draining the killed subprocess under protected cleanup removed the
event-loop-close warning. Logs are under `/tmp/llm4om-s06b/parent-*`.

The development image is separate from the accepted0.8.0 image. Wheel/sdist
builds passed; a clean Python3.11.13 wheel installation passed nine source-tape
cases and an actual SDK/container Gurobi run (objective12), including final
execution reuse. Strict mypy passed26 modules; repository checks passed155
files, including thirteen maintenance CLI tests and fixed-source mutation
rejection. One complete local Python3.12.11 integration regression passed263 tests in
571.935s. It covers existing paths plus the new resources, source workflow and
actual Docker/HiGHS/Gurobi behavior; no duplicate full matrix was run.

## Real configured model acceptance (2026-10-10)

Run `19962809094a4a8d8edcc4781fea6397` used the authorized configured
`deepseek-v4-pro-0813` via OpenAI-compatible `api.x5m5x.com/v1`. It made eleven
actual paid requests (7195 reported total tokens; cost unknown), then one
original script execution and one fresh Gurobi collector. Source execution
succeeded; the collector returned optimal `x=4`, objective12. Independent
inspection of the actual MPS-derived model verified integer lower bound0,
capacity row `x<=4`, objective `max 3x`, and all five feasible integer choices.
This is a hand-checkable public micro-case, not a benchmark score.

All six states and the original script remain. Fixed-main same-tape comparison
matched eleven prompt requests, one execution, file hashes and selection. The
model produced repeated JSON/reasoning in a clause reply; the upstream greedy
parser retained extra fragments inside its formulation text. The adapter
preserves this source quirk. The actual Code model matches the public problem;
this does not certify a clean or fully correct native Formulation.

The accepted SDK source hash is
`78aa477f4d2fbf03b7140008210b7039c987994ed34ce6d14dcfa24d7e1c36bb`.
Worker0.9.0 image:
`sha256:db98a3e5f3f0220f136b707e36d430ee77c4b21093e4aef2b7edeed4e91f558e`.
Wheel/sdist, hashes, configuration and verification are retained under
`/tmp/llm4om-s06b/real-acceptance/`. Verification checked155 source files,
151 public run files and118 package members for the actual project key;
all passed. Private raw storage stays0700/0600. The source container was
removed. Credential-free completed resume added zero model/Solver calls and
left the ledger unchanged.

Independent Standards/Spec review cannot currently run: the local Codex
review/author CLI reached its account usage limit. Parent self-review is not
labeled independent review. No remote CI or public package release is part
of this evidence. Final independent integration acceptance remains pending
that review. Parent Standards/Spec self-review found no remaining actionable
P1/P2 in its reading; reports are separately retained as
`/tmp/llm4om-s06b/parent-review-standards.md` and `parent-review-spec.md`.
