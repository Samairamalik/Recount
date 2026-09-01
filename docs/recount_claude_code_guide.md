# RECOUNT — CLAUDE CODE SETUP · STEP-BY-STEP GUIDE · USP
### Document 3 of 3 · How we build and present it: USP · Step-by-step · Claude Code setup · Learning roadmap · Interview prep · Resume positioning

---

# PART A — THE USP (know this cold before writing any code)

**One sentence:** Recount deterministically re-derives every number, comparison, and ranking in an LLM-generated report against the source dataset — no LLM ever judges correctness — and proves each verdict with the exact SQL and rows behind it.

**The three-part wedge (this is what no shipping tool combines):**
1. **Free-text in, arbitrary data underneath.** Not pre-tagged claims (PCN), not XBRL filings (VeriFin), not locked clinical tables (integrity gates) — a raw Markdown report against *your* CSV/Parquet.
2. **Zero AI in the verdict.** Not LLM-as-judge (Ragas/DeepEval faithfulness), not an agent writing SQL whose verdict is still LLM-mediated (Thucy/Evergreen) — a typed compiler and templated SQL, with an architecture test that fails the build if an LLM import ever touches the verify path.
3. **Shipped as measurable developer tooling.** Installable library + CLI + CI gate + promptfoo adapter + a reproducible seeded-corruption benchmark that reports detection rate, false-accepts, coverage, and abstention — head-to-head against an LLM-as-judge baseline on identical artifacts.

**The honest framing (recite it, it wins interviews):** "To my knowledge, the first to package free-text claim extraction → deterministic re-derivation → PASS/FAIL/UNVERIFIABLE with cell-level provenance as general, dataset-agnostic tooling. Closest prior art — VeriFin, clinical integrity gates, Thucy, Evergreen, PCN — is credited in the README; each solves a constrained slice; the assembly is the contribution." Never say "first system to verify LLM numbers," "no existing system does this," or "zero AI anywhere" (extraction is an LLM; only verification is deterministic).

**Why it's *your* USP specifically:** the method is the public generalization of what you shipped at ITC — deterministic re-derivation in a zero-tolerance reporting pipeline — plus the verify/auto-repair pattern from VizLens. The three signature interview answers this project manufactures: the three walls (data⇸prompts, text⇸verdicts, plans⇸code, each with a test), "a false PASS is the only unforgivable failure, so we abstain instead of guess," and "every number on my resume came from my own benchmark harness."

---

# PART B — HOW WE GO ABOUT THIS, STEP BY STEP (plain language)

**Step 0 — This weekend: prove the idea before building it (6–8 hours, throwaway).**
Sample the Olist dataset. Have an LLM write one quarterly report about it (~15 claims). Then *you*, by hand, label every claim and compute its true value in a notebook — these two hours design the claim schema and become permanent test ground truth. Then a quick-and-dirty script: extract claims → crudely map two claim types to DuckDB queries → print verdicts. Count what fraction compiled and verified. **Gate: ≥60% → build. Under 30% → narrow the scope (still a real project). In between → spend one evening on a richer config format and re-run once.** The spike gets committed to `spike/` as process evidence and never touched again.

**Step 1 — Week 1: lay the contracts.** Repo with uv/ruff/mypy/pytest/CI; the Claim types and SemanticConfig as Pydantic models; your hand labels become test fixtures. Also freeze the seven corruption classes *now*, before any verifier exists — that's what makes the eventual benchmark honest. Done when CI is green and every label round-trips the schema.

**Step 2 — Weeks 1–2: the deterministic engine.** Hand-written claims → correct verdicts: loader, compute plans, one SQL template per claim type, tolerance policies, golden tests from your notebook values, and the two "wall" tests. This is the layer you must own line-by-line. Done when goldens pass and the no-false-accept property test holds. *First demo exists here — before any production LLM call.*

**Step 3 — Week 3: the compiler.** The layer that turns a claim + your config into a computation — or refuses. Write the abstention decision table as a document first, then implement it. Refusing to guess is the product's spine.

