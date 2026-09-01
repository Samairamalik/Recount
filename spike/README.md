# Stage 0 — validation spike (throwaway)

**Question this spike answers:** on one real report over one real dataset, what fraction of
claims can be extracted → compiled → verified with a config written in under 30 minutes,
and what falls into UNVERIFIABLE? (Risk R1 — the only assumption that can kill the project.)

**Gate G1:** ≥60% of numeric claims compile-and-verify → proceed to Stage 1.
30–60% → one evening enriching the config format, re-run once. <30% → narrow V1 claim types.

## Steps (6–8 hours over one weekend)
1. `RESULTS.md` — G0 landscape findings are pre-filled. Read them.
2. Get data: download the Olist dataset from Kaggle (CC BY-NC-SA) into `spike/data/` (gitignored),
   then `uv run python spike/sample_olist.py` → `spike/data/orders.parquet` (~50k rows, one year).
3. Generate the report: ask any LLM to write a ~15-claim quarterly business report about the
   sample (give it the schema + a few aggregate numbers you compute yourself). Save as `spike/report.md`.
4. **Hand-label every claim** into `spike/labels.json` using `LABELING_GUIDE.md` and the template.
   Compute each claim's TRUE value yourself (DuckDB CLI or a notebook). This is the most important
   two hours of the project — it designs the claim schema and becomes permanent ground truth.
5. Write `spike/metrics.yml` (30-minute budget): metric → column/aggregation, entity aliases, time column.
6. With Claude Code: `spike/spike.py` — extraction call via the Gemini API with `response_schema`
   structured output (`google-genai` SDK, key in `GEMINI_API_KEY`; use `extraction_prompt.draft.md`) →
   crude compile for `point_value` and `growth` only → direct DuckDB queries → printed verdict
   table with abstain reasons. No tests, no packaging, no polish.
7. Fill in `RESULTS.md`: coverage %, compile rate, abstain rate + reasons, false accepts vs your labels.
   Decide per G1. Commit the whole `spike/` folder. Never extend it — Stage 1 starts clean.
