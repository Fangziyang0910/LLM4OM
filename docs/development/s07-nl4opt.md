# S07-A NL4Opt import and evaluator research

Purpose: fixed-source research and S07-A implementation/acceptance, 2026-10-09. SDK 0.4.0 remains unpublished. Source inspection and runtime evidence are distinguished below. Normative sources: [contracts](../plugin-contracts.md), [evaluation](../evaluation.md), [S07-A](../implementation-plan.md#s07-基准导入与独立评测), and [oracle isolation](../adr/0002-oracle-isolation.md). README, GLOSSARY, coding/contribution rules, relevant requirements and evaluation design were read.

The smallest honest import exposes the original document and privately preserves formulation annotations. Official NL4Opt supplies **reference declarations, not solved reference objectives or solutions**. A numerical objective evaluator requires separately reviewed, derived reference models and real solver evidence.

## Source lock and reproducibility

Catalog R03 identifies `nl4opt/nl4opt-competition`. Its [fixed README](https://github.com/nl4opt/nl4opt-competition/blob/49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea/README.md) identifies the dataset and official subtask baselines. This investigation resolves and freezes competition commit `49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea`; catalog did not previously prescribe a commit.

All generation files were downloaded and parsed. Each line is one object keyed by a signed decimal sample-ID string, containing one record. IDs are unique within each split; preserve the string, not a generated row number. First IDs are train `-804075997`, dev `-640645082`, test `1117636837`. Counts are 713/99/289.

| Fixed source path | SHA-256 of original bytes |
|---|---|
| [generation_data/train.jsonl](https://github.com/nl4opt/nl4opt-competition/blob/49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea/generation_data/train.jsonl) | `120ff6881c723296c458ef34f3840b5f14d174c6c30dd7002711f59e7e262380` |
| [generation_data/dev.jsonl](https://github.com/nl4opt/nl4opt-competition/blob/49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea/generation_data/dev.jsonl) | `6538ce1fe76861f89879672a6c9a02c8f41156952256f3cfde82c2808ba320ee` |
| [generation_data/test.jsonl](https://github.com/nl4opt/nl4opt-competition/blob/49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea/generation_data/test.jsonl) | `2a4a20a11935aacc99068ee4207d5265f15c0b387d4720c548c196d8ff2fcf5b` |
| [LICENSE](https://github.com/nl4opt/nl4opt-competition/blob/49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea/LICENSE) | `d8165362b50a26ccad4bc717c050c86db776b1c6d2ec40f288e416d0ecb62399` |

The license is MIT, copyright Huawei Technologies 2022; retain its notice when redistributing. No separate dataset license appeared in the inspected tree. Dataset Git blob IDs, independently recomputed as SHA-1 of `blob <byte-length>\0<bytes>`, match the commit tree: train `bf758170d44253ffb48600f9fea7bd5be7e7695c`, dev `01d8f86b9782e064dc29e8995a035d6595b13780`, test `417de7626b22445714b8017bc9fc24c493dab789`.

Downloaded public sources and API commit/tree responses remain under `/tmp/llm4om-s07/upstream`. Reproduce downloads with `https://raw.githubusercontent.com/nl4opt/nl4opt-competition/<commit>/<path>`; run `sha256sum` on the saved bytes. Count JSONL lines and enumerate their sole outer keys with standard-library JSON. These were data inspections, not tests or upstream execution.

## Actual schema and two inspected records

Across all 1,101 records the fields are `document`, `vars`, `var_mentions`, `params`, `var_mention_to_first_var`, `first_var_to_mentions`, `obj_declaration`, `const_declarations`, `spans`, `tokens`, `_input_hash`, `order_mapping`. Numeric coefficients/limits are strings. Objective declarations contain type/direction/name and either `terms` or `vars`; no-terms occurrences number 11/21/85. None supplies a variable-domain field, solved objective value, solution vector, bound or solver certificate. `_input_hash` is an upstream identifier, not a cryptographic content hash.

Both following records are lines 1–2 of the fixed dev file above. Raw-line SHA-256 excludes the terminating newline.

| ID | Annotation interpreted mathematically | Raw-line SHA-256 |
|---|---|---|
| `-640645082` | Rickshaw/ox-cart quantities r,o: maximize 50r+30o; 10r+8o≤200; r≤o. | `49d71b1effe2efb10ba19ffcb575a85e888a2d4f8300d49c6bca645a83606963` |
| `892653388` | Table/chair quantities t,c: maximize 350t+75c; 8t+2c≤500; c≥0.7(t+c); 1000t+150c≤20000. | `3b3a6dc415554e94f962576b6e0a432f8edf925e9af09e8d68410ec916bdd6b3` |

Aliases map singular/plural mentions to columns; the second record uses singular objective-term names. Both texts request an LP but count indivisible objects. Continuous nonnegative domains are a plausible LP interpretation; integrality is a different interpretation, not a supplied label. Neither nonnegativity nor integrality is encoded in these declarations. Preserve this ambiguity; any completed domain policy belongs to a named derived benchmark. No reference optimum was computed here.

## Minimal projection and mathematical semantics

PublicProblem: preserve `document` exactly, language `en`, stable dataset/split/sample ID, fixed source commit and license reference. Use a reproducible public-input revision; requirements, assumptions and data_refs can be empty. Use `unknown` unless an explicit public LP interpretation justifies `lp`. Do not manufacture confirmed domains.

Hidden EvaluationOracle: retain original declarations, aliases, order_mapping and raw-record hash as source reference-model material, explicitly incomplete for solving. Keep all annotations, including spans/tokens/vars/params, out of default end-to-end method input. Official subtask 2 supplies entities and order mapping as inputs; exposing them requires a separately identified assisted task. Methods, Worker mounts, repair feedback and public exports must not receive the full source JSONL or oracle paths.

Freeze a manifest before runs: commit, file/hash, split, source ID/line/hash, projection revision, domain/normalization policy, protocol, eligibility and exclusion reasons. For translation, honor `operator`, not English direction alone: sum means sum over mapped variables; bounds select one variable; linear means weighted sum; ratio means x versus p·sum(x); xby means x versus a·y; xy means x versus y. Parse percentages and fractions explicitly, resolve aliases, and reject unknown numbers/operators/types rather than guessing. Missing objective terms require checking the unit-coefficient convention against declared vars.

## Evaluator evidence and remaining checks

The official [baseline parser](https://github.com/nl4opt/nl4opt-subtask2-baseline/blob/18a54bcb2c34be7d034d994c9e065e59cdf1ddfe/parsers.py), [scorer](https://github.com/nl4opt/nl4opt-subtask2-baseline/blob/18a54bcb2c34be7d034d994c9e065e59cdf1ddfe/scoring.py) and [evaluation caller](https://github.com/nl4opt/nl4opt-subtask2-baseline/blob/18a54bcb2c34be7d034d994c9e065e59cdf1ddfe/test_utils.py) are locked at `18a54bcb2c34be7d034d994c9e065e59cdf1ddfe`. Their SHA-256 hashes are respectively `85cb64371e817ada6acb0bff9958c2b83cd42e0cf1e23ac1a77fbac66d1af63e`, `1c172914975c40f0add570ffdf9da4c80fd534dda99dec18fede5e50a75d4912`, `89d931830e9f22d1b6a92968d0ceb0df7631b15d613753890ab181f3ee16e39e`.

Scoring uses exact array equality, deduplicates predicted constraints, and returns 1−Σ(fp+fn)/Σ(reference declaration counts). It is declaration scoring, not per-instance solution accuracy. Canonicalization omits objective direction and variable domains. Its `xy` branch retains initial RHS 1; sparse linear rows retain initial coefficients 1. Number parsing can silently yield zero and JSON parsing can return an empty formulation. These behaviors require explicit fidelity decisions; do not copy them into a mathematical checker unnoticed.

S07-A can honestly demonstrate import/isolation, public execution evidence, and separately labelled annotation comparison. A reviewed derived model can later support independent feasibility and objective recomputation with a verified decision mapping. A reference optimum additionally needs an actual reference solve and termination evidence. For raw supplied data, numerical-objective eligibility is zero: rates are null/not_available. Preserve import/checker errors and admitted run failures; never shrink denominators after outcomes.

Remaining: full per-record mathematical/domain review, cross-split duplicate analysis, supported numeric grammar, decision mapping, derived-model validation and real solver acceptance. The source-inspection phase performed no implementation, tests, installs, paid calls, private trace/credential reads, Git operations or publication; implementation evidence follows.

## S07-A implementation evidence (2026-10-09)

The research above is preserved. Local implementation now exposes CLI `import` / `evaluate`,
SDK `import_dataset` / `evaluate_case`, shared `TaskAdapter.iter_cases` / `Evaluator.evaluate`
and immutable case identity/manifest bytes. Source validation uses existing strict JSON and
public ProblemSpec contracts; snapshots reuse content-addressed storage and atomic acceptance.
No task/evaluator registry, batch expansion, NLP4LP/MAMO or upstream mathematical parser was added.
Package and Worker versions remain unreleased 0.4.0.

Actual fixed-source local imports from the previously downloaded split bytes admitted
train 713, dev 99 and test 289 cases, with first IDs `-804075997`, `-640645082`, `1117636837`.
Each frozen manifest has N_eligible=0, declarations incomplete and domains unspecified.
Official projections retain MIT source attribution; new official snapshots include the original
LICENSE text. Fixtures use `fixture-nl4opt:test-v1`, never the official identity or commit.

Public-seam tests cover CLI/SDK import, original descriptions, duplicate IDs/JSON keys,
invalid UTF-8/CRLF, unknown or malformed record fields/types, split hash mismatch, false official
identity, changed public bytes, actual failed runs, different public revisions and corrupted
solve evidence. A local HTTP fixture invokes the actual CLI, Docker Worker 0.4.0 and HiGHS:
fixture candidate objective 13, completed execution; independent evidence stays not_available.
Provider request and public run files contain no annotation sentinel, oracle references or
source JSONL path. Existing Worker input assembly sends only candidate request/model and
explicit public data, not the imported snapshot directory.

An additional **engineering smoke on an actual official sample** used the original public
coconut description, a manually authored HTTP response fixture and real Docker/HiGHS.
Case `nl4opt:49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea:dev:-640645082`, local run
`46606c2dd0c74379beb740456bbc56b1`, completed; candidate LP termination optimal,
reported objective 888.8888888888889, checker_error=null, N_eligible=0 and objective rate=null.
The fixture chose nonnegative continuous candidate variables for this smoke; these are **not**
imported reference domains. This is neither a real external-model result nor a reference optimum.
Ignored local evidence resides in `runs/s07-source-inspection/official-local-evaluation.json`.

Author Standards self-check: changes reuse current application/validation/storage seams,
public tests observe actual files/results/HTTP requests, all new repository files have audit rows.
Author Spec self-check: local import/isolation/frozen provenance and honest single-case evaluation
are implemented. A failed run before public input persistence records unverified case binding.
No claims of declaration accuracy, independent feasibility or semantic verification are made.

Remaining parent acceptance: configured real external LLM on the official sample and independent
Standards / Spec review. They were intentionally not performed under this task's authorization.
Full source mathematical/domain review, derived references and independent checking remain later
work; no paid calls, actual credential files, preexisting private run archives, other agent logs,
GitHub mutations, commits, pushes or branch changes were used.

Final checks: `uv run --locked --extra dev --extra solve python -m unittest discover -s tests -v`
completed **143 tests in 127.433s, OK**, exit 0. A final red/green unknown-RunBundle-version
boundary check then passed the focused S07 file: **4 tests in 2.423s, OK**; the full suite was
not repeated for that narrowly tested guard. Final mypy: **17 source files, no issues**.
Repository checks: **102 files, passed**; reference rendering check and `git diff --check` passed.
Final `uv build` produced `dist/llm4om-0.4.0.tar.gz` and `dist/llm4om-0.4.0-py3-none-any.whl`.
The rebuilt wheel was installed in an isolated local environment; SDK exports, CLI help,
actual official dev import and evaluation of the stored official-sample local smoke all passed.
Independent review 2026-10-11: passed after same-day P1 fix in shared evaluate_case (guard swallowed by RunError(ValueError) inheritance); see /tmp/llm4om-reviews/s07-group.md.

## Parent real-model acceptance

On 2026-10-09 the same frozen official dev case ran through the public CLI with
`deepseek-v4-pro-0813`, the configured HTTPS Provider and container HiGHS, without
reference declarations/code/answers in its input. Run `1671919729cd48e386c30b2834435204`
completed, termination optimal, continuous candidate x=y=100/9 and reported objective
8000/9≈888.8888888888889. The public text's cost and ordering rules hold; the candidate
LP attains the bound from positive resource allocation with x≤y. This is a checked
candidate LP interpretation, not a supplied benchmark reference optimum.

Post-run raw NL4Opt evaluation returned checker_error=null, objective_match=not_available,
N_eligible=0 and rate=null. Provider reported input=713, output=3640, total=4412;
cached/reasoning fields were absent and remain null. These counts are preserved as
reported, including their non-additive total; cost is unknown. The run and evaluation
are stored outside version control at `/tmp/llm4om-s07/live`.

Independent Standards / Spec review and author fixes are recorded below. Validation is local by user
instruction; GitHub Actions is manual, and no cloud test is required for this acceptance.

## Independent review and fixes

Two independent read-only reviewers compared 8cef3fb…806c6d0. Standards found one
hard boundary violation; Spec found that same defect and one error-persistence defect.
Neither found concrete scope creep or a justified code-smell issue.

The evaluator had trusted stage flags without checking the supporting model files.
Public tests changed artifact, Formulation, IR and Python source independently: all four
initially retained pass, then correctly returned checker_error/error after verifying every
declared run artifact's hash and size. The CLI had rejected changed snapshot files before
saving an evaluation result. Metadata selection now precedes evaluator material checks;
public/private file changes and deletion first reproduced missing output, then produced
saved error records with frozen counts. Modeling iteration still verifies snapshot bytes.
These fixes have author red→green verification, not a second independent-review claim.

Actual LP acceptance can be checked from the public text: 50x+30y =
(40/9)(10x+8y)−(50/9)(y−x) ≤ 8000/9; x=y=100/9 attains the bound.
Public run/evaluation scans contain neither the actual credential value nor annotations,
oracle references or the local source JSONL path. Raw benchmark independent evidence
remains not_available.

Final parent acceptance: Python 3.11.13/3.12.3 each passed 143 tests (126.509s/126.562s),
including real Docker; 17 modules passed strict mypy, 102 source files and reference exports
passed checks. Final wheel/sdist and Worker rebuild succeeded; SDK-only wheel installation
passed free doctor and re-evaluated the preserved real sample without another model call.
Worker image `sha256:428036c9d57880f3ee79afb35889ecc319c8b19469dfef7963230a2cbb7c269e`.
The actual upstream LICENSE bytes match the copied notice. S07-A's current raw-data scope
is accepted; numerical accuracy, derived reference models and remaining 1.0 work stay separate.