**Step 4 — Week 4: the extractor (the only AI, deliberately last of the core).** One structured-output call per report, temperature 0, every claim's span must literally exist in the text, plus the deterministic numeric sweep so nothing is missed *silently*. Then measure it against your 40 labels and write the precision/recall down, whatever they are.

**Step 5 — Week 5: the benchmark — the headline.** Generate ~100+ corrupted report variants from the frozen taxonomy, run the pipeline, produce the numbers: detection per class, false-accepts (target zero on exact-match), coverage, abstention, latency — and the same suite scored by an LLM-as-judge for the comparison chart. Every resume blank fills here.

**Step 6 — Weeks 6–7: make it usable.** Week 6 is midsems — protect it (CLI exit codes at most). Week 7: `recount init`, the annotated HTML report (timeboxed), the promptfoo assertion, and the GitHub Action — plus a demo PR in your own repo being visibly blocked by a corrupted report.

**Step 7 — Week 8: harden and tell the truth.** Property tests (including: injecting instructions into data cells changes nothing), hostile inputs, `docs/design.md` with the three walls and the prior-art honesty section, demo GIF, tag v0.1. Done = the six acceptance criteria in the spec. Buffer week absorbs overruns only.

**The rhythm throughout:** DSA sprint stays the weekday priority; Recount gets ~8–10 weekend-weighted hours; each week has one milestone that is a *state*, not an activity; two consecutive missed milestones triggers the pre-agreed cut (drop `share` + HTML, ship four claim types CLI-only — thesis intact).

---

# PART C — CLAUDE CODE SETUP

## C1. One-time setup (30 minutes, before any session)

```bash
# prerequisites: git, uv (curl -LsSf https://astral.sh/uv/install.sh | sh), Claude Code
mkdir recount && cd recount && git init
uv init --package --python 3.12        # src layout, pyproject.toml
uv add duckdb pydantic typer rich jinja2 pyyaml anthropic
uv add --dev pytest hypothesis ruff mypy pip-audit
mkdir -p spike src/recount tests/architecture tests/fixtures examples/olist docs .github/workflows
$EDITOR CLAUDE.md                      # paste C2 verbatim — BEFORE the first session
git add -A && git commit -m "repo spine + constitution"
export ANTHROPIC_API_KEY=...           # env only; never in files
```

## C2. CLAUDE.md (paste verbatim; maintain the STATUS block every session)

```markdown
# CLAUDE.md — Recount project constitution

## What this project is
Recount verifies numeric/comparative/ranking claims in LLM-generated reports
against the source dataset, DETERMINISTICALLY. The core thesis is a hard wall
between probabilistic and deterministic code. Protecting that wall outranks
any feature, refactor, or convenience.

## Architecture invariants (never violate; flag if a task seems to require it)
- Only src/recount/extract/ and src/recount/bench/baseline_judge.py may import
  an LLM client. Wall-tests in tests/architecture/ enforce this; never edit
  those tests to make a change pass.
- SQL exists only as fixed templates in verify/engine.py, parameterized.
  No f-string/concat SQL anywhere. No eval/exec anywhere.
- Dataset contents never enter any prompt. Artifact text never influences a
  verdict except through schema-validated Claim objects.
- The compiler abstains (reason-coded) instead of guessing. Do not "improve"
  abstentions into best-effort guesses.

## How to behave (pair programmer, not autonomous generator)
- Before implementing: state what you'll build, assumptions, files touched,
  and the test plan. Wait for approval.
- Implement only the component asked for. No drive-by refactors, no new
  abstractions, no new dependencies without flagging as a QUESTION first.
- Every session ends with tests written AND run here. Never claim untested
  code works. Distinguish "implemented and tested" from "written, unverified".
- Say when you're uncertain (API behavior, SQL semantics, date edges) instead
  of guessing. Flag security-relevant choices and introduced tech debt.
- When code uses a concept the user may not know, explain it briefly in the
  session, and prompt the user to add a line to docs/learning-log.md.

## Quality gates (all pass before any commit)
uv run ruff check && uv run mypy && uv run pytest
Coverage ≥85% on compile/ and verify/.

## STATUS (update at the end of every session)
Current stage: <Stage N — name>
Done: <one line>   Next: <one line>   Open questions: <or "none">
```

## C3. The session loop (every component, no exceptions)

1. **Learn first** (the stage's 1–3 hour concept block) — before opening Claude Code.
2. **You state the design** — component purpose, inputs/outputs, constraints — and ask Claude Code to *critique and propose a plan* (files, functions, tests). Not the other way around.
3. **Review the plan**: does it touch only expected files? Are the tests real (asserting values, not just "it runs")? Edit before any code exists.
4. **Implement one component** (one module or less per session).
5. **Tests in the same session** — Claude writes them; **you add at least one case it didn't think of** (non-negotiable: it's how you find out whether you understand the component).
6. **Read the whole diff.** Ask "explain this line — and why not the obvious alternative" at least once per session.
7. **Run the quality gates.** 8. **Manually verify** against the stage's hand-computed ground truth.
9. **Commit** — message written by you, only when you can summarize the diff aloud.
10. **Update** CLAUDE.md STATUS + one line in `docs/learning-log.md` ("thing I learned / question an interviewer would ask"). That file becomes your interview prep, accumulating for free.

**Per task type:** *new module* → the loop above. *Bug* → **you** write the failing test first (highest learning-per-minute in the project), Claude fixes, the test is the definition of done. *Refactor* → only with a named smell and green tests before/after. *Docs/CI plumbing* → delegate freely, skim-review. 

**Stop-and-reconsider triggers (design conversation, not a coding session):** Claude proposes editing a wall-test · any component wants a new dependency · a module hits its third rework · benchmark numbers move without an explanation you can articulate.

## C4. Session-opener prompts per stage (compact starters)

- **Spike:** "Throwaway spike, no tests/packaging: script that (1) calls the extraction prompt in spike/prompt.txt on spike/report.md, (2) maps point_value and growth claims to DuckDB queries against spike/orders.parquet using the tiny config I'll paste, (3) prints a verdict table with abstain reasons. Propose the plan first."
- **Stage 1:** "Read CLAUDE.md. Propose repo spine + `claims/model.py` (5-type discriminated union per the schema I paste) + `config/schema.py`, with round-trip tests against tests/fixtures/labeled_claims.json. Plan first; explain discriminated unions briefly before implementing."
- **Stage 2:** "Stage 2 per CLAUDE.md invariants: loader, plans, engine (one SQL template per plan type, parameterized), policies. Golden tests use the hand-computed values I paste. Add the two architecture wall-tests. Plan first; after implementing, walk me through every SQL template and policy branch."
- **Stage 3:** "Here is my abstention decision table [paste]. Critique it — find missed cases — then implement compiler.py to match it exactly, with the ambiguity fixture tests. No LLM anywhere; extend the wall-test."
- **Stage 4:** "Extractor: one structured call, temp 0, one retry, span-substring enforcement, ExtractorClient Protocol + fixture mock; plus sweep.py (handle 1.42M, 12.4%, 1,41,834). CI uses recorded responses only. Then build the mini-eval vs the 40 labels and tell me where it failed and your hypothesis why."
- **Stage 5:** "Benchmark: seeded generators for the seven frozen corruption classes; metrics.py (detection/class, false-accept, false-flag, coverage, abstention, latency); `recount bench`; CI writes the README table between markers; judge baseline module. Verify same-seed determinism. Then flag any number in the results that looks suspicious."
- **Stage 6:** "CLI polish (init/verify/bench, exit codes 0/1/2, --strict), timeboxed Jinja2 annotated-HTML report, promptfoo `recount-verify` assertion with a worked example, Dockerized GitHub Action; open a demo PR containing a corrupted report so the Action blocks it."
- **Stage 7:** "Hardening: Hypothesis suites (no-false-accept, round-trip truth, instruction-in-data invariance, byte-identical determinism), hostile entity names, size caps. Then co-write docs/design.md — three walls, abstention table, benchmark methodology, prior-art honesty section — and flag any sentence that overclaims. Finish by asking me the ten hardest questions about this repo and critiquing my answers."

## C5. What Claude Code owns vs what you must own

**Delegate freely:** scaffolding, CI YAML, Rich/Jinja2 plumbing, test boilerplate, the Action, refactors-under-instruction. **You must be able to rewrite from a blank file:** the claim schema, the abstention table, the tolerance policies, every SQL template, the benchmark metric definitions. If you can't, pause and close the gap before moving on — this project exists partly to replace the AI-assisted-but-not-owned pattern of your earlier repos with code you can defend under fire.

---

**Today, in order:** ① the 1-hour landscape check (three searches; three sentences into `spike/RESULTS.md`) → ② C1 setup + CLAUDE.md committed → ③ sample the data, generate the report → ④ start hand-labeling. The spike gate closes the "which project?" question for good; everything after it is just the next milestone.

---

# PART D — LEARNING ROADMAP (per stage: before → while → able-to-explain → exercise)

**Stage 0 (spike).** Before (1h): DuckDB Python quickstart — nothing else; the spike is the lesson. Explain after: what shapes real claims take and why N% abstained. Exercise: hand-compute every claim's true value *before* the script runs; predict each verdict.
**Stage 1 (contracts).** Before (2h): Pydantic v2 discriminated unions + frozen models — you're about to make the project's most consequential design decision (the claim schema). Explain: why validation lives at the LLM boundary and nowhere else. Exercise: break the schema on purpose (wrong discriminator) and read the error.
**Stage 2 (engine).** Before (2–3h): float comparison semantics (why `==` lies; absolute vs relative vs percentage-point tolerance — needed to *design* policies.py, not just implement it) + half-open date intervals. Explain: every SQL template from memory; why growth claims use pp-tolerance while point values use relative. Exercise: the five hand-verified claims in the DuckDB CLI before the engine exists.
**Stage 3 (compiler).** Before (2h): what dbt/Cube metric definitions are — your config is a miniature semantic layer and interviewers will make the connection. Explain: the abstention table row by row, and why guessing is banned. Exercise: ten ambiguous claims from a real BI report → config-resolvable vs must-abstain, on paper.
**Stage 4 (extractor).** Before (1–2h): what JSON-schema-constrained outputs guarantee (shape) and don't (truth, bindings) — hence Pydantic re-validation. Explain: the three extractor failure modes and which component bounds each. Exercise: compute P/R on the 40 labels yourself in a notebook before the eval module does.
**Stage 5 (benchmark).** Before (2h): detection/false-accept/false-flag definitions + one read on benchmark gaming/Goodharting (why the taxonomy freeze matters). Explain: "how do you know your benchmark isn't self-serving?" fluently. Exercise: corrupt one report seven ways by hand; predict which get caught; check.
**Stage 6 (tooling).** Before (1h): promptfoo assertion API; exit-code conventions. Explain: exactly what happens when a bad report hits CI. Exercise: break the demo PR on purpose and read the entire log.
**Stage 7 (hardening).** Before (2h): Hypothesis basics (`st.floats`, `st.sampled_from`, `@composite` — ignore the rest). Explain: the three walls and the test enforcing each. Exercise: write the README's "what Recount does NOT do" from memory; diff against Document 1 §5.

# PART E — INTERVIEW PREPARATION (what to *understand*, per question)

