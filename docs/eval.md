# Extraction eval (Stage 4, with a Stage 5 addendum)

The numbers below are what the extractor measured against the 57 hand labels, whatever
they are. Re-runnable keyless: `uv run pytest tests/extract/test_eval.py` replays the
recording in `tests/fixtures/extract/report.json`; the test pins every number here.

**Stage 5 note.** The Stage 4 sections record the Stage 4 recordings. Both recordings were
re-made on 2026-09-07 after the wire schema changed (every key required-but-nullable,
docs/benchmark.md §6 changelog 1); the current pinned numbers for both models are in the
addendum at the end, and that is where the benchmark's extraction model is stated.

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

## Stage 5 addendum: the model-switch gate, a schema finding, and two models like for like

The dashboard limits for the default pin `gemini-3.6-flash` (5 RPM / 20 RPD) could not carry
the benchmark's ~200 calls, so the owner ruled a switch to `gemini-3.1-flash-lite`
(15 RPM / 500 RPD) behind an honesty gate: re-run this mini-eval live on the lite model and
proceed only at recall ≥ 0.85 with precision 1.0.

**The gate failed first, and the failure was a finding.** On the Stage 4 wire schema the
lite model returned 55 wire objects for the 57 labels, every one with the right type and a
verbatim span, and then omitted keys the schema listed as optional: `subject` on 55/55,
`value` and `direction` on 7/7 growth claims, `period` on 5/5 rankings, `value` on 3/3
comparisons. Pydantic rejected 21 as `invalid_claim` ("Field required"), and the 34 accepted
point values carried no subject, so 17 state-level figures were verified against the
national total: 17 false flags, 0 false accepts, recall 0.5965. The Stage 0 failure mode
(subject as the sole carrier of the entity) had come back through a different door: a
JSON-schema-constrained output only promises the keys it is told are required.

**The change (changelog 1):** every wire key is now required; the non-`WIRE_REQUIRED` ones
stay nullable, so a model must write an explicit null and the unchanged post-validation
rejects it where the type needs a value. Both Stage 4 recordings were re-made on the
default model so the two models are measured on the same schema.

| | 3.6-flash, Stage 4 schema | 3.6-flash, required schema | flash-lite, Stage 4 schema | flash-lite, required schema |
|---|---|---|---|---|
| claims accepted / rejected | 62 / 0 | 63 / 0 | 34 / 21 | 51 / 4 (`foreign_field`) |
| matched · merged · missed · spurious | 55 · 0 · 2 · 7 | 55 · 0 · 2 · 8 | 34 · 0 · 23 · 0 | 51 · 1 · 5 · 0 |
| **recall** | 0.9649 | **0.9649** | 0.5965 | **0.8947** |
| **precision** | 0.8871 | **0.873** | 1.0 | **1.0** |
| span validity | 1.0 | 1.0 | 1.0 | 1.0 |
| subject binding | 28/28 | 28/28 | 0/18 | 28/28 |
| metric binding | 54/55 | 55/55 | 34/34 | 45/51 |
| verdict agreement (agree / false accept / false flag / other) | 54 / 0 / 0 / 1 | 54 / 0 / 0 / 1 | 17 / 0 / 17 / 0 | 47 / 0 / 0 / 4 |
| sweep flagged the numeric misses | 1/1 | 1/1 | 13/13 | 4/4 |
| latency of the one call | n/a | n/a | 10.8 s | 19.2 s |

Gate re-applied on the required schema: recall 0.8947 ≥ 0.85, precision 1.0 → the benchmark
runs on `gemini-3.1-flash-lite`, extractor and judge alike. **The default pin in
`extract/client.py` is unchanged (`gemini-3.6-flash`)**; the benchmark states its own model.

What the lite model still does differently, all visible in the pinned numbers: it merges
c28 into a neighbour; it misses the three "delivery time … days" point values that share a
sentence with a growth or ranking claim (c18, c24, c29; every one flagged by the sweep);
it names ranking metrics in words the config does not alias ("fulfillment speed"), so four
rankings abstain `schema_gap` where the labels expect a verdict, including c41, the
spike's wrong_ranking corruption; and it writes non-null `direction` on some point values,
which the foreign-field check rejects (their numbers fall to the sweep). The default
model's recall is unchanged by the schema change; its precision moved from 0.8871 to
0.873 because it returned one more true-but-unlabeled claim.

End-to-end on the clean report with the re-made default-model recording: 61 claims
accepted, 0 rejected, **56 PASS / 5 UNVERIFIABLE / 0 FAIL** (Stage 4: 66 / 58 / 8 / 0).

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

## Stage 6 addendum: the echo gate read on the same recordings

Neither recording changed in Stage 6 (prompt, schema and artifact are untouched, so the
fingerprints still match). What changed is the compiler: abstention row M3 refuses a
metric binding the span does not echo (docs/abstention.md, ruled F-2), and the extractor
rejects a comparison or growth value written as a level (F-4). Only the verdict-agreement
column moves; recall, precision and every binding number are identical to the table above.

