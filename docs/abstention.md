# Abstention decision table (Stage 3)

This document is the compiler's specification. `src/recount/compile/compiler.py`
must match it row for row, and every branch in the code cites a row id below.
When a situation is not in this table, the compiler abstains (`ambiguous`) and the
missing row is added here first. The table never grows a guess.

Reviewed row by row on 2026-09-06; rulings are folded in. Row V6 is authored by
the project owner.

## 0. Contract

```
compile_claim(claim: Claim, cfg: SemanticConfig) -> ComputePlan | Abstain
Abstain(reason: AbstainReason, detail: str)      # frozen
```

- Deterministic, pure. Reads only the Claim's typed fields; never `span`, never
  the dataset, never the clock. No LLM (wall 1), no SQL (wall 2).
- Everything resolvable is resolved through `SemanticConfig` only. The config
  defines meaning; it never caches facts about the data (no coverage fields).
- `detail` is a one-line, user-facing diagnostic naming the offending field and,
  for `schema_gap`, the config key that would fix it.

### 0.1 Normalisation `norm(s)`

Applied to both sides of every vocabulary match (metric names and aliases,
entity alias keys and stored values, `group_by`, entity dimension names):

1. Unicode NFKD, then drop combining marks ("São" → "Sao", "Paraná" → "Parana")
2. `casefold()`
3. collapse internal whitespace to one space; strip ends

So "São Paulo", "sao paulo" and "SAO  PAULO" all equal "sao paulo".

### 0.2 Evaluation order (first matching row wins)

1. **M** metric resolution
2. **E** / **G** subject and group_by resolution, polarity, displaced
3. **X** claim type vs metric kind
4. **D** / **V1–V5** direction and vagueness
5. **P** period parsing (period, baseline, scope)
6. **V6** and **G8/G11**: checks that need parsed intervals
7. build the plan; **N** rows are raised by the engine at verify time

Schema gaps are reported before vagueness on purpose: a `schema_gap` is the one
abstention the user can fix in YAML, and once fixed the vagueness row (if any)
surfaces honestly on the next run. Motivating fixture: c30 has both an unknown
entity and no baseline; the label is `schema_gap`.

Rows the engine's policies also check (D1, D2, G10, V1–V3) are decided here
first; the policy branches stay as defence in depth, not as the spec.

## 1. Rows

Legend — outcome: **plan** = a ComputePlan is built; **abstain** = `Abstain`.
Fixture ids refer to `tests/fixtures/labeled_claims.json`; "synthetic" means a
Stage 3 unit test constructs the claim/config.

### M — metric

| id | condition | outcome | reason | detail | fixture |
|---|---|---|---|---|---|
| M1 | `norm(metric)` equals `norm(name)` or `norm(alias)` of exactly one config metric | plan (continue) | — | — | c2 `orders`, c3 `revenue`, and every other fixture |
| M2 | no config metric matches | abstain | `schema_gap` | `unknown metric '{metric}'; config metrics: {names}` | c1 `state_count` (F1) |

Measure built from the resolved metric: `agg` sum/count/avg pass through;
`agg: share` becomes `count` of rows (row X1); `column` and `round` pass through.
Two metrics matching after `norm()` cannot happen: config validation rejects it (C1).

### E — subject on point_value, growth, comparison, share

| id | condition | outcome | reason | detail | fixture |
|---|---|---|---|---|---|
| E1 | `subject` is null (point_value, growth, comparison) | plan, no entity filter: the whole dataset in the period | — | — | c2, c13, c17 |
| E2 | `norm(subject)` equals a normalised alias **key or stored value** of one entities dimension; resolution is purely from config (no dataset access, no separate values list) | plan, `EntityFilter(column, value)` | — | — | c31 "Sao Paulo" → SP; "São Paulo" and "SP" (synthetic) |
| E3 | *retired*: a token matching two dimensions cannot happen, config validation rejects it (C4) | — | — | — | — |
| E4 | matches nothing | abstain | `schema_gap` | `unknown entity '{subject}'; add it under entities.<dim>.aliases` | c30 "Southeast and South regions" |

(`share` requires a subject at the schema level, so E1 never applies to it.)

### G — ranking: group_by, subject, polarity, displaced, scope

Evaluated in the order G1–G3, G4–G6, G7, G9, G10, then the P rows on `period`
and `scope`, then G8/G11.

