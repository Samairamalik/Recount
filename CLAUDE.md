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
Current stage: Stage 2 complete — deterministic verification engine
Done: io/loader.py (CSV/Parquet → DuckDB `data`, schema validated against SemanticConfig, byte/row caps),
compile/plans.py (frozen ComputePlan union: aggregate/growth/compare/rank/share; resolved columns,
half-open Periods, EntityKey|TimeKey group keys), verify/engine.py (ONE constant SQL template per plan
kind; identifiers from validated plans, keywords from Literals, all data as bound params),
verify/policies.py (half_ulp in Decimal, per-metric ROUND in SQL, direction-before-magnitude for
growth/comparison, RANK with ties, AVG NULL semantics documented), verify/verdict.py.
AbstainReason gained NO_DATA (visible amendment, see learning-log). examples/olist/orders.parquet
committed (CC BY-NC-SA, ATTRIBUTION.md). Goldens: 52/57 fixture claims verify to label incl. all 6
corruptions for the right reason; Hypothesis: round-trip PASS, beyond-tolerance FAIL (1k cases),
flipped-direction FAIL. Wall 3 added: src/ never imports test scaffolding (tests/verify/_fixture_plans.py).
Next: Stage 3 — abstention decision table (doc first), compiler.py: alias resolution, period parsing
(quarters/months/years/ranges), polarity for better/worse (schema_gap if absent), time-grain group_by,
c11-style missing-baseline → ambiguous. Replaces tests/verify/_fixture_plans.py.
Open questions: docs/recount_claude_code_guide.md C1 still says anthropic/ANTHROPIC_API_KEY; CLAUDE.md §0 (Gemini) wins.
Fixture claims the engine cannot plan (compiler's job): c1 (COUNT DISTINCT metric), c5/c7 (no baseline period), c30 (no region entity).
