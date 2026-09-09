"""End-to-end smoke: raw clean report -> extract (recorded) -> compile -> verify."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from recount.config import load_config
from recount.extract import MockClient
from recount.io import load_dataset
from recount.pipeline import run

CFG = load_config(Path("tests/fixtures/olist_metrics.yml"))
DS = load_dataset(Path("examples/olist/orders.parquet"), CFG)
CLEAN = Path("spike/report_clean.md")


def test_clean_report_end_to_end_has_no_fail_and_no_rejection() -> None:
    result = run(
        CLEAN.read_text(), CFG, DS, MockClient(Path("tests/fixtures/extract/report_clean.json"))
    )
    ex = result.extraction
    assert ex.rejected == ()
    assert [v.claim_id for v in result.verdicts] == [c.id for c in ex.claims]
    # Stage 4 recording: 66 claims, 58 PASS / 8 UNVERIFIABLE. Re-recorded in Stage 5 after
    # the wire schema made every key required (docs/benchmark.md §6, changelog 1): 61 claims,
    # 56 PASS / 5 UNVERIFIABLE. Stage 6 (changelog 5, abstention M3): the same recording
    # gives 41 PASS / 20 UNVERIFIABLE, 15 of them metric_echo_failed; changelog 7's alias
    # "days for delivery" returned two: 61 claims, 43 / 18, 13 metric_echo_failed.
    # Re-recorded again in Stage 8 (changelog 10), because `rank_from` changed the prompt
    # and the wire schema: 55 claims, 42 / 13, 8 metric_echo_failed. Recall is unchanged
    # (docs/eval.md, Stage 8 addendum) — the model simply extracted a different number of
    # claims from the same text, which is F-4 in one line.
    assert len(ex.claims) == 55
    assert Counter(v.verdict for v in result.verdicts) == {"PASS": 42, "UNVERIFIABLE": 13}
    assert {v.abstain_reason.value for v in result.verdicts if v.abstain_reason} == {
        "ambiguous",
        "unsupported_claim_type",
        "schema_gap",
    }
    assert sum(v.detail.startswith("metric_echo_failed") for v in result.verdicts) == 8
    # numbers no claim verifies: "Across all 27 states" (fixture c1, a schema gap anyway),
    # and two the sweep flags because the claim covering their sentence binds another value
    tokens = [t.context for t in ex.unextracted_numeric]
    assert tokens == ["27 states", "11.41 days", "17,280 orders"]
