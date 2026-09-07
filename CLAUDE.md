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
Current stage: Stage 6 complete pending the owner's look at the blocked demo PR (STOP 2) — parts A and B committed and
pushed; stop before Stage 7.
Done (Stage 6 A, all keyless replays on the Stage 5 recordings, suite hash unchanged): changelogs 3–7 in
docs/benchmark.md §6: (3) extractor rejects a comparison/growth value written as a level (collateral false flags
85 → 0); (4) token-to-field sweep (sweep-silent 1 → 0); (5) compiler echo gate M3, fixture amendment F5 (echo_gap;
pools untouched): fabricated_metric false accepts 2 → 0; (6) F-3 "overall" aliases commented-out opt-in, alias-on
replayed both ways (14/15 on Stage 5, 5/15 on Stage 6); (7) `days for delivery` default alias, `delivery
performance` opt-in, suite generated from frozen bench/suite_config.yml (hash pinned). Final default table C:
exact-match detection 79/100, false accepts 0, collateral 0, abstention 21.9%, clean 40 PASS / 0 FAIL / 11 UNV.
Done (Stage 6 B): `recount verify` (--json/--html/--md/--strict/--annotations; --claims fully offline,
--recording/--recordings keyless replay), exit codes 0/1/2 with one-sentence exit-2 messages citing YAML lines
(docs/cli.md); `recount init --data` commented template (config/template.py); report/ (run record with hashes and
timings, Rich + Markdown tables, Jinja2 static HTML with evidence drawer + YAML stubs); pipeline.verify_text with
partial results on a crashed claim; adapters/promptfoo.get_assert + examples/promptfoo worked example; docker
action.yml + Dockerfile + .github/workflows/verify-reports.yml (replays committed recordings: keys never in PR CI);
examples/olist/{report.md,metrics.yml}; README quickstart reproduced from a clean-venv wheel install. Demo PR #1
(demo/corrupted-report: Sao Paulo revenue 2,428,002.62 → 4,228,002.62, variant s1-wrong_figure-c31).
Next: Stage 7 — Hypothesis suites (no-false-accept, round-trip truth, instruction-in-data invariance, byte-identical
determinism), hostile-input tests, docs/design.md, demo GIF, v0.1 tag; gate G5 = PRD §1.16. Deployment note: mark
verify-reports required in branch protection + CODEOWNERS on .github/ and action.yml (T9), owner's call.
Open questions: docs/recount_claude_code_guide.md C1 still says anthropic/ANTHROPIC_API_KEY; CLAUDE.md §0 (Gemini) wins.
Known false-PASS path (documented, abstention P12): periods partly outside the data range compute over
the rows present; V2 engine TODO queries min/max of time_column and abstains no_data. G7 (year rankings
withheld as no_data) is the stopgap. COUNT DISTINCT metrics (c1) deferred; the sweep flags "27 states".
Benchmark integrity: taxonomy frozen (test_corruption_taxonomy_is_frozen); every post-freeze change to
verify/compile/extract is a numbered entry in docs/benchmark.md §6 with before/after numbers (six so far).
