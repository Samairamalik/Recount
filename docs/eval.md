# Extraction eval (Stage 4)

The numbers below are what the extractor measured against the 57 hand labels, whatever
they are. Re-runnable keyless: `uv run pytest tests/extract/test_eval.py` replays the
recording in `tests/fixtures/extract/report.json`; the test pins every number here.

## Method

- **Artifact:** `spike/report.md`, the report the labels were made on (all 57 label
  spans exist in it verbatim). The clean report is the end-to-end smoke, below.
- **Ground truth:** `tests/fixtures/labeled_claims.json`, 57 claims: 35 point_value,
  7 growth, 6 share, 5 ranking, 4 comparison.
- **Extractor:** one `gemini-3.6-flash` call, temperature 0, response schema derived
  from the Claim models (`extract/extractor.py: wire_schema`), Pydantic re-validation,
  reject-don't-repair post-checks, numeric sweep over accepted spans.
- **Matching policy (spike dilemma d7):** label and claim spans are located at their
  first occurrence; overlapping pairs are matched one-to-one, largest overlap first,
  ties by document order. A label whose only overlapping claim was taken by another
  label is *merged*; other unmatched labels are *missed*; unmatched claims are
  *spurious*. Recall = matched / 57, precision = matched / accepted claims.
- **Binding accuracy:** on matched pairs, per field, after the compiler's own
  normalisation (metric and subject through the config vocabulary, periods through the
  period parser). "Right" means the compiler would resolve both sides identically.
- **Verdict agreement:** each matched claim is also run through `verify_claim` and its
  verdict compared with the label's `expected_verdict`.

## Numbers

| | iteration 1 | iteration 2 (shipped) |
|---|---|---|
| claims accepted / rejected | 53 / 3 | 62 / 0 |
| matched labels | 52 | 55 |
| merged / missed / spurious | 0 / 5 / 1 | 0 / 2 / 7 |
| **recall** | **0.9123** | **0.9649** |
| **precision** | **0.9811** | **0.8871** |
| span validity | 1.0 | 1.0 (asserted by construction) |
| verdict agreement on matched | 52 / 52 | 54 / 55 |
| false accepts / false flags | 0 / 0 | 0 / 0 |
| sweep flagged the numeric misses | 1 / 1 | 1 / 1 |

Field-level binding accuracy, iteration 2 (correct / checked):

| field | metric | period | subject | direction | type | value | baseline | rank | group_by | displaced | scope |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | 54/55 | 55/55 | 28/28 | 10/10 | 53/55 | 47/50 | 8/8 | 5/5 | 5/5 | 1/1 | 1/1 |

Every ranking field, every direction, every period and every subject bound correctly.
The subject result matters most: 13 of the spike's 39 claims had spans naming no
entity, and all 28 subject-bearing labels here bound to the right state.

## The one iteration (a bug, not a prompt change)

Recall after the first run was above the 0.8 gate, so no prompt iteration was owed.
The three rejections, though, were all comparisons the model *had* found (c5, c7,
c17, with the right span, metric and period) and emitted with `direction: null` or
`"decrease"`, which the Comparison model refuses. Cause: the flat wire schema took
`direction` from the first Claim class declaring it (Growth), so the wire enum was
`increase | decrease` and the model could never emit `higher/lower/better/worse/
unchanged`. The fix merges per-class enums into their union
(`extractor.py: _merge`), pinned by
`test_wire_schema_direction_admits_growth_and_comparison_vocabularies`. The prompt
was not touched. Both recordings were re-made and both numbers are kept above.

The precision drop between iterations is a real consequence of the fix: once
comparison directions were representable, the model also split sentences of the form
"causing average delivery times to stretch to 14.28 days" into a comparison and a
point_value where the labeler wrote one claim. See the table.

## Failure modes (iteration 2)

