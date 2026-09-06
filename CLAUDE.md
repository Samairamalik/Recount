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
Current stage: Stage 4 complete — extractor + sweep + extraction eval
Done: src/recount/extract/ (the only LLM zone): client.py (ExtractorClient Protocol; GeminiClient pinned
to gemini-3.6-flash, temperature 0, response_json_schema, key from env/.env; MockClient replays a
recording bound to model+prompt+artifact+schema hashes and refuses a stale one; RecordingClient),
prompt.py (rewritten against the 57 labels; invented-domain few-shots; period grammar of abstention §P,
scope/displaced/unsigned-magnitude contracts), extractor.py (wire schema derived from the Claim models
with per-class enum union; Pydantic re-validation; REJECT never repair: span not verbatim, duplicate
span/id, foreign non-null field, invalid claim; one retry that is not expected to fix content-level
failures), sweep.py (numeric tokens incl. 1,41,834 / R$1,447,714.17 / 1.42M / 12.4%; bare 1900–2099
skipped as years), eval.py (d7 matching policy: first-occurrence overlap, one-to-one), record.py
(python -m recount.extract.record ARTIFACT OUT). src/recount/pipeline.py: run(artifact, cfg, dataset,
client) -> extraction + verdicts. Recordings in tests/fixtures/extract/{report,report_clean}.json.
Eval (docs/eval.md, pinned by tests/extract/test_eval.py): recall 0.9649 (55/57), precision 0.8871
(55/62), span validity 1.0, 0 false accepts, 0 false flags, subject 28/28, period 55/55, direction 10/10.
One iteration, a bug not a prompt change: the flat wire schema took `direction` from Growth alone so
comparisons could never be emitted (iteration 1: recall 0.9123). Clean report e2e: 58 PASS / 8
UNVERIFIABLE / 0 FAIL. Live smoke behind RECOUNT_LIVE=1; CI is keyless.
Next: Stage 5 — benchmark (seven corruption generators, metrics module, `recount bench`, README table
in fixture mode, LLM-as-judge baseline in bench/baseline_judge.py). Decide the split rule for the 20 new
labels first (docs/eval.md caveats): the model splits "X stretched to 14.28 days" into comparison +
point_value; the labels treat it as one claim.
Open questions: docs/recount_claude_code_guide.md C1 still says anthropic/ANTHROPIC_API_KEY; CLAUDE.md §0 (Gemini) wins.
Known false-PASS path (documented, abstention P12): periods partly outside the data range compute over
the rows present; V2 engine TODO queries min/max of time_column and abstains no_data. G7 (year rankings
withheld as no_data) is the stopgap. COUNT DISTINCT metrics (c1) deferred; the sweep flags "27 states".
