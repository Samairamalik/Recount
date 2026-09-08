# Recount design

Recount verifies the numeric, comparative and ranking claims in an LLM-generated report
against the source dataset. An LLM extracts the claims; everything after that is
deterministic code: a compiler binds each claim to the user's metric definitions, one
fixed SQL template per claim type recomputes the value in DuckDB, and a policy compares
stated with computed. The output per claim is PASS, FAIL or UNVERIFIABLE with the executed
SQL, the bound parameters and the row counts. This document is the design in one place:
the three walls and the tests that hold them, the abstention philosophy, the benchmark
method, the five findings that changed the tool, the threat model, and the honesty
section, which says what Recount does not do and who did the neighbouring things first.

Companion documents: [abstention.md](abstention.md) (the compiler's specification, row
by row), [benchmark.md](benchmark.md) (the corruption benchmark and its changelog),
[eval.md](eval.md) (the extraction eval), [cli.md](cli.md) (commands, exit codes, the
Action), [learning-log.md](learning-log.md) (one dated line per design decision).

## 1. The pipeline

```
report.md ──► extract (LLM, one call, JSON schema) ──► validate + reject ──► sweep
                                                              │
metrics.yml ──► compile (Claim × SemanticConfig → ComputePlan | Abstain)
                                                              │
orders.parquet ──► load + validate schema ──► execute (fixed SQL template, bound params)
                                                              │
                                                    policy (half-ulp, direction, rank)
                                                              │
                                              verdict ──► JSON / table / HTML / exit code
```

- **Extract** (`src/recount/extract/`): one structured-output call per artifact at
  temperature 0, response schema derived from the Claim models. The model sees the
  report and nothing else: not the dataset, not the config.
- **Validate and reject** (`extract/extractor.py`): every wire object is re-validated
  through the frozen, `extra="forbid"` Claim models; a span that is not a verbatim
  substring of the report, a duplicated span or id, a field the type does not declare,
  a comparison or growth value written as a level rather than a difference: each is
  *rejected*, recorded, and its numbers fall to the sweep. Nothing is repaired.
- **Sweep** (`extract/sweep.py`): every numeric token no accepted claim binds is reported
  as unextracted, so a missed claim is a visible gap and `--strict` can fail on it.
- **Compile** (`compile/compiler.py`): resolves metric, entity, period and polarity through
  the config only, and abstains with a reason code wherever the table in
  [abstention.md](abstention.md) says so.
- **Execute** (`verify/engine.py`): five SQL templates, one per plan kind. Column names are
  quoted identifiers the loader validated against the real schema; every value is a bound
  parameter.
- **Policy** (`verify/policies.py`): direction before magnitude; half-ulp tolerance read
  from the decimals as written in the span; rank equality; NULL and empty-slice semantics
  made explicit as `no_data`.
- **Report** (`report/`): the run record (input hashes, versions, every claim beside its
  verdict), the terminal and Markdown tables, and a single-file HTML with an evidence
  drawer. The HTML reads only the run record, so `--json` and `--html` cannot disagree.

## 2. The three walls

The thesis is a hard boundary between probabilistic and deterministic code. Each wall is
one sentence, and each has a test that fails the build if it is breached. The tests in
`tests/architecture/test_walls.py` are never edited to make a change pass
(`CLAUDE.md` §0).

### Wall 1 — dataset ⇸ prompt

*Dataset contents never enter any prompt on the verification path.* The extractor reads
the report; the compiler and engine read the dataset; no module does both.

- `tests/architecture/test_walls.py::test_wall_1_no_llm_imports_outside_extract` walks the
  AST of every module under `src/recount/` and fails on an LLM client import anywhere but
  `extract/` and the eval-only `bench/baseline_judge.py`.
- `tests/adversarial/test_injection.py::test_instruction_in_a_cell_moves_no_verdict`
  (Hypothesis, 300 random tables) seeds instruction strings into random cells and requires
  every verdict outside the seeded rows' slice to be byte-identical. The benchmark's
  `instruction_in_data` class is the same property on the Olist example, 5/5 invariant
  (`tests/bench/test_corrupt.py::test_instruction_in_data_is_composite`).
