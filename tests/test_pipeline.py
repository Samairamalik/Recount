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
    assert Counter(v.verdict for v in result.verdicts) == {"PASS": 58, "UNVERIFIABLE": 8}
    assert {v.abstain_reason.value for v in result.verdicts if v.abstain_reason} == {
        "ambiguous",
        "unsupported_claim_type",
    }
    # the one number no claim covers: "Across all 27 states" (fixture c1, a schema gap anyway)
    assert [t.context for t in ex.unextracted_numeric] == ["27 states"]
