# Chicago taxi 2025 — a reference example, not a runnable quickstart

**This example does not run out of the box, and that is deliberate.** The dataset is
6,825,838 trips (66 MB of Parquet) built from twelve monthly Socrata pulls, which is far too
large to commit; `rebuild.sh` fetches and rebuilds it in a few minutes. A sampled subset
*would* fit, but every number in `report.md` is computed over the full year, so a sample
would verify nothing — the claims and the data would be a different experiment wearing the
same name. Run it by rebuilding the dataset, or read it as a worked example of a config and
a report on data this project had never seen.

For a quickstart that runs immediately and needs no API key, use `examples/olist/`.

## What these files are

| file | what it is |
|---|---|
| `report.md` | a ~15-claim business report written by `gemini-3.6-flash` from a deterministic aggregate summary of the data (prompt below), 2026-09-08 |
| `metrics.yml` | the semantic config, hand-edited from `recount init` output during the acceptance run, then updated for v0.2.0 where the run had to work around a defect — the two changed lines carry comments saying so |
| `claims.v0.1.0.json` | the 60 claims the extractor produced from `report.md` on 2026-09-08, kept exactly as captured |
| `rebuild.sh` | rebuilds `chicago_taxi_2025.parquet` from the City of Chicago data portal |

`claims.v0.1.0.json` predates `Ranking.rank_from` (v0.2.0), so replaying it today abstains
`ambiguous` on all 13 ranking claims: no claim recorded before the field existed is read as
if it had named an end (abstention G12). That is the fail-closed behaviour working, and it
is why the file is named for the version that produced it rather than being edited to look
current — hand-adding a field to recorded model output would be fabricating an extraction.
A live run against the same report produces claims that carry the field.

## Running it

```bash
cd examples/chicago
./rebuild.sh                      # ~3 min, ~66 MB, needs curl + duckdb
cd ../..
uv run recount verify examples/chicago/report.md \
  --data examples/chicago/chicago_taxi_2025.parquet \
  --config examples/chicago/metrics.yml --html chicago.html
```

That extracts live and needs `GEMINI_API_KEY`. To see the deterministic half only, with no
network, add `--claims examples/chicago/claims.v0.1.0.json` and read the ranking claims'
abstentions as described above.

## How the report was written

The dataset was summarised deterministically (totals, per-quarter and per-month figures,
per-company and per-payment-type aggregates) and that summary — never the raw rows — was
given to `gemini-3.6-flash`, which was asked for "about 15 specific, checkable numeric
claims", a mix of totals, quarter-over-quarter growth, comparisons, shares and rankings,
each naming its period and metric in words, as flowing prose. The report is what it
returned, unedited. Recount never saw the summary: the extractor reads `report.md` and
nothing else.

## Attribution and disclaimer

Source: **City of Chicago** — [Taxi Trips (2024–)](https://data.cityofchicago.org/resource/ajtu-isnz),
City of Chicago Data Portal, calendar year 2025, columns `trip_start_timestamp`, `company`,
`payment_type`, `trip_total`, `fare`, `tips`, `trip_miles`, `trip_seconds`. Published under
the [Chicago Data Terms of Use](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html),
which permit use and redistribution with attribution and require this disclaimer to
accompany derivative works:

> This site provides applications using data that has been modified for use from its
> original source, www.cityofchicago.org, the official website of the City of Chicago. The
> City of Chicago makes no claims as to the content, accuracy, timeliness, or completeness
> of any of the data provided at this site. The data provided at this site is subject to
> change at any time. It is understood that the data provided at this site is being used at
> one's own risk.

No City of Chicago data is committed to this repository: `rebuild.sh` fetches it from the
portal. `report.md` is model-written prose about aggregates of that data; the aggregates
themselves are reproducible from the rebuilt Parquet.

The Recount code is Apache-2.0 (repository `LICENSE`); these terms cover the example data.

## Where this example comes from

The v0.1.0 acceptance run, written up in [docs/design.md §9](../../docs/design.md). Short
version: every number Recount computed matched independently written DuckDB queries to the
digit, and three design defects turned up, all in ranking, all producing confident FAILs on
true sentences — which is what v0.2.0 fixes.
