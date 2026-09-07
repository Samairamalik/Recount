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
Current stage: Stage 5 complete — corruption benchmark + judge baseline (measured, committed, CI keyless)
Done: src/recount/bench/ — corrupt.py (seven seeded generators on the frozen taxonomy, 120 variants +
clean, seeds 1–5, byte-identical; class 7 is composite: a wrong_figure artifact + one injected cell),
summary.py (the judge's deterministic aggregate summary, fixed SQL), baseline_judge.py (the only
eval-only AI; same ExtractorClient seam, recorded/replayed like the extractor), metrics.py (M1 hit rule,
M2 outcomes, M11 rows), runner.py (recordings keyed by sha of what the model saw, resumable, throttled;
README table between BENCH markers; results JSON with latency). src/recount/cli.py with only `bench`
(Stage 6 preview). tests/bench/ incl. an oracle client (perfect extraction = the verifier's upper bound,
pinned). docs/benchmark.md is the contract (rows I/B/M/J/C/F), findings and §7 results; docs/eval.md
has the Stage 5 addendum. CI: `recount bench --write-readme` replay + `git diff --exit-code`.
Live run 2026-09-07 on gemini-3.1-flash-lite (extractor AND judge; the default pin stays
gemini-3.6-flash, whose free tier is 5 RPM / 20 RPD): 197 calls. Results (table A): exact-match
detection 83/100, false accepts 0/100, coverage 98/100; clean report 43 PASS / 0 FAIL / 8 UNV;
fabricated_metric 17/20 detected-by-abstention + 2 false accepts (F-2); wrong_ranking 0/15 detected,
15/15 abstained schema_gap (F-3); collateral false flags 85 on 48 variants, 0 on clean (F-4); judge
120/120 "unfaithful" incl. the clean report, 80 false flags, 64% localized, 0/5 suppressed by injection.
Changelog: (1) wire schema every key required-but-nullable (flash-lite recall 0.5965 → 0.8947,
3.6-flash unchanged 0.9649, both re-recorded); (2) stated precision read off the span
(rounding_drift 17/20 + 3 false accepts → 20/20 + 0), applied only after the "before" table.
Next: Stage 6 — CLI exit codes, `recount init`, HTML report (4h box), promptfoo assertion, GitHub
Action + demo PR. Rulings owed first: F-2 metric-echo check (extract/), F-3 config alias for "overall"
(owner's config call), F-4 comparison-value semantics vs a prompt clarification.
Open questions: docs/recount_claude_code_guide.md C1 still says anthropic/ANTHROPIC_API_KEY; CLAUDE.md §0 (Gemini) wins.
Known false-PASS path (documented, abstention P12): periods partly outside the data range compute over
the rows present; V2 engine TODO queries min/max of time_column and abstains no_data. G7 (year rankings
withheld as no_data) is the stopgap. COUNT DISTINCT metrics (c1) deferred; the sweep flags "27 states".
Benchmark integrity: taxonomy frozen (test_corruption_taxonomy_is_frozen); every post-freeze change to
verify/compile/extract is a numbered entry in docs/benchmark.md §6 with before/after numbers.