- `src/recount/extract/prompt.py` is a constant. Its examples are about an invented widget
  report, so the extraction eval is not contaminated by its own answers.

The one deliberate exception is the benchmark's LLM-as-judge *baseline*: it receives a
deterministic aggregate summary of the public example data so that the head-to-head is
fair, in `bench/baseline_judge.py` only, and its output never touches a Recount verdict.
The exception is written into `CLAUDE.md` §0 and the README rather than hidden.

### Wall 2 — text ⇸ verdict

*Artifact text never influences a verdict except through a schema-validated Claim.* A
verdict is a function of (claim, dataset, config). The report reaches the pipeline in two
places only: the extractor, which has no verdict authority, and the verbatim-span check.

- `tests/adversarial/test_injection.py::test_injected_phrasings_between_paragraphs_change_no_verdict`:
  ten injection phrasings, each inserted at the top, middle and bottom of the example
  report, with the extraction held fixed through the offline claims path; every verdict and
  every executed SQL string is identical to the clean run.
- `tests/adversarial/test_injection.py::test_a_phrasing_inside_a_span_rejects_that_claim_and_nothing_else`:
  the only thing an injected phrase can do is break the span it lands in, and that claim is
  rejected, not repaired.
- `tests/adversarial/test_injection.py::test_hostile_wire_fields_are_foreign_and_rejected`:
  an extractor response carrying `verdict`, `override` or `sql` keys is rejected object by
  object, because every Claim model forbids extra fields.
- The rejection paths themselves: `tests/extract/test_extractor.py` (`test_rejects_span_not_verbatim`,
  `test_rejects_a_non_null_field_the_type_does_not_declare`,
  `test_rejects_every_claim_sharing_a_span`, …).

Two doors in this wall are open on purpose, and both can only *narrow* a verdict:
`verify/policies.py: stated_decimals` reads the written precision off the span so "6.00%"
is held to ±0.005 rather than ±0.5 (benchmark changelog 2), and the compiler's echo gate
M3 refuses a metric binding the span does not name in the config's vocabulary (changelog
5). Neither can turn a FAIL into a PASS.

### Wall 3 — plan ⇸ code

*SQL exists only as fixed templates, parameterized; no `eval`, no `exec`, no dynamically
built SQL anywhere.* A `ComputePlan` is a closed-world typed object (`compile/plans.py`):
resolved column names, half-open dates, a group key. It carries no SQL and no claim text.

- `tests/architecture/test_walls.py::test_wall_2_no_dynamic_sql_or_eval` scans every source
  file for `eval(`/`exec(` calls and f-strings containing SQL keywords.
- `tests/architecture/test_walls.py::test_wall_3_src_never_imports_test_scaffolding` keeps
  production code from importing anything under `tests/`.
- `tests/verify/test_engine.py::test_sql_text_never_contains_claim_text_or_values` and
  `tests/security/test_hostile_inputs.py` (forty parametrised cases): SQL-injection-shaped
  entity aliases, stored values, metric aliases, claim fields, column names and cell values
  go through the whole compile → verify path; the executed SQL never contains them, the
  `data` table is intact afterwards, and a hostile column name comes out as a correctly
  doubled-quote identifier.
- Determinism is the same wall seen from outside: `tests/test_determinism.py` requires the
  run record, HTML and Markdown to be byte-identical across two processes (timings aside)
  and every verdict invariant under a shuffled row order; CI re-runs the benchmark from
  the committed recordings and fails if the README table or the results JSON drifts.

## 3. Abstention: why UNVERIFIABLE is a verdict

A false PASS is the one unforgivable failure. A verifier that guesses when it does not
know produces exactly that, so the compiler abstains, with a reason code grouped by what
the user can do about it:

| reason | meaning | what fixes it |
|---|---|---|
| `schema_gap` | the config lacks the metric, entity, dimension or polarity the claim needs | a line of YAML; the verdict `detail` names the key and the HTML drawer offers a stub |
| `ambiguous` | the sentence is irreducibly vague (no baseline, no number, no scope) | a rewrite of the sentence |
| `unsupported_claim_type` | the sentence is precise; the tool lacks the capability (rank change, "overtook") | an issue |
| `no_data` | the slice is empty, the growth baseline is zero, the subject is not among the groups | check the period, the entity, or the data |

