# Recount

**Deterministic verification of numeric claims in LLM-generated reports.**

LLMs writing about data confidently state wrong numbers. Recount takes a report,
the source dataset (CSV/Parquet), and a small metric config; extracts every
checkable claim; recomputes each one with plain SQL (DuckDB) — zero AI in the
verification step — and returns PASS / FAIL / UNVERIFIABLE per claim with the
executed query and row counts as proof.

> Status: Stage 6, part A (benchmark-driven fixes replayed; see the table below and `docs/benchmark.md` §6–7). CLI packaging follows in part B.

## What Recount does NOT do (honesty section — keep this current)
- It does not make the generator hallucinate less; it makes hallucinated numbers detectable.
- The extraction step is an LLM; only the *verification* step is deterministic.
- It verifies against the config's definition of a metric; a wrong config yields confidently wrong verdicts.
- Dataset contents never enter a prompt on the verification path. The one exception is the
  benchmark's LLM-as-judge baseline, which is handed a deterministic aggregate summary of the
  public example data so the head-to-head is fair; its output never touches a verdict.

## Prior art (credited, not competed with)
VeriFin (arXiv 2608.10213) · Deterministic Integrity Gates (arXiv 2606.09500) ·
Thucy (arXiv 2512.03278) · Evergreen (arXiv 2604.26180) · Proof-Carrying Numbers (arXiv 2509.06902) ·
FinGround (arXiv 2604.23588). Each solves a constrained slice; Recount is the general,
dataset-agnostic, developer-tooling assembly.

## Benchmark
<!-- BENCH:START -->
Recount 0.0.1 · 121 artifacts (96 distinct) · seeds 1, 2, 3, 4, 5 · extractor and judge: `gemini-3.1-flash-lite` · suite `fcd63c6c9739` · methodology and per-class analysis in [docs/benchmark.md](docs/benchmark.md).

| class | n | claims | detection | by abstention | false accept | coverage | abstention | sweep flagged | collateral flags | judge detection | judge false accept | judge localized |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| wrong_figure | 20 | 15 | 18/20 (90%) | 0/20 (0%) | 0/20 (0%) | 18/20 (90%) | 22% | 2 | 0 | 20/20 (100%) | 0/20 (0%) | 14/20 (70%) |
| flipped_direction | 20 | 5 | 16/20 (80%) | 0/20 (0%) | 0/20 (0%) | 20/20 (100%) | 22% | 0 | 0 | 20/20 (100%) | 0/20 (0%) | 13/20 (65%) |
| wrong_ranking | 15 | 2 | 0/15 (0%) | 0/15 (0%) | 0/15 (0%) | 15/15 (100%) | 21% | 0 | 0 | 15/15 (100%) | 0/15 (0%) | 15/15 (100%) |
| swapped_entity | 20 | 14 | 20/20 (100%) | 0/20 (0%) | 0/20 (0%) | 20/20 (100%) | 22% | 0 | 0 | 20/20 (100%) | 0/20 (0%) | 10/20 (50%) |
| fabricated_metric | 20 | 17 | 0/20 (0%) | 19/20 (95%) | 0/20 (0%) | 19/20 (95%) | 23% | 1 | 0 | 20/20 (100%) | 0/20 (0%) | 13/20 (65%) |
| rounding_drift | 20 | 17 | 20/20 (100%) | 0/20 (0%) | 0/20 (0%) | 20/20 (100%) | 22% | 0 | 0 | 20/20 (100%) | 0/20 (0%) | 7/20 (35%) |
| instruction_in_data | 5 | 5 | 5/5 (100%) | 0/5 (0%) | 0/5 (0%) | 5/5 (100%) | 22% | 0 | 0 | 5/5 (100%) | 0/5 (0%) | 5/5 (100%) |
| **exact-match classes** | 100 | 37 | 79/100 (79%) | 0/100 (0%) | 0/100 (0%) | 98/100 (98%) | 22% | 2 | 0 | 100/100 (100%) | 0/100 (0%) | 64/100 (64%) |
| **overall** | 120 | 42 | 79/120 (66%) | 19/120 (16%) | 0/120 (0%) | 117/120 (98%) | 22% | 3 | 0 | 120/120 (100%) | 0/120 (0%) | 77/120 (64%) |

Clean report: 51 claims, 40 PASS / 0 FAIL / 11 UNVERIFIABLE (false-flag rate 0%); label recall 0.8947, precision 1.0000; unextracted numerics: 27 states, 12.55 days, 11.41 days, 17,280 orders, 14.28 days; judge: unfaithful, 1 false flags.
instruction_in_data: Recount verdicts identical to the sibling variant in 5/5 (invariant by construction); judge detections suppressed by the injected cell: 0/5.

| latency | p50 | p95 | n | source |
|---|---|---|---|---|
| extraction s | 16.9285 s | 22.0678 s | 96 | recordings of the live run |
| judge s | 2.164 s | 3.699 s | 101 | recordings of the live run |
| verification ms per claim | 1.1863 ms | 2.6501 ms | 6228 | live run |
<!-- BENCH:END -->
F-3 opt-in, measured separately with `tests/fixtures/olist_metrics.alias-on.yml` (the two `overall` aliases uncommented; `bench/results/latest.alias-on.json`): wrong_ranking detection 5/15, 10/15 abstained `metric_echo_failed`, 0 false accepts; everything else identical. The default stays alias-off. Both rows and the reasoning are in [docs/benchmark.md](docs/benchmark.md) §7.

## License
Apache-2.0 (code). Example data: see `examples/olist/ATTRIBUTION.md`.
