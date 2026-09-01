# Recount

**Deterministic verification of numeric claims in LLM-generated reports.**

LLMs writing about data confidently state wrong numbers. Recount takes a report,
the source dataset (CSV/Parquet), and a small metric config; extracts every
checkable claim; recomputes each one with plain SQL (DuckDB) — zero AI in the
verification step — and returns PASS / FAIL / UNVERIFIABLE per claim with the
executed query and row counts as proof.

> Status: Stage 0 (validation spike). Not yet usable. See `spike/README.md`.

## What Recount does NOT do (honesty section — keep this current)
- It does not make the generator hallucinate less; it makes hallucinated numbers detectable.
- The extraction step is an LLM; only the *verification* step is deterministic.
- It verifies against the config's definition of a metric; a wrong config yields confidently wrong verdicts.

## Prior art (credited, not competed with)
VeriFin (arXiv 2608.10213) · Deterministic Integrity Gates (arXiv 2606.09500) ·
Thucy (arXiv 2512.03278) · Evergreen (arXiv 2604.26180) · Proof-Carrying Numbers (arXiv 2509.06902) ·
FinGround (arXiv 2604.23588). Each solves a constrained slice; Recount is the general,
dataset-agnostic, developer-tooling assembly.

## Benchmark
<!-- BENCH:START -->
_Not yet measured._
<!-- BENCH:END -->

## License
Apache-2.0 (code). Example data: see `examples/olist/ATTRIBUTION.md`.
