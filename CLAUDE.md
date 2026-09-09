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
Current stage: Stage 8 (v0.2.0) — the v0.1.0 acceptance run on unseen data, ruled and fixed.
Done (Stage 8, 2026-09-08), in the owner's order:
1. **F-3 rank direction** — `Ranking.rank_from` (highest/lowest/best/worst) carries the end the sentence
   names; `polarity` keeps only "which way is better". Abstention G12 (null → ambiguous), G9 narrowed to
   best/worst, `RankPlan.polarity` → `order`. Fixture amendment F6 (all five ranking labels are `best`).
2. **F-4 ranking support and the report's hedge** — `metrics.<m>.min_rows` (default None; `recount init`
   writes an active 30 on avg metrics), a second ranking template that ranks only supported groups and
   returns the rest with a NULL rank, engine row N5 (below-threshold subject abstains `no_data`, never
   FAILs — trade-off argued in docs/design.md §3), G11 rewritten so an entity ranking's stated universe
   is refused honestly, prompt carries it into `scope`.
3. **F-1 alias matching** — docs fixed (full-string after normalisation, never a substring), not the code;
   `schema_gap` details now print the YAML line to paste.
4. **F-6 HTML spans** — innermost-wins segmentation so nested spans render; anything still unpainted is
   named in the header, so the counts always reconcile with the page.
5. **Docs sweep** — default model stated and reconciled with the benchmark's, `recount --version`, `.env`
   documented, an Install-and-develop section (uv, Python ≥3.12, `uv run pytest`), and the honesty note
   that extraction non-determinism can flip a verdict, not only coverage (F-5).
6. **F-7 backoff** — transient 5xx/429/transport retried with exponential backoff (4 attempts, 1/4/16 s),
   reported as `upstream unavailable`, distinct from an unusable response; content failures unchanged.
Sequencing (owner's ruling): the keyless oracle before/after ran first with extraction held fixed — **no
number moved**, suite hash unchanged — and only then was the live re-record started (the prompt and wire
schema changed, which stales every recording by construction). The docs/eval.md honesty gate was re-run
first and passed (flash-lite recall 0.8947 / precision 1.0, both unchanged; default model recall 0.9649,
precision 0.873 -> 0.9821). Changelog entries 8-9 are committed.

The re-record completed on 2026-09-09 (16 remaining calls; the provider had degraded the
previous day and recovered). All 96 extraction recordings and the 3 eval fixtures are on the
Stage 8 prompt and schema; the judge's 101 are untouched, so the head-to-head baseline is
unchanged. Changelog entries 8-14 carry the before/after; table E in §7 is the v0.2.0 run.
**v0.1.0 -> v0.2.0, and all of it is extraction:** exact-match detection 79/100 -> 76/100,
detected-by-abstention 19 -> 18, unextracted 3 -> 7, **false accepts 0 -> 0, collateral
0 -> 0**, abstained 19 -> 19, suite hash unchanged, clean report identical (51 claims, 40
PASS / 0 FAIL / 11 UNVERIFIABLE, recall 0.8947, precision 1.0). Exactly 4 of 120 variants
changed outcome and all four are the same claim, c27. Items 3-6 were A/B'd on the identical
recordings and are byte-identical. The alias-on row fell 5/15 -> 0/15 because this
extraction words the ranking metric `commercial performance` everywhere; no alias was added
after seeing the table (I2 / T10).

Also: docs/design.md §9 "Acceptance testing on unseen data"; `examples/chicago/` as a reference (not
runnable: the 66 MB dataset is rebuilt by its script, and a sample would verify nothing).
Next: unchanged V2 items — P12 data-coverage abstention, COUNT DISTINCT metrics, rank-change verification
(G10). F-2 (dimension aliases) and F-12/F-14 from the acceptance report are open and not scoped here.
Known false-PASS path (documented, abstention P12): periods partly outside the data range compute over
the rows present; V2 engine TODO queries min/max of time_column and abstains no_data. G7 (year rankings
withheld as no_data) is the stopgap; `min_rows` narrows one corner of it and replaces neither.
Benchmark integrity: taxonomy frozen (test_corruption_taxonomy_is_frozen); every post-freeze change to
verify/compile/extract is a numbered entry in docs/benchmark.md §6 with before/after numbers.
