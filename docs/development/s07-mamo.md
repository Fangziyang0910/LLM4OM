# S07-C MAMO import and numeric comparison

Status: SDK/Worker0.10.0 local implementation and actual local acceptance;
independent review passed 2026-10-11 (PASS-WITH-NOTES; report /tmp/llm4om-reviews/s07-group.md). Delivery: [draft PR24](https://github.com/Fangziyang0910/LLM4OM/pull/24). Scope: [Issue22](https://github.com/Fangziyang0910/LLM4OM/issues/22),
FR-08–12/28–30, DD-06, AC-04/05/15/25. Source facts are in the
[fixed-source research](s07-benchmark-research.md). The [contracts](../plugin-contracts.md#15-s07-c-mamo-task-interface-sdk-0100)
define the implemented interface; [evaluation protocol](../evaluation.md) defines evidence layers.

## Public input, source and selection

The adapter pins MAMO commit `2c91069dee5c1e4db4b899eb176ec987d0251bb3` and
all three canonical JSONL hashes. An official import preserves652 EasyLP and
211 ComplexLP questions.346 ODE records are explicit source exclusions. Original
subset/ID, Question text including inline LaTeX/data, record/line hashes and
source file bytes remain. Few-shot files are not additional benchmark splits.

Only Question and public provenance enter ProblemSpec. Answer and original
complete records/files stay in the0700 private snapshot directory, files0600.
Official snapshots retain the fixed CC BY-SA4.0 LICENSE and source attribution
with projection/modification notice. Dataset projections do not acquire the
project's Apache license. No dataset content is bundled in the SDK.

EasyLP/ComplexLP labels do not certify LP/MILP or variable domains. Import admits
all public questions; numeric comparison eligibility requires a frozen public
question review. It states classification, domain interpretation, rounding,
reviewer and exact evidence spans bound to the Question hash. Unsupported and
unresolved reviews retain reasons. The adapter verifies shape/Question binding
before yielding selected cases. Import records all cases and independently
freezes `N_imported`, `N_selected` and `N_eligible` before modeling. It does not
derive domains or rounding from Answer or remove failed selected cases.

## Actual evaluation behavior

CLI/SDK use the existing import/evaluate entry points. NL4Opt retains its0.1
snapshot/raw-declaration protocol. Common frozen-case material and actual-run
checks are shared; dataset-specific projection and reference semantics remain
in their adapters/evaluators. There is no modeling-method ID branch.

MAMO compares an available Solver objective with a supplied private numeric
answer under `llm4om.eval.mamo-numeric-v0.1`. Tolerance is
`abs(pred-ref) <= abs_tol + rel_tol*abs(ref)`, frozen with defaults1e-6/1e-5 in
the example config. The zero-answer case uses this same expression. Optional
decimal half-away-from-zero rounding applies to the candidate according to the
public question review; the supplied reference is preserved. Rounding both
numbers incorrectly hid a malformed reference in a red test; candidate-only
normalization fixes it.

Numeric agreement is `supplied_numeric_reference_match`, not certified optimum,
independent feasibility or full Formulation correctness. Canonical records have
no reference model/vector/certificate; those layers remain not_available.
Generation/execution/checker failures retain the selected eligible case in its
comparison denominator. A single-case result reports its own denominator and
the manifest's global counts; it is not a completed benchmark aggregate.
Changed/missing public/private/policy/source material yields a saved checker
error. Public evaluation output contains no oracle_ref, Answer or numeric
reference/difference. No COPT support is inferred from the author's scorer.

## Current actual local evidence

The full canonical source imported863 optimization cases, preserved346 ODE
exclusions, and froze a one-case smoke selection with one eligible MILP. Its
public review used only the Question. The selected EasyLP1 model was constructed
before evaluation: nonnegative integer allocations X,Y, total<=1000,
X-Y>=200, X<=700,Y<=500, minimize50X+30Y. Since
`50X+30Y=50(X-Y)+80Y>=10000`, X200/Y0 attains the lower bound. Actual HiGHS
returned that vector/objective and matched the private numeric answer.

The model is hand-authored and supplied through synthetic loopback HTTP. This is
actual Solver/task/evaluation acceptance, not paid external-model quality or a
full benchmark score. Zero paid model calls were made. Evidence and original
source snapshots remain under `/tmp/llm4om-s07c/canonical/`.

Public SDK/CLI tests cover import/isolation/IDs, selected iteration, review
shape, invalid/duplicate/mutated source, retained failure denominators and
material errors. Six actual HiGHS cases cover zero, candidate rounding/ties,
negative ties and preserving an incompatible numeric reference. The existing
five NL4Opt import/evaluation cases passed after the shared check extraction.
Strict mypy passed27 modules. Logs are under `/tmp/llm4om-s07c/`.

Wheel/sdist and actual Worker build passed. A clean Python3.11.13 wheel
installation passed all five MAMO cases, including six actual HiGHS numeric
boundaries. One complete local Python3.12.11 regression passed268 tests in
588.824s; it includes actual Docker/HiGHS/Gurobi and existing protocols.
Source158/public942/package121 actual-project-key scans passed; all863 public
projections omit private fields, snapshot private storage is0700/0600.

Actual SDK0.10.0 run `853e511be97048b39fba7660b35f19bd` supplies the canonical
HiGHS vector/objective match. An earlier smoke harness used a stale loopback
config and failed; its saved evaluation keeps denominator1/numerator0. The
corrected harness creates a fresh run instead of deleting that failed attempt.
Completed resume passed. Evidence: `/tmp/llm4om-s07c/verification.json`,
`canonical/sdk010/solver-verification.json`, `full-python312.log` and
`wheel-311-focused.log`.

Independent Standards/Spec review is unavailable because the
local Codex CLI account usage limit was reached; parent self-review will be
recorded separately at `parent-review-standards.md` and `parent-review-spec.md`
in the task evidence directory. No remaining actionable P1/P2 was found in that
parent reading; it does not fulfil independent review. No remote CI, package publication or dataset redistribution
was used. Whole1.0 remains incomplete.

## Final installed delivery

Source SDK hash:
`b45e3b7f45bb2b7be7eb109109d8ec7c82fcf9b504a1c10f8010cbbbad6882e2`.
The full regression used image
`sha256:445e14fe70f2f291dc5e247b32ad96de3b7b261025f1045ef1363e0378befd3e`.
After README metadata synchronization, final wheel/Worker retain the identical
SDK source. Final image:
`sha256:3e7f2212d2612374fbbb57e374786d4190dfc7c32d9a7484ad594d589132daef`.
The final Python3.11 wheel matches that source and independently evaluates the
canonical run's supplied numeric answer as pass. Root SDK0.10.0 also passed an
actual final-image Gurobi run (objective13) and canonical completed resume;
project `.env` remains unchanged0600/ignored. No duplicate full suite followed
these metadata-only changes. Final scans and source/image checks are recorded
in `final-verification.log`; root evidence is `root-smoke/verification.json`
under `/tmp/llm4om-s07c/`.
