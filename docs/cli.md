# Recount CLI

Three commands: `recount init`, `recount verify`, `recount bench`. Everything is a YAML
file plus flags; nothing is persisted between runs. `recount --version` prints the
installed version.

**The API key.** Only live extraction needs one; the quickstart, the test suite, CI and the
benchmark replay do not. `GEMINI_API_KEY` is read from the environment, and if it is not
set there, from a `GEMINI_API_KEY=...` line in a `.env` file in the working directory
(`.env.example` is the template; `.gitignore` covers `.env`). Nothing else is read from
`.env`, and the key is never written to any output.

## Quickstart (the bundled example, no API key)

```bash
uv sync
uv run recount verify examples/olist/report.md \
  --data examples/olist/orders.parquet --config examples/olist/metrics.yml \
  --recordings bench/recordings/extract --html out.html
```

Expected: `40 PASS · 0 FAIL · 11 UNVERIFIABLE · 5 unextracted numeric · 4 rejected`, exit
code 0, and `out.html` with every span coloured. `--recordings` replays the live model's
recorded extraction for exactly this text (the benchmark's recordings); drop it and set
`GEMINI_API_KEY` to extract live.

## Exit codes

| code | meaning |
|---|---|
| 0 | no claim FAILed. UNVERIFIABLE claims and unextracted numerics are reported, not fatal |
| 1 | at least one FAIL. With `--strict`, also any UNVERIFIABLE claim or any unextracted numeric |
| 2 | system error: the run could not produce trustworthy verdicts (below). Partial results are still written when some verdicts exist |

Exit 2 cases, each one sentence plus a link here:

- **artifact** empty, or over the 1 MiB size cap.
- **dataset** unreadable, wrong format (`.csv` / `.parquet` only), over the size or row cap,
  or not matching the config (a column the config names is missing or mistyped).
- **config** not valid YAML (line cited) or not a valid `SemanticConfig` (field path and the
  line of the offending key cited).
- **extraction** invalid twice (the raw output is saved next to the artifact as
  `<artifact>.raw.txt`), no API key, or no recording for this artifact under `--recordings`.
  A missing recording is exit 2, never a silent pass. An upstream failure is reported
  separately as *upstream unavailable*, after the retries below, so a 503 is not confused
  with a model that returned something unusable.
- **upstream unavailable**: the provider returned 5xx / 429 / a transport error on every
  attempt. Live extraction retries a transient failure with exponential backoff (four
  attempts, ~1 s, 4 s, 16 s) before giving up; a content-level failure (invalid JSON, not
  an array) is retried once, since at temperature 0 it usually repeats.
- **engine**: a claim crashed verification. Every other verdict is still emitted; the
  crashed claim shows `policy: error`.

`--strict` is the CI setting for reports that must be fully accounted for: every number
either verified or explicitly explained.

## `recount verify`

```
recount verify REPORT --data DATA --config CONFIG
    [--json OUT] [--html OUT] [--md OUT] [--strict] [--annotations] [--quiet]
    [--claims claims.json | --recording rec.json | --recordings DIR] [--model NAME]
```

- `--json` writes the run record (docs/design.md, the audit record): version, extractor model, artifact / dataset /
  config SHA-256, counts, exit code, per-stage timings, every claim next to its verdict
  (executed SQL, bound parameters, row counts), rejected wire objects, unextracted tokens.
- `--html` writes the annotated report: the artifact as written, spans coloured by verdict
  (green PASS, red FAIL, amber UNVERIFIABLE, grey = a number no claim covers). Click a span
  or press `j` / `k`: claimed vs computed, the delta against the tolerance band, the SQL
  with parameters substituted for display and as executed, row counts; an UNVERIFIABLE
  claim shows its reason and, for a `schema_gap`, a YAML stub to paste. Failures are listed
  first and the first one opens by default. One file, no external assets.
- `--md` writes the same table as Markdown (the Action puts it in the job summary).
- `--annotations` prints GitHub workflow commands: `::error` per FAIL, `::notice` per
  UNVERIFIABLE, `::warning` per unextracted numeric under `--strict`, each with the line.
- `--model NAME` picks the live extractor model. The default is **`gemini-3.6-flash`**
  (`recount.extract.client.MODEL`). The benchmark in docs/benchmark.md ran on
  `gemini-3.1-flash-lite`, which the free tier allows 15 RPM / 500 RPD against the
  default's 5 RPM / 20 RPD; the two extract differently on the same report, so the
  benchmark's numbers belong to that model.
- Offline modes: `--claims` takes pre-extracted claims (a JSON array of Claim objects) and
  runs the deterministic pipeline with no network at all; the file goes through the same
  validation and post-checks as a live response, so a span that is not verbatim in the
  report is rejected. `--recording` replays one recorded extraction; `--recordings DIR`
  picks `DIR/<sha256(report)[:16]>.json`. A recording is bound to the model, prompt,
  schema and artifact and refuses to replay if any changed.

### config

`metrics.yml` binds the report's vocabulary to columns: `time_column`, `entities`
(dimension → column + aliases → stored value) and `metrics` (`agg` sum / count / avg /
share, `column`, `aliases`, `round`, `polarity`, `min_rows`). `polarity` says which
direction of the metric is better — it is needed for "improved / worsened" comparisons and
for rankings written as a quality ("led all states"), and it no longer decides which end a
rank counts from: the claim carries that (`rank_from`). `min_rows` is the rows a group
needs to be in a ranking universe at all; unset means every group ranks, and a subject
below it abstains `no_data` rather than FAILing. Recount verifies against these
definitions and nothing else: a word not listed is an UNVERIFIABLE `schema_gap` with the
key that would fix it, never a guess (docs/abstention.md).

**How a name or alias is matched.** In full, after normalisation — NFKD, accents dropped,
case folded, internal whitespace collapsed — and never as a substring. `norm(the claim's
metric)` must *equal* `norm(a name or alias)`, so the alias `revenue` does not match
"total revenue", and `trip volume` does not match "total trip volume": each wording a
report actually uses needs its own alias line. Business prose prefixes almost everything
("total", "overall", "monthly", "average"), and listing those prefixed forms is the
single cheapest thing you can do to a config. (Whole-word matching is a different check:
the echo gate M3 asks whether the *span* contains the bound metric's wording as whole
words. It can only refuse a binding, never create one.) Aliases must resolve uniquely:
one wording naming two metrics is a config error, which is why matching is not widened
to substrings. `examples/olist/metrics.yml`
is a complete one, including two commented-out opt-in aliases and why they are off.

### dataset

`.parquet` or `.csv`, one row per event, a DATE / TIMESTAMP column for `time_column`,
numeric columns for sum / avg metrics. Caps: 1 GiB, 100M rows (and 1 MiB for the report). The file path goes through
the DuckDB API, never into SQL text; dataset contents never enter any prompt.

## `recount init`

```
recount init --data DATA [--out metrics.yml] [--time-column COL] [--force]
```

Reads the columns and types (nothing else) and writes a commented template: the first
DATE / TIMESTAMP column as `time_column`, a `row_count` metric to rename, `total_` /
`avg_` metrics per numeric column (each with an active `min_rows: 30`, since a mean over
fewer rows than that should not win a ranking), one entity dimension per text column
(id-like columns skipped), and a commented `share` metric. The template loads as written; the aliases are
what you edit. Refuses to overwrite without `--force`.

## promptfoo assertion (`recount-verify`)

`examples/promptfoo/promptfooconfig.yaml` is a runnable worked example:

```yaml
assert:
  - type: python
    value: file://recount_verify.py      # from recount.adapters.promptfoo import get_assert
```

The generated report is the `output`; `recount_data` and `recount_config` come from test
vars, with optional `recount_strict`, `recount_claims` (offline) or `recount_recording`
(keyless replay). The GradingResult passes iff the exit code would be 0, scores
PASS / (PASS + FAIL), carries the summary line and every FAIL in `reason`, and exposes the
counts as `namedScores`. A system error is a failed assertion, never a pass.

## GitHub Action

```yaml
- uses: Samairamalik/Recount@main
  with:
    report: reports/q3.md
    data: data/orders.parquet
    config: metrics.yml
    strict: "true"
    # claims: reports/q3.claims.json      # offline
    # recordings: recordings/              # keyless replay
```

Docker action (`action.yml`, `Dockerfile`): runs `recount verify` with `--json`, `--html`,
`--md` and `--annotations`, appends the verdict table to the job summary, and exits with
Recount's code, so a FAIL blocks the check. Live extraction needs `GEMINI_API_KEY` in the
job's `env`; this repository's own workflow (`.github/workflows/verify-reports.yml`)
replays the committed recordings instead, because keys never enter PR CI. To make the
gate merge-blocking, mark the check required in branch protection and require code-owner review; this
repository's `.github/CODEOWNERS` covers `.github/`, `action.yml` and `Dockerfile` so a PR
cannot edit the gate it is subject to (docs/design.md T9).

## `recount bench`

See docs/benchmark.md. `--config` chooses the verifier's config (the F-3 alias-on row);
the suite itself is always generated from the frozen `bench/suite_config.yml`.