**Beginner.** "What does it do?" → the one-liner + your demo cold. "Why DuckDB?" → one engine over CSV/Parquet; SQL text doubles as auditable provenance; no server for a local tool — and know what pandas would cost you (inspectable queries) and Postgres (zero-install UX). "Why is there an LLM at all?" → paraphrase detection is genuinely hard for rules; know precisely what the LLM is *not allowed* to do.
**Intermediate.** "Why not LLM-as-judge?" → nondeterminism, no provenance, judge-of-a-judge regress — *and you measured its false-accept rate on your own benchmark; quote your numbers.* "Where does it fail?" → the four honest holes: extraction misses (bounded by the sweep), wrong binding (quantified by swapped_entity), config mis-specification (it verifies against the config's definition of truth), template bugs (why golden + property tests exist). "Why abstain instead of guess?" → a false PASS is the cardinal failure; UNVERIFIABLE is information; know your abstention rate and its audited correctness. "Isn't this Guardrails/promptfoo?" → know exactly what each does (schema/assertions) and doesn't (re-derivation); your promptfoo adapter proves complement-not-competitor.
**Advanced.** "Deterministic vs ML, and how enforced?" → the three walls + the build-failing tests. *Your signature answer — rehearse it aloud.* "Bottlenecks / 10x?" → extraction dominates cost+latency (one call per artifact; per-claim would be worse — know why); DuckDB single-node ceiling ~100M rows; scale = extraction cache by artifact hash + parallel plan execution — and knowing when *not* to add infrastructure. "Adversarial input?" → walk T1–T4 with the actual property tests; injection resistance is an architectural property you *test*, not security research you claim. "How would you eliminate hallucination?" → trick question: you don't — you make numeric hallucination detectable and blocking; name the complementary generation-side approaches (semantic layers, constrained decoding). "Isn't your benchmark self-serving?" → frozen taxonomy, co-reported coverage/abstention, judge baseline on identical artifacts, published seeds. "Isn't this VeriFin / the clinical-gates paper?" → yes-and: they're credited in the README; yours is the general, dataset-agnostic, tooling-first assembly. Volunteering the prior art unprompted converts the gotcha into your best moment.
**Why-X/why-not-Y bank:** Pydantic vs dataclasses · templates vs DSL · abstain vs LLM-guessed mappings · Typer CLI vs web app · no vector DB (nothing is similarity-retrieved) · no agents (fixed DAG; loops add nondeterminism exactly where determinism is the product) · uv vs Poetry · stdlib logging vs structlog.

# PART F — RESUME POSITIONING (fill blanks ONLY from your own benchmark)

**One line:** Open-source deterministic verifier for numeric claims in LLM-generated analytics reports.
**Two lines:** Built Recount, an open-source Python library + CI gate that extracts numeric/comparative/ranking claims from LLM-generated reports and deterministically re-derives each against the source dataset (DuckDB), returning PASS/FAIL/UNVERIFIABLE with cell-level provenance — evaluated on a reproducible seeded-corruption benchmark against an LLM-as-judge baseline.
**Bullets (blanks = your measured numbers):**
- Designed a typed claim taxonomy and deterministic verification engine (Python, DuckDB, Pydantic) enforcing a hard probabilistic/deterministic boundary via architecture tests; achieved __% detection and __% false-accepts across 7 seeded corruption classes on 100+ artifacts (vs __%/__% for an LLM-as-judge baseline).
- Built a coverage-aware evaluation pipeline measuring extraction precision/recall (__/__), abstention correctness (__%), and per-claim latency (__ms), published as a reproducible benchmark with a frozen corruption taxonomy and seeded generation.
- Shipped as pip-installable tooling with a promptfoo assertion and a GitHub Action that blocks merges on failed claims; __ automated tests incl. Hypothesis property tests proving instruction-in-data invariance and zero false-accepts on exact-match claims.
**Capture while building so every blank fills honestly:** per-class detection; false-accept/false-flag; judge deltas; extraction P/R on the 40 labels; abstention rate + audited correctness; latency p50/p95; test count + coverage; suite size.
**Taped to the monitor:** never "first system to…", "no existing system does…", "zero AI anywhere." Always "to my knowledge, the first to package X as Y — closest prior art: VeriFin, clinical integrity gates, Thucy, Evergreen, PCN." (Full lists: Document 1 §5.)

*— End of Document 3. The three-document set is complete: Document 1 = why (research & verdict) · Document 2 = what (specification) · Document 3 = how (execution). Next artifact: spike code.*
