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
Current stage: v0.1.0 tagged (moving tag v0.1), repo PUBLIC (2026-09-08). Stage 7 closed with the mock interview.
Done (Stage 7, 2026-09-08): tests/security/test_hostile_inputs.py (T3/T4/T7: 40 parametrised hostile-name cases
through compile→verify, hostile column names as quoted identifiers, hostile cells as group keys, a `!!python` config
tag refused as invalid YAML, dataset and artifact caps as one-line exit 2); tests/adversarial/test_injection.py (T1:
10 phrasings × 3 positions with extraction held fixed → verdicts identical, a phrasing inside a span rejects only
that claim, hostile wire keys are foreign fields; T2: Hypothesis instruction-in-a-cell invariance);
tests/test_determinism.py (in-process, two-process byte-identical JSON/HTML/Markdown, Hypothesis row-order
invariance). New cap: `pipeline.MAX_ARTIFACT_BYTES` = 1 MiB (`ArtifactError` → exit 2). docs/design.md (walls with
test names, abstention, benchmark method, F-1→F-5, threat table T1–T10, honesty + prior art). README public-ready
with docs/demo.gif (frames rendered from real runs: CLI on the corrupted report, the PR's Checks tab on
GitHub with verify-reports ✗, the HTML drawer). LICENSE (Apache-2.0) added
(it was referenced but missing). Version 0.1.0; benchmark replayed keylessly, only the version line moved;
bench/results/v0.1.0.json committed. The three private planning docs removed from the tree and every reference
scrubbed (spec §, FR-, NFR- ids; threat ids T1–T10 now defined in docs/design.md). pip-audit clean; no key, .env or
raw data tracked, history scanned.
Next: the post-v0.1 visibility write-up is the owner's; code-wise the V2 items are P12 (data-coverage abstention),
COUNT DISTINCT metrics and rank-change verification. Pre-flip tightenings (owner's ruling, 2026-09-08): pip-audit is enforcing in ci.yml; .github/CODEOWNERS covers
.github/, action.yml and Dockerfile (T9); verify-reports is already a required check on main.
Known false-PASS path (documented, abstention P12): periods partly outside the data range compute over
the rows present; V2 engine TODO queries min/max of time_column and abstains no_data. G7 (year rankings
withheld as no_data) is the stopgap. COUNT DISTINCT metrics (c1) deferred; the sweep flags "27 states".
Benchmark integrity: taxonomy frozen (test_corruption_taxonomy_is_frozen); every post-freeze change to
verify/compile/extract is a numbered entry in docs/benchmark.md §6 with before/after numbers (seven so far).
