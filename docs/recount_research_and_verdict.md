# RECOUNT — RESEARCH & VERDICT
### Document 1 of 3 · Why this project: landscape, prior art, alternatives, verdict, honesty constraints
*Consolidates: the August 2026 deep-research report (authoritative), the still-valid findings of the June 2026 scan (Appendix A), and the comparison scorecard & rubric (Appendix B). Companion documents: `recount_spec.md` (what we build) and `recount_claude_code_guide.md` (how we build and present it).*

---

## VERDICT (read this first)

**MODIFY RECOUNT — build the narrowed version. Confidence ~70%.**
- The core gap — a general-purpose, dataset-agnostic OSS library that deterministically *re-derives* numeric/comparative/ranking claims from free-text LLM reports against arbitrary CSV/Parquet, with a seeded-corruption benchmark — did **not** exist as a shipping project as of August 2026. But it is being encircled fast by 2026 research (Thucy, Evergreen, VeriFin, clinical integrity gates, Pitwall), so the original sprawling scope was a trap; the narrowed scope in `recount_spec.md` is the buildable wedge.
- **Strongest competitor:** Thucy (open, source-agnostic claim verification over SQL DBs with reproducible SQL evidence, TabFact SOTA 94.3%). **Biggest research threat:** Deterministic Integrity Gates (already pairs zero-AI numeric re-derivation with a seeded-defect benchmark, clinical-only) and Pitwall (typed-claim state verification, F1-only) — either team could generalize. **Biggest differentiation opportunity:** the deterministic-verify × arbitrary-dataset × eval-native-tooling intersection, plus coverage-aware abstention as a research angle. **Biggest technical risk:** semantic ambiguity of metric definitions in the open setting — mitigated by aggressive UNVERIFIABLE abstention and the semantic config; tested by the weekend spike before commitment.
- **Time-sensitivity:** the competitive picture moves monthly. Re-check the landscape at week 0 and week 4 (gates G0/G4 in the spec). If anyone ships a dataset-agnostic OSS re-derivation library + corruption benchmark, reposition as "best-benchmarked independent implementation" or pivot per Appendix B.

---

## 1. THE AUGUST 2026 LANDSCAPE — CLOSEST PRIOR ART (verified against primary sources)

**Verification of six previously-unverified system names** (supplied by another AI; each hunted down):

| Name | Verdict | Evidence |
|---|---|---|
| ClaimDB | **VERIFIED-RELEVANT** | arXiv 2601.14698 — fact-verification benchmark over large structured data (80 databases, ~4.5M records each); forces reasoning in executable programs. A benchmark, not a tool. |
| MACE | **VERIFIED-RELEVANT** (name overloaded) | arXiv 2604.17225 — multi-agent claim verification from tabular documents (Planner/Executor/Verifier). Note: "MACE" also names an unrelated classic annotation-aggregation tool. |
| CAVE | VERIFIED-IRRELEVANT | NAACL 2025 — authorship-verification explanations; not data claims. |
| VISTA | VERIFIED-IRRELEVANT | arXiv 2605.26144 — benchmark for visual spec-to-web-app coding agents. |
| TABFAITH | **NOT FOUND / likely fabricated** | No such system located. Do not cite. |
| STAF | **NOT FOUND / likely fabricated** | No relevant system located. Do not cite. |

**Prior-art table (verified systems only):**

