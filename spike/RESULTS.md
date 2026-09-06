# Spike results

## G0 — landscape check (done 2026-09-01)
Three searches, primary sources: no new general-purpose OSS library re-derives numeric claims from
free-text reports against arbitrary datasets. Closest movements since the August report:
- FinGround (finance/SEC) states production integration as an internal REST service targeting Q3 2026 — proprietary, finance-only, not OSS.
- Evergreen's repo (brown-db/evergreen) is experiment code that requires a Snowflake account and Yelp data — a research artifact, not an installable library.
- VeriFin remains finance/XBRL-only; its explicit "coverage cost" finding (rejecting 37–73 correct claims per model) is a useful comparison point for our abstention rate.
**Gate G0: PASS.** Proceed to the spike.

## Data
- source: Olist Brazilian e-commerce (Kaggle, CC BY-NC-SA), joined orders × customers × items, delivered only
- rows sampled: 43,428 (one row per delivered order; `order_id` unique)
- period: 2017-01-05 .. 2017-12-31 · 27 states · total revenue 6,921,535.24
- two data quirks fixed as conventions in `labels.json`:
  - `revenue` is a DOUBLE; `SUM(revenue)` varies by ~3.5e-07 across row orderings (measured: `…239999729` / `…239999984` / `…239999633`). All revenue comparisons round to 2dp first.
  - 2 rows have NULL `delivery_days`; `AVG` excludes them, so the national denominator is 43,426. Affects Q2, Q4, RS, SP.

## Report
- generator model: gemini-3.6-flash, temperature 0, one call (`spike/generate_report.py`)
- claims in report (hand count): **57**
- clean artifact preserved as `report_clean.md`; `report.md` carries **6 hand-injected corruptions**
  (one per claim): wrong_figure_revenue (c19), wrong_figure_delivery (c45), flipped_direction (c25),
  wrong_ranking (c41), swapped_entity (c54), rounding_drift (c27). Manifest in `labels.json`.
- answer key verdict mix: 46 PASS · 6 FAIL · 5 UNVERIFIABLE

## Extraction
- claims extracted: **39** (one Gemini call, structured output, `response_schema`)
- matched hand labels: **39** · missed: **18** · invented/misbound: **0**
- coverage = matched / hand-count = **68.4%** (39/57)
- the 18 uncredited labels split two ways, and the distinction matters:
  - **5 were merged**, not missed — the extractor returned one span covering two assertions
    (e.g. `generating 1,931,208.93 in gross revenue across 12,215 orders` = c19 + c20). Counting
    merges as covered gives **77.2%** (44/57). The honest headline is 68.4%; the gap is a
    *measurement* artifact of one-claim-per-span, not a model failure.
  - **13 were genuinely not extracted.** Nine of these are the non-numeric ones — every
    direction-only comparison (c5, c7, c17, c30), every ranking (c11, c23, c34, c41) and the vague
    growth (c12). Four are bare numeric fragments the model folded away (c37, c38, c43, c55).
- **The `subject` field did real work.** 13 extracted claims have a span containing no state name at
  all (`336,300.71 in total revenue`), where `subject` was the only carrier of the entity. Span-local
  verification alone would have computed the national figure and produced 13 false flags.

## Compile + verify (point_value + growth only)
- compiled: **32** · abstained: **7** (reasons: `unsupported_claim_type:share` ×6, `unsupported_claim_type:ranking` ×1)
- every abstention was the intended one — the spike compiler only supports two of five claim types.
  Zero abstentions came from `unknown_metric`, `unknown_period` or `unknown_entity`, so the
  30-minute `metrics.yml` vocabulary (5 metrics, 6 entity aliases) covered the whole report.
- verdicts vs my hand-computed truth — correct: **31 / 39** · false accepts: **1** · false flags: **0**
- the 7 remaining mismatches are all abstentions where the key expects a real verdict (6 share + 1 ranking)
- **compile-and-verify rate on numeric claims = 68.1% (32/47)**

### Corruption detection — 3 of 6
| id | class | verdict | outcome |
|---|---|---|---|
| c19 | wrong_figure_revenue | FAIL | caught |
| c45 | wrong_figure_delivery | FAIL | caught |
| c27 | rounding_drift | FAIL | caught (0.0546 drift vs 0.005 bound) |
| c25 | flipped_direction | **PASS** | **FALSE ACCEPT** |
| c41 | wrong_ranking | — | not extracted |
| c54 | swapped_entity | ABSTAIN | claim type unsupported |

**The single false accept is the most important result in this spike.** `Fourth-quarter revenue
declined by 43.61%` verified as PASS because the compiler compares magnitude only: it read 43.61,
computed +43.61, and never looked at the word "declined". A sign-blind comparator will accept a
claim that says the exact opposite of the truth. Per CLAUDE.md, a false PASS is the one unforgivable
failure — so the tolerance check must carry direction, not just distance, before Stage 2 ships.