The full decision table, written before the compiler and reviewed row by row, is
[abstention.md](abstention.md). Three things about it matter more than any row:

1. **Evaluation order is a spec decision.** Schema gaps are reported before vagueness,
   because a schema gap is the one abstention fixable in YAML, and once fixed the vagueness
   surfaces honestly on the next run.
2. **The table never grows a guess.** When a situation is not in it, the compiler abstains
   `ambiguous` and the row is added first. The spike's silent "previous quarter" baseline
   fallback is the canonical example of what is not allowed.
3. **Abstention has a measured cost, and the cost is published.** The echo gate (M3)
   turned two fabricated-metric false accepts into abstentions and, in the same move, took
   nine detections and five clean PASSes to `metric_echo_failed`; both numbers are in
   [benchmark.md](benchmark.md) changelog 5. Detection is never reported without coverage
   and abstention in the same row.

## 4. Benchmark methodology

[benchmark.md](benchmark.md) is the full specification; this is the shape.

- **Frozen taxonomy.** Seven corruption classes (`wrong_figure`, `flipped_direction`,
  `wrong_ranking`, `swapped_entity`, `fabricated_metric`, `rounding_drift`,
  `instruction_in_data`) frozen in Stage 1, before any verifier existed
  (`tests/claims/test_model.py::test_corruption_taxonomy_is_frozen`).
- **Seeded generators.** Each class has one construction anchored to a hand-made spike
  example: transposed digits, an antonym from a fixed table, an ordinal swap, another
  state's true value, a metric phrase from a fixed substitution table, a last-digit drift
  asserted to lie outside the tolerance, a parameterized cell update. Five seeds, 120
  variants plus the clean report; `generate(seed)` is a pure function
  (`tests/bench/test_corrupt.py::test_same_seed_is_byte_identical`) and the suite is
  generated from a committed config snapshot whose hash is pinned
  (`test_suite_is_frozen_to_the_stage5_hash`).
- **Metrics co-reported.** Per class: detection over *all* variants (never only the
  extracted ones), detected-by-abstention (the expected outcome for a fabricated metric),
  false accepts, coverage, abstention rate, sweep-flagged misses, collateral false flags on
  untouched sentences, and the same artifacts through the judge.
- **The judge baseline** is the same model, temperature 0, one call per artifact, handed a
  deterministic aggregate summary of the data as an answer key. The comparison is
  deliberately generous to the judge.
- **Replay, not fixtures.** Every live response is recorded with a fingerprint over
  (model, prompt, artifact, schema); CI replays the whole extractor from the recordings
  and refuses a stale one, so a prompt edit breaks CI loudly instead of quietly aging the
  README.
- **Integrity rule.** Every post-freeze change to the verifier, compiler or extractor is a
  numbered changelog entry with before/after numbers (seven so far). No seed is re-drawn
  to remove a false accept.

Final numbers, default config, `gemini-3.1-flash-lite` for extractor and judge:

| | Recount | judge with the answer key |
|---|---|---|
| detection, exact-match classes (n = 100) | 79 % | 100 % |
| false accepts, exact-match classes | 0 | 0 |
| fabricated metric caught by abstention (n = 20) | 19 | n/a (no abstain path) |
| coverage (a claim on the corrupted span) | 98 % | n/a |
| abstention rate | 22 % | 0 % |
| clean report (51 claims) | 40 PASS / 0 FAIL / 11 UNVERIFIABLE | judged unfaithful |
| problems raised on correct spans, all 121 artifacts | 0 | 80 |
| pointed at the corrupted span | every detection | 64 % |
| verdict comes with executed SQL + row counts | yes | no |

The judge's 100 % is a prior, not a detector: it also calls the clean report unfaithful.
Recount's 79 % is lower and means something, because it comes with a computed value, an
executed query, and zero false flags on the same clean report.

## 5. Five findings, in order

The benchmark exists to find these. Each was written down before it was acted on, and each
change was replayed on the same recordings.