| id | condition | outcome | reason | detail | fixture |
|---|---|---|---|---|---|
| G1 | `norm(group_by)` ∈ {`month`, `quarter`, `year`} | `TimeKey(grain)` on `time_column` — **checked before entities, never resolved from them** (BINDING b) | — | — | c23 |
| G2 | else `norm(group_by)` equals a normalised entities dimension name | `EntityKey(column)` | — | — | c34, c36, c41 |
| G3 | else | abstain | `schema_gap` | `group_by '{group_by}' is neither an entities dimension ({dims}) nor a time grain (month, quarter, year)` | synthetic ("region") |
| G4 | entity ranking, `subject` null | abstain | `ambiguous` | `ranking needs a subject: who holds rank {rank}?` | synthetic |
| G5 | entity ranking, `norm(subject)` is not an alias key/value **of that dimension** (a match in another dimension does not count) | abstain | `schema_gap` | `'{subject}' is not a '{group_by}' alias; add it under entities.{group_by}.aliases` | synthetic |
| G6 | time-grain ranking with `subject` set ("SP's best quarter") | abstain | `unsupported_claim_type` | `ranking {grain}s within an entity is not supported; RankPlan has no entity scope` | synthetic |
| G7 | time-grain ranking, grain = `year` | abstain | `no_data` | `ranking years is withheld: a partly covered year would rank against full ones` — a **stopgap** for partial-year data coverage, superseded by the runtime check in P12 (the only `no_data` the compiler raises) | synthetic |
| G8 | time-grain ranking (month/quarter): `period` must parse to **exactly one unit of that grain** (the subject key is that unit's start date) and `scope` must parse and contain that unit; the universe is `scope` | plan | — | period not one unit: abstain `ambiguous`, `period '{period}' is not a single {grain}; which {grain} holds rank {rank}?`; scope null: abstain `ambiguous`, `no scope stated: rank {rank} among which {grain}s?`; unit outside scope: abstain `ambiguous`, `period '{period}' lies outside scope '{scope}'` | c23 (`2017-Q3`, scope `2017`, F3); synthetic `2017` + quarter, and scope null |
| G9 | ranking metric has no `polarity` | abstain | `schema_gap` | `ranking by '{metric}' needs polarity (rank 1 = best); set metrics.{metric}.polarity` | synthetic (polarity removed) |
| G10 | `displaced` is set (any non-null value; `"unspecified"` is the reserved value for an unnamed party) | abstain | `unsupported_claim_type` | `'displaced {displaced}' asserts an overtaking, a rank change between two periods; rank-change verification is not supported` — the sentence is precise; the tool lacks the capability | c11 (F2) |
| G11 | entity ranking with `scope` set | abstain | `ambiguous` | `scope '{scope}' on an entity ranking conflicts with period '{period}'; the period is the universe` | synthetic |

`scope` is a Stage 1 amendment to `Ranking` (logged in docs/learning-log.md like
`NO_DATA`): the period string naming the ranking universe of a time-grain
ranking ("of the year" → `2017`). Nothing is ever inferred from a calendar.

### D — comparison direction and polarity

| id | condition | outcome | reason | detail | fixture |
|---|---|---|---|---|---|
| D1 | `direction = unchanged` | abstain | `ambiguous` | `'unchanged' has no threshold` | c5 |
| D2 | `direction ∈ {better, worse}` and the metric has no `polarity` | abstain | `schema_gap` (BINDING a) | `'{direction}' needs metrics.{metric}.polarity` | synthetic: c17 with polarity removed |
| D3 | `direction ∈ {better, worse}` with polarity | `ComparePlan(polarity=…)` | — | — | c17 |
| D4 | `direction ∈ {higher, lower}` | `ComparePlan` (polarity passed through, unused) | — | — | c7 would reach here but V5 fires first |

Comparison `value` is a non-negative magnitude (`ge=0`), like growth: the sign
lives only in `direction`, so a sign/direction conflict is impossible by
construction and there is no detection row.

### V — stated value and vagueness

| id | condition | outcome | reason | detail | fixture |
|---|---|---|---|---|---|
| V1 | point_value `value` null | abstain | `ambiguous` | `no stated value; '{metric}' is asserted without a number` | synthetic ("substantial revenue") |
| V2 | share `value` null | abstain | `ambiguous` | `no stated share` | synthetic |
| V3 | growth `value` null | abstain | `ambiguous` | `no stated growth magnitude` | c12 "nearly doubled" |
| V4 | comparison `value` null with higher/lower/better/worse | plan (direction-only check) | — | — | c17 |
| V5 | growth or comparison `baseline_period` null | abstain | `ambiguous` | `no baseline period: '{metric}' in {period} is compared against what?` | c7 ("two weeks" is a constant, not a period); c5 second reason |
| V6 *(authored by the project owner)* | growth or comparison whose parsed baseline **starts on or after** the period starts | abstain | `ambiguous` | `baseline '{baseline}' does not precede period '{period}'; growth and comparison run backwards in time` | synthetic; plus c17 and c13 with period and baseline swapped |

V6 rationale: growth and comparison must run backwards in time; a forward or
equal baseline means the extractor swapped the periods or the sentence is
unclear. V6 subsumes the earlier "baseline equals period" row (P10, retired).
Evaluated after P because it needs both intervals.

V3 note: the Growth schema cannot distinguish "grew" (direction-only, checkable)
from "nearly doubled" (vague magnitude); both carry `value: null`. Stage 3 follows
the fixture and abstains on both. This is known lost coverage (learning-log,
design consequence 3/3), to be revisited with a schema change, not a compiler guess.

### X — claim type vs metric kind

| id | condition | outcome | reason | detail | fixture |
|---|---|---|---|---|---|
| X1 | share claim; metric agg ∈ {sum, count, share} | `SharePlan`; a `share` metric measures the row count | — | — | c33, c39 |
| X2 | share claim; metric agg = avg | abstain | `ambiguous` | `a share of an average is not defined` | synthetic |
| X3 | point_value claim; metric agg = share | abstain | `unsupported_claim_type` | `'{metric}' is a share; a point_value claim cannot carry a share (the engine pairs point_value with aggregate plans)` | synthetic |
| X4 | growth or comparison claim; metric agg = share | abstain | `unsupported_claim_type` | `growth/comparison of a share is not supported; compiling it would silently compute the count, not the share` | synthetic |
| X5 | ranking claim; metric agg = share | `RankPlan` on the row count (within one period, ordering by share equals ordering by count) | — | — | synthetic |

Shares are shares of the period total by construction: a `share` metric's
denominator is the period-level row count, and config validation rejects any
other definition (a `share` metric takes no `column`).

### P — periods (`period`; `baseline_period` on growth/comparison; `scope` on ranking)

Grammar, after trim and whitespace collapse, case-insensitive. Every form
yields a half-open `[start, end)`:

| form | examples | interval |
|---|---|---|
| year | `2017` | `[2017-01-01, 2018-01-01)` |
| quarter | `2017-Q3`, `2017Q3`, `2017 Q3`, `Q3 2017`, `Q3-2017` | `[2017-07-01, 2017-10-01)`; Q4 → `[2017-10-01, 2018-01-01)` |
| month | `2017-07`, `July 2017`, `Jul 2017`, `2017 July` | `[2017-07-01, 2017-08-01)`; Dec → next Jan 1; Feb 2016 → `[2016-02-01, 2016-03-01)` (29 days) |
| day | `2017-07-15` (valid calendar date) | `[2017-07-15, 2017-07-16)`; `2016-02-29` valid, `2017-02-29` is P7 |
| range | `A to B`, `A..B`, `A – B`, `A - B` (spaced hyphen), A and B any single form | `[A.start, B.end)`; the written end is inclusive, so `2017-01-01 to 2017-06-30` → `[2017-01-01, 2017-07-01)` |

A bare hyphen never makes a range: `2017-2018` is unparseable while `2017 to
2018` parses, because the hyphen is already the ISO separator inside `2017-07`
and `2017-07-15`, and `2017-18` could be a fiscal year or a mistyped month.

| id | condition | outcome | reason | detail | fixture |
|---|---|---|---|---|---|
| P1 | year form | plan | — | — | c2 |
| P2 | quarter form | plan | — | — | c8 (Q1), c25 (Q4 ends 2018-01-01) |
| P3 | month form | plan | — | — | synthetic |
| P4 | day form | plan | — | — | synthetic |
| P5 | range form with `A.start ≤ B.start` and `A.end ≤ B.end` | plan | — | — | synthetic |
| P6 | `period` null | abstain | `ambiguous` | `no period stated; the compiler never assumes the whole dataset` | synthetic |
| P7 | any other text: `first quarter`, `Q3` (no year), `H1 2017`, `FY2017`, `2017-2018` (bare hyphen range), `2017-13`, `2017-02-29`, relative words (`last year`, `YTD`: no anchor date exists, the tool never reads the clock) | abstain | `ambiguous` | `cannot parse period '{period}'; accepted forms: YYYY, YYYY-Qn, YYYY-MM, YYYY-MM-DD, Month YYYY, or 'A to B'` | synthetic |
| P8 | range with B before A in either endpoint (`2017-Q3 to 2017-Q1`) | abstain | `ambiguous` | `period range '{period}' ends before it starts` | synthetic |
| P9 | `baseline_period` or `scope` null / unparseable / reversed | as P6/P7/P8 with the field name ("baseline period", "scope") in the detail | `ambiguous` | — | c7 (null baseline) |
| P10 | *retired*: subsumed by V6 | — | — | — | — |
| P11 | baseline overlaps but differs (`2017-Q4` vs `2017`) and satisfies V6 | plan | — | — | synthetic — a defined computation |
| P12 | period outside or partly outside the data range | **documented Stage 3 limitation.** The compiler never sees the dataset. An empty slice becomes engine `no_data` (N1–N4). A partly covered period computes over the rows present and is **not flagged**. This is a **false-PASS path**, not a warning: "2017-Q1 revenue was 813,052.64" over data that starts Jan 5 can PASS against a truth the data does not contain. | — | — | c11's Jan 5 start is the example |

P7 note: impossible dates (`2017-02-29`, `2017-13`) are extraction errors, not
sentence vagueness; they share `ambiguous` today and would take a distinct code
if the reason taxonomy ever grows.

### N — engine-time abstentions (Stage 2, unchanged; listed for completeness)

| id | condition | reason | detail |
|---|---|---|---|
| N1 | aggregate/share slice empty or whole = 0 | `no_data` | engine |
| N2 | growth baseline empty or zero | `no_data` | engine |
| N3 | comparison current or baseline empty | `no_data` | engine |
| N4 | ranking subject not among the groups | `no_data` | engine |

## 2. Config-level rules (enforced in `SemanticConfig` validation)

| id | rule | why |
|---|---|---|
| C1 | metric name/alias uniqueness is checked under `norm()` | otherwise M1 could match two metrics |
| C2 | subsumed by C4 | — |
| C3 | an entities dimension whose `norm()` name is `month`/`quarter`/`year` is an error | G1 would shadow it silently |
| C4 | across **all** dimensions combined, every normalised alias key and stored value resolves to exactly one (dimension, stored value); a token that would resolve to two is an error. No key or value may normalise to `unspecified` (reserved sentinel for `displaced`). | makes E2 a lookup with no second answer, so E3 cannot occur |
| C5 | a `share` metric takes no `column`: its denominator is the period-level row count, and no other definition is accepted | X1/X5 rest on "share of the period total" |

## 3. Fixture amendments (visible, logged in docs/learning-log.md)

| id | claim | before | after | why |
|---|---|---|---|---|
| F1 | c1 "Across all 27 states", metric `state_count` | `PASS` | `UNVERIFIABLE`, `schema_gap` | the config has no `state_count` and the engine has no COUNT DISTINCT aggregate; with this config a correct verifier abstains (dilemma d1's lesson). COUNT DISTINCT is deferred, see §5. |
| F2 | c11 "took the lead", ranking | no `displaced` | `displaced: "unspecified"`, `expected_reason: unsupported_claim_type` | non-null `displaced` means the text asserts an overtaking; the sentence is precise and the tool lacks rank-change verification (G10). |
| F3 | c23 "peak fulfillment efficiency of the year" | no `scope` | `scope: "2017"` | the span says "of the year"; the universe is stated, not inferred (G8). |

After F1 the 57 fixtures split PASS 45 / FAIL 6 / UNVERIFIABLE 6.

## 4. Schema amendments (Stage 1 contracts, amended visibly)

- `Ranking.scope: str | None = None` — the ranking universe as written.
- `Comparison.value` gains `ge=0` — unsigned magnitude, sign only in `direction`.

## 5. Known limitations and deferred work

- **COUNT DISTINCT** (c1): no `count_distinct` aggregate in Metric/Measure/engine. Deferred; c1 abstains `schema_gap` until it exists.
- **P12, data coverage** — V2 engine TODO, a **false-PASS path**: at run time, query
  min/max of the time column and abstain `no_data` when the period, the baseline,
  or any period in a ranking universe is not fully inside the data. Never a
  config field: config defines meaning, it does not cache facts about the data.
  G7 (year rankings withheld) is the compiler-side stopgap until then.
- **V3, direction-only growth** is abstained along with vague growth (schema cannot tell them apart).
- **Rank change** (G10): "overtook" claims need two rankings and a comparison of ranks; not supported.