Note also that the two corruptions which escaped without a false accept (c41, c54) escaped by
*luck of coverage*, not by design: one was never extracted, the other fell outside the supported
claim types. Neither is evidence of correct abstention behaviour.

## Dilemmas encountered while labeling
- **d1 (c11) — ruling overturned mid-spike.** "Sao Paulo took the lead in the first quarter" was first
  labeled FAIL as a constructed falsehood, then corrected to UNVERIFIABLE (`ambiguous_baseline`). The
  data starts 2017-01-05, so the "overtook a prior leader" reading is uncomputable while the "was
  ranked #1" reading is simply true. **Lesson: `expected_verdict` records what a correct verifier
  should output, not whether the sentence is true.** Labeling it FAIL would have trained the spike to
  score a correct abstention as a miss.
- **d2 (c7, c12) — vague magnitude, no number.** "well under two weeks", "nearly doubled". UNVERIFIABLE
  per LABELING_GUIDE rule 3. These are the abstention fixtures.
- **d3 (c30) — schema-gap abstention, NOT vagueness.** "Southeast and South regions" needs a
  state→region mapping the fact table does not have. This is a different abstention *reason* from d2
  and must get its own reason code — a user can fix a schema gap by extending the config; they cannot
  fix vagueness at all. **Recorded as Stage 1 schema feedback.**
- **d4 (c36) — unstated measure.** "second position overall" never says by orders or revenue. Benign
  here because RJ is #2 on both, but a compiler cannot know that without computing both. Latent
  abstention rule.
- **d5 (c17, c23) — direction-only and superlative claims carry no stated value but are fully
  deterministic.** "delivery performance improved" (Q2 12.55 < Q1 13.09) and "peak fulfillment
  efficiency of the year" (Q3 lowest of four) are checkable with no number in the sentence. V1 needs a
  direction-only `comparison` variant and a superlative `ranking` variant, or these get wrongly
  bucketed with d2's genuinely-vague claims and abstained away. **Recorded as Stage 1 schema feedback.**
- **d6 — float sums.** `SUM` over DOUBLE is order-dependent; "the true value" is undefined until a
  rounding rule is fixed. Became a convention, not 12 duplicate per-claim notes.
- **d7 (new, from the run) — claim merging breaks 1:1 scoring.** The extractor returned single spans
  covering two assertions in 5 cases. Coverage is therefore sensitive to the span-matching rule
  (68.4% strict vs 77.2% lenient). Stage 1 needs a defined matching policy *before* the mini-eval, or
  the extractor's recall number is not reproducible.
- **d8 (new, from the run) — sign-blind comparison.** See the false accept above. Surfaced only
  because corruptions were injected; a clean report would have scored 100% on this claim and hidden it.

## Caveats on this spike's numbers
- **Claim-type mix is skewed to `point_value`** (35 of 57; growth 7, share 6, ranking 5, comparison 4).
  The report was generated dense in figures and was kept rather than regenerated, so the compile rate
  is measured mostly against the easiest claim type. Expect the Stage 1 rate on ranking/comparison to
  be materially worse.
- **The base rate of true claims is artificial.** The generator was fed real aggregates, so the clean
  report was almost entirely correct. Six corruptions were injected to make false-accept measurable at
  all — n=6 is enough to expose the sign-blindness bug, not enough to estimate a rate.
- Coverage and compile-and-verify rates both depend on the hand count of 57, which is itself a
  judgment call under LABELING_GUIDE rule 1.

## G1 decision
- rate **68.1%** → [ ] PROCEED (≥60)   [ ] ENRICH CONFIG & RERUN (30–60)   [ ] NARROW V1 (<30)
  *(decision deliberately left unmade — owner's call)*
- what the spike changed about the claim schema / config format:
  1. `subject` must be a first-class field on **every** claim type, not just `ranking` — 13 of 39
     extracted claims could not be bound to an entity from their span alone.
  2. Abstention reasons must distinguish **schema gap** (d3, fixable by config) from **irreducible
     vagueness** (d2, not fixable) — they look identical today and lead the user to opposite actions.
  3. The claim schema needs **direction-only comparison** and **superlative ranking** variants that
     carry no stated value (d5).
  4. Verification must compare **direction as well as magnitude** (d8) — this is the one change that
     removes an actual false accept.
  5. Tolerance belongs in the config as a rule (`half_ulp` worked for all 47 numeric claims), and
     rounding must be pinned per metric because float sums are not order-stable (d6).
  6. A span-matching policy must be fixed before extractor recall is measured (d7).