- **F-1, precision is lost at the float boundary.** Seen in the oracle run before any live
  call: "6.00%" arrives as the float 6.0, so the tolerance became ±0.5 and three
  rounding-drift variants PASSed. Fixed after the live run reproduced it (changelog 2):
  the decimals are read off the verbatim span. Exact-match false accepts 3 → 0.
- **F-2, the extractor can launder a fabricated metric into a real one.** "Average return
  time of just 9.3 days" was bound to `avg_delivery_days` and PASSed at 9.305; two of
  twenty. No verifier change can reach a Claim that is internally consistent, so the fix is
  a refusal: the echo gate M3 (changelog 5). False accepts 2 → 0, at a cost of nine
  detections and five clean PASSes, all itemised.
- **F-3, rankings abstain because the sentence names no measure.** "Secured the second
  position overall": 0/15 detected, 15/15 abstained `schema_gap`, 0 false accepts. Adding
  an "overall" alias after seeing the table would be the self-serving move, so it ships
  commented out and is measured both ways (changelog 6): 14/15 on the Stage 5 verifier,
  5/15 on the Stage 6 one, because an alias can only attach to a word that is there.
- **F-4, collateral false flags come from one unstable extraction pattern.** 85 FAILs on
  untouched sentences across 48 variants and 0 on the clean report, all from the model
  typing "to stretch to 14.28 days" as a comparison carrying the *level*. Temperature 0 did
  not make extraction a function of the text. Fixed by a reject-don't-repair post-check
  (changelog 3): 85 → 0.
- **F-5, a rejected claim's number can be sweep-silent.** "17,280 refunds" was rejected and
  its number sat inside a neighbouring claim's span. Fixed by token-to-field coverage in
  the sweep (changelog 4): a number a span merely encloses is flagged.

The pattern across all five: the LLM's output validated against the schema every time, and
every finding lived in the gap between shape and meaning. The fixes are all refusals or
precision, never guesses, and the detection number went 83 → 74 → 79 along the way with
each step written down.

## 6. Threat model

Threat ids are cited from code comments and tests.

| id | threat | mitigation | enforced by |
|---|---|---|---|
| T1 | prompt injection via the report | the extractor has no verdict authority; verdicts come from code that never reads text | `tests/adversarial/test_injection.py` (ten phrasings × three positions) |
| T2 | instruction in a data cell | cells are only ever aggregated or compared as values; nothing from the dataset enters a prompt | Hypothesis property in `test_injection.py`; benchmark class 7 |
| T3 | code smuggled through config or claims | `yaml.safe_load`, `extra="forbid"` models, no eval/exec, closed-world plans | `test_config_with_a_python_tag_is_refused_as_invalid_yaml`; wall 2 test |
| T4 | SQL injection through names | values bound as parameters; identifiers quoted after schema validation | `tests/security/test_hostile_inputs.py`, `tests/verify/test_engine.py` |
| T5 | dataset exfiltration via the provider | only report text is sent; `--claims` runs fully offline; free-tier terms stated in `CLAUDE.md` | wall 1 test |
| T6 | key leakage | env-only keys, `.env` git-ignored, keys never in PR CI (recordings instead) | `.github/workflows/verify-reports.yml` |
| T7 | resource exhaustion | caps: 1 GiB / 100 M rows for the dataset, 1 MiB for the report, one call per artifact | `test_dataset_caps_are_a_one_line_exit_2`, `test_oversized_artifact_is_refused_before_any_extraction` |
| T8 | dependency compromise | `uv` lockfile, seven runtime dependencies, `pip-audit` enforcing in CI | `ci.yml` |
| T9 | a PR edits the gate it is subject to | required check + code-owner review on `.github/`, `action.yml`, `Dockerfile` | `.github/CODEOWNERS`; branch protection on `main` |
| T10 | self-serving benchmark | taxonomy frozen before tuning, coverage and abstention co-reported, changelog discipline, judge on identical artifacts | `test_corruption_taxonomy_is_frozen`, `test_suite_is_frozen_to_the_stage5_hash` |

Injection resistance here is an architectural property that is tested, not security
research that is claimed.