| id | span | kind | what happened | hypothesis |
|---|---|---|---|---|
| c1 | "Across all 27 states" | missed | Not extracted (also not in iteration 1). The sweep reports `27 states` as unextracted. | "27 states" is a count of a dimension, not of a metric; nothing in the prompt names entity counts as claims. The label itself is a schema_gap abstention (no COUNT DISTINCT), so no coverage of a verifiable claim was lost. |
| c30 | "heavily concentrated in the Southeast and South regions" | missed | Not extracted in either iteration. | The sentence states no direction word and no comparand; the prompt's comparison examples are all "X improved / fell / remained stable". A lost *abstention* (expected schema_gap), not a lost verdict. |
| c11 | "Sao Paulo took the lead in the first quarter" | misbound metric | Extracted with `displaced: "unspecified"` as intended; metric `revenue`, label says `orders`. | The sentence names no measure (spike dilemma d4). The compiler abstains G10 on `displaced` before the metric matters, so the verdict agrees. |
| c33 | "representing roughly two-fifths of all orders at 39.31%" | split, verdict UNVERIFIABLE vs PASS | The model emitted two shares: "representing roughly two-fifths of all orders" (value null) and "at 39.31%" (value 39.31). The label matched the vague half by overlap; the numeric half is counted spurious and verifies PASS on its own. | The one-claim-per-assertion rule was applied to a sentence the labeler treated as one assertion. The number is verified either way; only the eval's one-to-one accounting calls it a mismatch. |
| c29 | "causing average delivery times to stretch to 14.28 days" | split, type point_value vs comparison | Comparison "…to stretch" (higher, vs 2017-Q3, PASS) matched the label; point_value "14.28 days" is spurious and PASSes. | Same split behaviour; both halves are true claims. |
| c24 | "reducing average delivery times to a year-low of 11.41 days" | split, type point_value vs ranking | Ranking "year-low" (rank 1 by quarter, scope 2017, PASS) matched; point_value "11.41 days" is spurious and PASSes. | Same. The ranking reading is arguably the stronger claim in the sentence. |
| spurious c1, c8 | "steady quarter-over-quarter volume gains", "order volume spikes in the second half of the year" | spurious, abstain | Vague growth claims the labeler did not label; both abstain `ambiguous` (c8's period `2017-H2` is outside the grammar, as designed). | Prompt asks for vague claims with confidence low; the labels under-count them. |
| spurious c27, c31 | "record-breaking fourth quarter", "to peak" | spurious, would PASS | Quarter rankings (rank 1 by quarter, scope 2017) that the labeler did not label; both are true. | Superlative vocabulary in the prompt ("peak", "top") fires on "record-breaking" and "peak at". Unlabeled true claims, not hallucinations. |
| iteration 1 only: c5, c7, c17 | comparisons | rejected `invalid_claim` | `direction` null / "decrease" on a comparison. | Wire schema bug, fixed above. |

Hallucinated claims: none. Every one of the 62 accepted spans is verbatim in the
artifact (the check is deterministic and cannot be bypassed), and every spurious claim
is a real assertion in the text.

## What the sweep caught

One token in each artifact: `27 states` (`Across all 27 states`). Every other numeric
token in the report sits inside an accepted claim's span. The sweep is what turns the
extractor's one numeric miss into a visible line rather than a silent gap; with
`--strict` (Stage 6) it will fail the run.

## End-to-end smoke on the clean report

`spike/report_clean.md` through `pipeline.run` with the recording in
`tests/fixtures/extract/report_clean.json`: 66 claims accepted, 0 rejected,
**58 PASS, 8 UNVERIFIABLE, 0 FAIL**. No false flags on a clean report. The
abstentions are the vague growth claims, "remained stable" (unchanged), "well under two
weeks" (no baseline), "took the lead" (unsupported rank change) and "roughly
two-fifths" (no stated share), each with the reason the abstention table prescribes.

## Caveats

- One report, one model, one temperature. The label set is dense in point_value
  (35 of 57); comparison and ranking are measured on 4 and 5 examples.
- Precision is bounded above by label granularity: three of the seven spurious claims
  are halves of sentences the labeler treated as one claim, and four are true
  assertions the labels omit. A second labeling pass (Stage 5 adds 20 sentences)
  should decide the split rule before the next measurement.
- The recordings are bound to the model id, the prompt, the artifact and the wire
  schema; `MockClient` refuses a stale one. Changing any of them means re-recording
  with `python -m recount.extract.record` and re-reading this document.
