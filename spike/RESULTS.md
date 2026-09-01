# Spike results

## G0 — landscape check (done 2026-09-01)
Three searches, primary sources: no new general-purpose OSS library re-derives numeric claims from
free-text reports against arbitrary datasets. Closest movements since the August report:
- FinGround (finance/SEC) states production integration as an internal REST service targeting Q3 2026 — proprietary, finance-only, not OSS.
- Evergreen's repo (brown-db/evergreen) is experiment code that requires a Snowflake account and Yelp data — a research artifact, not an installable library.
- VeriFin remains finance/XBRL-only; its explicit "coverage cost" finding (rejecting 37–73 correct claims per model) is a useful comparison point for our abstention rate.
**Gate G0: PASS.** Proceed to the spike.

## Data
- source: <fill> · rows sampled: <fill> · period: <fill>

## Report
- generator model: <fill> · claims in report (hand count): <fill>

## Extraction
- claims extracted: <fill> · matched hand labels: <fill> · missed: <fill> · invented/misbound: <fill>
- coverage = matched / hand-count = <fill>

## Compile + verify (point_value + growth only)
- compiled: <fill> · abstained: <fill> (reasons: <fill>)
- verdicts vs my hand-computed truth — correct: <fill> · false accepts: <fill> · false flags: <fill>
- compile-and-verify rate on numeric claims = <fill>

## Dilemmas encountered while labeling
- 

## G1 decision
- rate <fill>% → [ ] PROCEED (≥60)   [ ] ENRICH CONFIG & RERUN (30–60)   [ ] NARROW V1 (<30)
- what the spike changed about the claim schema / config format:
