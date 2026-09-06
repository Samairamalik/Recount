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
- Dataset contents never enter any prompt. Artifact text never influences a
  verdict except through schema-validated Claim objects.
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
Current stage: Stage 3 complete — compiler + abstention
Done: docs/abstention.md is the reviewed decision table (rows M/E/G/D/V/X/P/N, config rules C1–C5,
fixture amendments F1–F3; V6 authored by the owner); compile/compiler.py matches it row for row with
row ids in comments; compile/periods.py (half-open years/quarters/months/days, 'A to B' ranges,
bare-hyphen ranges refused, no relative periods); config norm() + metric_index/entity_index (accents,
case, stored values resolve; uniqueness across dimensions; 'unspecified' reserved; share metrics take
no column); verify.verify_claim() (Abstain → UNVERIFIABLE verdict with empty sql/params).
Stage 1 amendments (logged): Ranking.scope (universe as written), Comparison.value ge=0. Fixture
relabels: c1 → schema_gap, c11 displaced='unspecified' → unsupported_claim_type, c23 scope='2017'.
Goldens: all 57 fixture claims end-to-end through compiler → engine (45 PASS / 6 FAIL / 6 UNVERIFIABLE
with expected reasons); tests/verify/_fixture_plans.py retired. Binding tests by name:
test_binding_a_better_worse_without_polarity_is_schema_gap,
test_binding_b_time_grain_group_by_resolves_from_time_column_never_entities.
Next: Stage 4 — extractor (Gemini structured output behind ExtractorClient Protocol, temp 0, one retry,
span enforcement, mock) + numeric sweep + mini-eval vs the labels. Extractor contract must emit the
period grammar of docs/abstention.md §P, `scope` for time-grain rankings, `displaced` for overtaking.
Open questions: docs/recount_claude_code_guide.md C1 still says anthropic/ANTHROPIC_API_KEY; CLAUDE.md §0 (Gemini) wins.
Known false-PASS path (documented, abstention P12): periods partly outside the data range compute over
the rows present; V2 engine TODO queries min/max of time_column and abstains no_data. G7 (year rankings
withheld as no_data) is the stopgap. COUNT DISTINCT metrics (c1) deferred.