| | 3.6-flash, Stage 5 | 3.6-flash, changelog 5 | 3.6-flash, changelog 7 | flash-lite, Stage 5 | flash-lite, changelog 5 | flash-lite, changelog 7 |
|---|---|---|---|---|---|---|
| verdict agreement (agree / false accept / false flag / other) | 54 / 0 / 0 / 1 | 44 / 0 / 0 / 11 | **46 / 0 / 0 / 9** | 47 / 0 / 0 / 4 | 42 / 0 / 0 / 9 | **44 / 0 / 0 / 7** |
| of which `metric_echo_failed` on a label the fixture marks `echo_gap` (F5) | – | 9 | 7 (c16 c17 c23 c26 c34 c36 c41) | – | 5 | 3 (c16 c17 c26; the lite model abstains M2 on c23/c34/c36/c41's "fulfillment …"/"commercial …" wording) |
| other new abstention | – | 1: label c24 "a year-low" matched a ranking whose span is just those words | 1 (same) | – | – | – |
| end-to-end on `report_clean.md` (PASS / UNVERIFIABLE / FAIL) | 56 / 5 / 0 | 41 / 20 / 0 | **43 / 18 / 0** | 43 / 8 / 0 | 38 / 13 / 0 | **40 / 11 / 0** |

Read: the default model writes tight spans ("11.41 days", "to 14.28 days", "a year-low")
and binds the metric from the sentence, which is exactly the binding M3 refuses, so it
loses thirteen clean verdicts to the echo gate where the lite model, whose spans carry
more of the sentence, loses three (changelog 7 returned the two "days for delivery"
spans on both). No false accept and no false flag on either model,
before or after; what M3 buys (docs/benchmark.md changelog 5) is paid for in coverage,
and this table is where the price is written down.

## Stage 8 addendum: the gate re-run because the prompt changed

`Ranking` gained `rank_from` (docs/benchmark.md changelog 8) and the prompt gained the
paragraph that teaches it, plus the sentence that carries an entity ranking's stated
universe into `scope` (changelog 9). A prompt or schema edit invalidates every recording by
construction, so both fixtures were re-recorded live on 2026-09-08 and the owner's honesty
gate — recall ≥ 0.85 with precision 1.0 on the benchmark's model — was re-applied before
the 96 benchmark recordings were spent.

| | 3.6-flash, changelog 7 | 3.6-flash, Stage 8 | flash-lite, changelog 7 | flash-lite, Stage 8 |
|---|---|---|---|---|
| claims accepted / rejected | 63 / 0 | 56 / 0 | 51 / 4 | 51 / 4 |
| matched · merged · missed · spurious | 55 · 0 · 2 · 8 | 55 · 0 · 2 · 1 | 51 · 1 · 5 · 0 | 51 · 0 · 6 · 0 |
| **recall** | 0.9649 | **0.9649** | 0.8947 | **0.8947** |
| **precision** | 0.873 | **0.9821** | 1.0 | **1.0** |
| span validity | 1.0 | 1.0 | 1.0 | 1.0 |
| subject binding | 28/28 | 28/28 | 28/28 | 28/28 |
| metric binding | 55/55 | 52/55 | 45/51 | 47/51 |
| rank binding | 5/5 | 5/5 | 5/5 | 5/5 |
| verdict agreement (agree / false accept / false flag / other) | 46 / 0 / 0 / 9 | 46 / 0 / 0 / 9 | 44 / 0 / 0 / 7 | 44 / 0 / 0 / 7 |
| end-to-end on `report_clean.md` (PASS / UNV / FAIL) | 43 / 18 / 0 | 42 / 13 / 0 | 40 / 11 / 0 | **40 / 11 / 0** |

**Gate: passed.** flash-lite recall 0.8947 ≥ 0.85, precision 1.0, unchanged to four decimal
places. The default model's recall is likewise unchanged; its precision rose from 0.873 to
0.9821 because it returned seven fewer unlabelled-but-true claims on this run — extraction
is not a function of the text at temperature 0 (F-4), and a re-record is the clearest
demonstration of that: same model, same prompt-plus-report, different day, different claim
count. That is also why the re-record was done *after* the verifier change had been measured
on the oracle path with extraction held fixed.

The lite model's clean-report end-to-end is unchanged to the count (40 / 11 / 0 on 51
accepted claims, 4 rejected), which is the number the README quickstart prints; the default
model's moved from 43 / 18 / 0 on 61 claims to 42 / 13 / 0 on 55, because it returned fewer
claims this time. Neither is a verifier change.

**`rank_from` in the wild.** Both models filled it on every ranking, and read the sentence
rather than the config: `best` for quality wording ("took the lead", "peak fulfillment
efficiency", "secured the second position"), `lowest` for "a year-low of 11.41 days",
`highest` for "to peak at 17,280 orders". Rank binding against the labels stayed 5/5. The
`invalid_claim` rejections on the lite run are the pre-existing wire-schema union on
`direction` (a growth word typed onto a comparison), not the new field; both of those spans
are levels that changelog 3's post-check rejects anyway.

