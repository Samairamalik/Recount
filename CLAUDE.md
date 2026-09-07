# CLAUDE.md — Recount

Behavioral guidelines to reduce common LLM coding mistakes, plus this project's
non-negotiable invariants. **Tradeoff:** these bias toward caution over speed.
For trivial tasks, use judgment — but the invariants in §0 always apply.

## 0. Project & invariants (never violate; flag if a task seems to require it)

Recount verifies numeric/comparative/ranking claims in LLM-generated reports
against the source dataset, DETERMINISTICALLY. The thesis is a hard wall between
probabilistic and deterministic code. Protecting that wall outranks any feature,
refactor, or convenience.

- Only `src/recount/extract/` and `src/recount/bench/baseline_judge.py` may import
  an LLM client. Wall-tests in `tests/architecture/` enforce this. Never edit those
  tests to make a change pass.
- SQL exists only as fixed templates in `verify/engine.py`, parameterized.
  No f-string/concat SQL anywhere. No `eval`/`exec` anywhere.
- Dataset contents never enter any prompt on the verification path — the extractor
  sees artifact text only. Sole exception: the eval-only judge baseline
  (bench/baseline_judge.py) receives a deterministic aggregate summary of the public
  example data; it exists to make the comparison fair and its output never touches
  a Recount verdict. (Amended Stage 5, ruling J4; logged in docs/learning-log.md.)
  Artifact text never influences a verdict except through schema-validated Claim objects.
- The compiler abstains (reason-coded) instead of guessing. Never "improve"
  abstentions into best-effort guesses. A false PASS is the one unforgivable failure.
- Provider: Gemini API (free tier) via `google-genai`, behind the `ExtractorClient`
  Protocol, structured output (`response_schema`) only. Free tier may use inputs
  for product improvement, so "dataset never enters a prompt" is doubly binding.
  One call per artifact, never per claim.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- State what you'll build, files touched, and the test plan. Wait for approval.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.
- If uncertain about API behavior, SQL semantics, or date edge cases, say so
  rather than guessing.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- No new dependencies without flagging as a QUESTION first.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## STATUS (update at the end of every session)
Current stage: Stage 6 part A complete — benchmark-driven fixes replayed (changelogs 3–7), owner's rulings on the
tables folded in (changelog 7); part B (packaging) in progress.
Done (Stage 6 A, all keyless replays on the Stage 5 recordings, suite hash unchanged): (3) extractor rejects a
comparison/growth value written as a level (`value_not_a_difference`): collateral false flags 85 → 0; (4) sweep is
token-to-field (`sweep(artifact, coverage(claims))`, NumericToken.value): sweep-silent 1 → 0, +1.28 flagged tokens
per artifact, all "17,280 orders"; (5) compiler echo gate M3 (span must name the bound metric; share may name its
row-count denominator; evaluated last; the compiler now reads `span` for this one refusal): fabricated_metric false
accepts 2 → 0, exact-match detection 83 → 74 (9 lost to two unaliased wordings), abstention 16% → 26%, clean
43 → 38 PASS / 0 FAIL; fixture amendment F5 (`echo_gap` on nine labels, expected_verdict untouched so pools are
frozen); (6) F-3 "overall" aliases shipped commented out in tests/fixtures/olist_metrics.yml, alias-on copy
measured both ways: 14/15 on the Stage 5 verifier, 5/15 on the Stage 6 one (M3 refuses the spans with no wording).
`recount bench --config`; CI replays and diffs latest.alias-on.json too. (7) owner's split ruling: `days for
delivery` is a default alias of avg_delivery_days (exact-match 74 → 79, clean 40 PASS / 0 FAIL / 11 UNV, abstention
21.9%), `delivery performance` a second commented-out opt-in; the alias grew the fabricated_metric pool and would
have re-sampled the suite, so generation now reads the frozen bench/suite_config.yml (hash pinned by test).
docs: benchmark.md §0/§5–7 (tables C, D, progression), abstention.md (contract, M3, F5), eval.md Stage 6
addendum, learning-log ×4.
Next: Part B: `recount init --data`, exit codes 0/1/2 + --strict + docs, Jinja2 HTML report (4h box), promptfoo
`recount-verify` assertion + example, Dockerized GitHub Action + demo PR blocked by a corrupted report; STOP at the
blocked PR; end-of-stage quiz (a)(b)(c); STATUS; stop before Stage 7.
Open questions: docs/recount_claude_code_guide.md C1 still says anthropic/ANTHROPIC_API_KEY; CLAUDE.md §0 (Gemini) wins.
Known false-PASS path (documented, abstention P12): periods partly outside the data range compute over
the rows present; V2 engine TODO queries min/max of time_column and abstains no_data. G7 (year rankings
withheld as no_data) is the stopgap. COUNT DISTINCT metrics (c1) deferred; the sweep flags "27 states".
Benchmark integrity: taxonomy frozen (test_corruption_taxonomy_is_frozen); every post-freeze change to
verify/compile/extract is a numbered entry in docs/benchmark.md §6 with before/after numbers (six so far).