| System | Year/Type | What it does | Deterministic verdict? | LLM in loop? | Open code? | What it still doesn't do (the Recount gap) |
|---|---|---|---|---|---|---|
| **PCN** (World Bank) | 2025 · paper arXiv 2509.06902 + repo github.com/worldbank/pcn | Render-time numeric verification of *pre-tagged* claim tokens under policies (exact/rounded/alias/tolerance), fail-closed, with soundness proofs | Yes | No (verify step) | Yes (small) | No extraction from free text; no re-derivation from a raw dataset; no corruption benchmark |
| **VeriFin** | Aug 2026 · paper arXiv 2608.10213 | Grounds operands in XBRL facts, verifies financial claims with the Z3 SMT solver → Verified/Violated/Abstain + unsat-core repair; zero false-accepts on its benchmark | Yes (Z3) | Yes (formalization) | Anonymized placeholder only | Finance/XBRL only; fixed QA claims, not free-text reports; not dataset-agnostic; no usable code |
| **FinGround** | Apr 2026 · paper arXiv 2604.23588 (ACL 2026 Industry) | Atomic claim decomposition (six-type taxonomy incl. numerical/comparative/computational), type-routed verification incl. arithmetic re-computation, span rewrite with table-cell citations; reports existing detectors miss 43% of computational errors | Partly (arithmetic step) | Yes (learned verdict models) | No public code found | Finance/SEC only; learned verdicts (not zero-AI); no OSS, no corruption benchmark |
| **Thucy** | Dec 2025 · paper arXiv 2512.03278 + repo github.com/michaeltheologitis/thucy | Multi-agent claim verification across relational DBs; agents write+execute SQL; returns the exact SQL as reproducible evidence; TabFact SOTA 94.3% | SQL execution deterministic; **verdict LLM-mediated** | Yes | Yes | Verdict not deterministic; SQL-DB sources, not CSV/Parquet files; no free-text report pipeline; no corruption benchmark |
| **Evergreen** (Brown/Snowflake) | 2026 · paper arXiv 2604.26180 + repo brown-db/evergreen | Claim verification as *semantic query processing*: compiles each claim to a declarative verification query with provenance/citations — conceptually the closest sibling to Recount's compiler | Query exec deterministic; LLM calls per tuple | Yes | Yes | Text-review corpora (Yelp/Twitter), not arbitrary tabular data; 32-claim benchmark; no seeded corruption |
| **Deterministic Integrity Gates** | Jun 2026 · paper arXiv 2606.09500 | Zero-AI exact-match verification of numeric claims in clinical manuscripts against manifest-locked analysis tables; **ships a seeded-defect benchmark** — the closest system on Recount's two signature axes at once | **Yes (zero-AI verify)** | Extraction only | Code paths shown | Clinical-manuscript-specific; verifies against *locked* tables, not arbitrary user datasets; not a general installable library |
| **Pitwall** | Jul 2026 · paper arXiv 2607.06495 | Verifier-gated grounded generation for live F1: typed claim schema verified against computed race state → SUPPORTED/CONTRADICTED/UNVERIFIABLE; even gates fine-tuning data on claim faithfulness | Verification deterministic vs state | Generator yes | Not released | Domain-locked engine, not reusable tooling. **Direct consequence: Recount's demo domain should NOT be sports** — the sports/typed-claim framing is claimed. |
| **TabVer / TabFact / FEVEROUS / FActScore lineage** | 2020–2024 · research + benchmarks | Table-grounded entailment, arithmetic over tables via natural logic (TabVer, TACL 2024, code released), atomic decomposition (FActScore et al.) | Logical-form exec deterministic | Yes | Mostly | Entailment labels on gold tables, not report re-derivation over user data; benchmarks/models, not developer tools |
| **promptfoo / DeepEval / Braintrust / Ragas / Guardrails / LangSmith / Langfuse / Arize / Giskard** | 2024–26 · OSS + commercial tools | Eval harnesses, deterministic string/schema assertions, NLI/LLM-judge faithfulness, custom-code scorers, CI/GitHub Actions, red-teaming | Assertions yes; faithfulness no | Mixed | Yes | **None extract claims and re-derive them against a supplied dataset.** They are the delivery vehicle, not the competitor — hence the promptfoo adapter. Note: promptfoo was acquired by OpenAI (announced Mar 9, 2026; 350k+ developers; remains open source) — consolidation signal, and a large distribution surface for an adapter. |

## 2. THE MOST RELEVANT PAPERS, EXPLAINED (what to learn from each)