## 7. What Recount does not do

- It does not make the generator hallucinate less. It makes hallucinated *numbers*
  detectable and blocking, after the fact.
- It is not "zero AI". The extraction step is an LLM. Only the verification step is
  deterministic, and the extractor's misses and wrong bindings are the largest residual
  risk: measured as recall 0.96 / 0.89 on the two models (eval.md) and as the
  `swapped_entity` and `fabricated_metric` classes.
- It verifies against the config's definition of a metric. A wrong `metrics.yml` yields
  confidently wrong verdicts; Recount cannot know that "revenue" should have excluded
  freight.
- It does not read the clock or infer periods. "Last quarter" abstains.
- It does not check rank changes ("overtook"), COUNT DISTINCT metrics, shares of averages,
  or claims about periods partly outside the data (a documented false-PASS path,
  abstention.md §5: today the query runs over the rows present; the planned fix abstains
  `no_data` on partial coverage).
- Its benchmark is one dataset, one report style, seven classes and five seeds. The
  `flipped_direction` pool has five distinct claims. The numbers are reproducible, not
  general.
- Extraction is not a function of the text even at temperature 0 (F-4). Recordings make
  CI deterministic; a live run is not.

## 8. Prior art

Recount is not the first system to verify numbers in generated text, to re-derive figures
from data, to ship a seeded-corruption benchmark, or to verify claims against a database.
Each of these exists, and each solves a constrained slice:

| system | what it does | what Recount does differently |
|---|---|---|
| **VeriFin** (arXiv [2608.10213](https://arxiv.org/abs/2608.10213)) | grounds operands in XBRL facts and checks financial claims with an SMT solver; Verified / Violated / Abstain; zero false accepts on its benchmark | finance and XBRL only, fixed QA claims. Recount borrows the discipline (ground independently, then re-derive; Abstain as a first-class verdict) for free-text reports over arbitrary CSV/Parquet |
| **Deterministic Integrity Gates** (arXiv [2606.09500](https://arxiv.org/abs/2606.09500)) | zero-AI exact-match verification of numeric claims in clinical manuscripts against manifest-locked tables, with a seeded-defect benchmark | the closest system on both signature axes, clinical-specific and against locked tables. Recount is the general, dataset-agnostic, installable version; the seeded-defect benchmark pattern is theirs first |
| **Thucy** (arXiv [2512.03278](https://arxiv.org/abs/2512.03278)) | multi-agent claim verification over relational databases; agents write and run SQL and return it as evidence | the SQL-as-evidence output is the UX Recount adopts; Thucy's verdict is still LLM-mediated and its SQL is free-form, which is exactly what Recount's templated plans exist to avoid |
| **Evergreen** (arXiv [2604.26180](https://arxiv.org/abs/2604.26180)) | claim verification as semantic query processing: each claim compiled to a declarative query with provenance | the conceptual sibling of Recount's compiler, over text corpora with per-tuple LLM calls; Recount keeps the compile-to-query idea and removes the LLM from execution |
| **Proof-Carrying Numbers** (arXiv [2509.06902](https://arxiv.org/abs/2509.06902)) | render-time verification of pre-tagged numeric tokens under policies (exact / rounded / alias / tolerance), fail-closed | no extraction from free text and no re-derivation from a raw dataset; Recount's policy vocabulary and fail-closed default follow PCN, and Recount could sit behind a PCN-style renderer |
| **FinGround** (arXiv [2604.23588](https://arxiv.org/abs/2604.23588)) | atomic claim decomposition with type-routed verification, including arithmetic recomputation, for SEC filings | finance-only, learned verdict models, no public code; its finding that existing detectors miss most computational errors is the problem statement Recount works on |

To my knowledge, what Recount packages that these do not is the assembly: free-text claim
extraction → deterministic re-derivation over an arbitrary tabular dataset →
PASS / FAIL / UNVERIFIABLE with the executed SQL, as a library, a CLI, a CI gate and a
promptfoo assertion, evaluated on a reproducible seeded-corruption benchmark that reports
coverage and abstention next to detection. That sentence is hedged on purpose, and the
table above is where a reader should start checking it.