- **VeriFin** — the discipline to steal: *ground the operands independently, then re-derive* (so semantic-parsing errors can't sneak through), and Abstain as a first-class verdict. Its zero-false-accept result (baselines accepted 6–92 of 600 bad candidates) sets Recount's bar for exact-match classes. Recount does what it can't: free-text reports, arbitrary datasets, usable tooling.
- **Thucy** — the UX to steal: *reproducible evidence as output* (return the exact SQL). Its weakness is Recount's thesis: the verdict is still LLM-mediated, and free-form agent SQL can silently run the wrong query; Recount's closed-world templated plans are the answer to exactly that.
- **Evergreen** — validates "compile the claim to a query" as the right abstraction; its per-tuple LLM calls and tiny text-corpus benchmark leave the deterministic, tabular, benchmarked version open.
- **Deterministic Integrity Gates** — the paper an interviewer might raise as "this already exists." Answer: yes, for clinical manuscripts against locked tables; Recount is the general, dataset-agnostic, developer-tooling version — and it's credited in the README. Steal its seeded-defect benchmark pattern.
- **PCN** — steal the policy taxonomy (exact/rounded/alias/tolerance) and the fail-closed default; credit it in the config docs. Recount is the compute-and-check engine that could sit *behind* a PCN-style renderer.
- **Pitwall** — proof the verifier-gated architecture works in production-like settings; also the reason Recount's demo uses business/e-commerce data, not sports.
- **Coverage literature** ("Precision Is Not Faithfulness", arXiv 2606.09376) — the research framing Recount adopts: a verifier that can't *see* a claim can't falsify it, so extraction coverage and abstention must be reported alongside detection. This is Recount's honest edge over every precision-only eval.

## 3. THE ACTUAL UNSOLVED PROBLEM (not "nobody built Recount")

Given free-text analytical prose and an arbitrary tabular dataset with only a light semantic config: deterministically and reproducibly decide, per numeric/comparative/ranking claim, whether the number is re-derivable from the data — while correctly resolving metric definitions, denominators, filters, groupings, temporal windows, and rounding — and honestly abstaining when the claim is under-specified. Everything shipping in 2026 solves a *constrained* slice (fixed formulas, governed metric stores, locked tables, single clean tables). The open part is **semantic resolution + coverage + abstention in the open setting, with determinism preserved**. That is the engineering problem Recount attacks; the plumbing is just how it gets there.

## 4. ALTERNATIVES FORMALLY SCORED (so "is this the best?" stays answered)

Five serious alternatives were researched and scored 1–10 across 13 criteria (real-world problem, technical depth, AI/ML depth, cybersecurity depth, software engineering, research potential, novelty, demo factor, resume value, interview value, measurability, 6–8-week feasibility, genericness risk):

| Project | Overall | Why it lost |
|---|---|---|
| **Recount (modified)** | **7.3 — winner** | Highest feasibility × resume/SWE value × measurability; unfair advantage (her production re-derivation experience); zero bluffed skills |
| Verifier-gated grounded generation, new live domain (Pitwall-style) | 7.2 | Highest ceiling and demo-wow, but doing generation *and* verification well in 8 weeks alongside college is the weakest feasibility of the set; conceptually shadowed by Pitwall |
| Recount original (broad scope) | 7.1 | Same thesis, dragged down by feasibility and scope-generality risk — hence MODIFY |
| Agent tool-call/argument verification harness | 6.8 | Real problem, but crowded (AEGIS, ToolGate, AgentLTL exist); weaker novelty |
| Coverage-aware faithfulness benchmark only | 6.6 | Strong research artifact, weak SWE signal — absorbed INTO Recount as its evaluation framing instead |
| AI-generated-code security CI gate | 6.5 | Real (Veracode: 45% of AI-generated code introduces vulns) but crowded (Snyk, Semgrep) and a poor fit: zero security background, wrong role pipeline |
| *(Previously eliminated with live evidence)* AI agent-skill security scanner | — | The pitched product already ships: Snyk Agent Scan (ex-Invariant mcp-scan, acquired June 2025; 15+ risk types incl. skills), Cisco mcp-scanner + DefenseClaw (31,000 skills analyzed, 26% vulnerable); benchmarks SkillTrustBench (5,520 samples) and MalSkillBench (3,944 runtime-verified) exist to compare an already-crowded detector field |

## 5. HONESTY CONSTRAINTS (resume- and interview-binding)

**Claims that MUST NOT be made** (each is disprovable):
- "First system to deterministically verify numeric claims from LLM output" (PCN, VeriFin, clinical gates predate it)
- "No one re-derives numbers from LLM reports" (FinGround recomputes; clinical gates exact-match; Evergreen compiles claims to queries)
- "First seeded-corruption benchmark for numeric faithfulness" (clinical gates ship one; FinVerBench injects errors)
- "First to verify claims against arbitrary databases" (Thucy is source-agnostic across relational DBs)
- "First typed-claim verification for sports/data-to-text" (Pitwall)
- "Zero AI anywhere" (extraction is an LLM; only *verification* is deterministic — say exactly that)
- Any claim that EU AI Act Art. 14/15 *currently* forces this (see §6)

**Claims that CAN be defensibly made:**
- "A dataset-agnostic OSS library that compiles extracted claims to a deterministic, zero-AI verification step over arbitrary CSV/Parquet — the general-purpose analogue of domain-locked systems like VeriFin (finance) and clinical integrity gates."
- "To my knowledge, the first to package free-text claim extraction → deterministic re-derivation → PASS/FAIL/UNVERIFIABLE with cell-level provenance as an eval-framework-native scorer + CLI with a reproducible, dataset-agnostic seeded-corruption benchmark" — hedged with "to my knowledge," closest prior art named.
- "A coverage-aware evaluation of numeric report faithfulness measuring extraction coverage and abstention, not just precision."

## 6. DEMAND SIGNALS & THE REGULATORY CORRECTION

- **Hiring (the strong signal):** AI Engineer ranked the #1 fastest-growing US role for the second consecutive year (LinkedIn Jobs on the Rise 2026; postings +143% YoY); AI literacy +70% YoY and the agent-eval toolchain (LangSmith, Braintrust, Maxim AI) among the fastest-growing skills (LinkedIn Skills on the Rise 2026). Evals literacy is repeatedly described as the top screen separating people who built with LLMs from people who watched tutorials. *(Source-derived: LinkedIn's proprietary indices.)*
- **Trust problem is real and measured:** Stack Overflow 2025 Developer Survey (49,009 respondents): 84% using/planning AI tools while trust in accuracy fell to 29% (from 40%); more developers actively distrust AI output (46%) than trust it (33%). Enterprise-cost figures circulating in 2026 (Deloitte "47% made a major decision on hallucinated content"; Forrester "4.3 hrs/week checking AI outputs") are secondary/reported — cite as reported, never as independently verified.
- **REGULATORY CORRECTION (supersedes the June scan):** the EU AI Act's Digital Omnibus (in force July 27, 2026) postponed standalone Annex III high-risk obligations (Ch. III, Arts. 9–15) from Aug 2, 2026 to **Dec 2, 2027** (Annex I embedded: Aug 2028); Art. 50 transparency and Art. 4 AI-literacy duties were NOT postponed. Use the Act as a directional tailwind only. *(Multiple law-firm trackers: DLA Piper, Gibson Dunn, Orrick.)*

## 7. SOURCE INTEGRITY NOTES

Facts vs source-derived claims are marked throughout. Self-reported performance numbers (VeriFin zero false-accepts; Thucy 94.3%; FinGround 68–78% reduction) are the authors' results, not independently reproduced. Repo star/activity counts are indicative. The competitive picture is time-sensitive — re-validated at build start per gates G0/G4.

---

# APPENDIX A — STILL-VALID FINDINGS FROM THE JUNE 2026 SCAN

- **The eval/guardrail tool landscape clusters into four categories, none of which re-derive:** (1) NLI/LLM-judge grounding (Ragas Faithfulness, DeepEval Hallucination, Guardrails ProvenanceLLM, Vectara HHEM) — soft entailment, not arithmetic recomputation; (2) schema/structural validation (Guardrails, Pydantic validators, ValidSQL — shape, not truth); (3) eval harnesses with custom-code scorers + CI gates (Braintrust, promptfoo, DeepEval) — the closest *primitive* and therefore the right integration surface; (4) security/red-team scanners (garak ~8.1k stars, Rebuff, Lakera) — model-facing robustness, not artifact fidelity. Cell-level provenance, bounded span-repair, and seeded-corruption benchmarks were not found as shipped features in any of them.
- **BI/semantic-layer vendors prevent rather than verify:** ThoughtSpot Sage claims no hallucinations *because* the LLM only parses intent; dbt/MetricFlow and Cube make the LLM choose certified metrics and generate SQL deterministically (dbt's 2026 benchmark update: semantic-layer grounding lifting models to 98–100% vs 84–90% raw — vendor-reported); Tableau acknowledged ad-hoc Q&A hallucination. **Positioning consequence:** semantic layers and Recount are complementary layers — prevention at generation time inside governed stacks vs post-hoc verification of arbitrary artifacts from generators you don't control. No BI vendor exposes standalone "verify this report against this dataset."
- **World Bank shipped PCN precisely because "AI access does not equal data integrity"** — institutional validation of the exact problem.
- **The GitHub niche scan** found no Python project doing deterministic re-computation of report claims against user dataframes as reusable tooling; neighbors (VerifierFC, TabFact code, table-validation/VLDB-TaDA, hobby LLM-fact-checkers) all differ materially (reasoning-based, benchmark-only, table-to-table, or LLM-in-the-loop).

# APPENDIX B — COMPARISON RUBRIC & FINAL SCORECARD (from the proposal)

**Recount's scorecard (1–10):** real-world problem 8 · technical depth 7 · AI/ML depth 7 · software engineering 9 · research potential 6 · novelty 6 · demo 7 · resume value 9 · interview value 9 · measurability 9 · feasibility 8 · genericness risk (10 = low) 7 · cybersecurity 3 (honest: a supporting property, not a security project). **Overall 7.3 — highest of six scored candidates.**

**The rubric any competing proposal must satisfy before it's comparable** (a pitch with a big score and none of these has been marketed, not researched): (1) a *verified* gap from primary sources; (2) one named primary user; (3) an evidence plan — the metrics the project itself will measure; (4) a claims policy — what it must NOT say; (5) an unfair-advantage argument specific to the builder; (6) gated feasibility with a fallback that is still a complete project; (7) an explicit scope cut-list.

**Pivot conditions (pre-agreed):** if a general OSS re-derivation library + corruption benchmark ships before Recount's v0.1, reposition as best-benchmarked independent implementation or pivot to the verifier-gated-generation alternative (§4). Decision points: gates G0 (today) and G4 (week 5).

*— End of Document 1. Next: `recount_spec.md` (Document 2 — what we build) and `recount_claude_code_guide.md` (Document 3 — how we build and present it).*
