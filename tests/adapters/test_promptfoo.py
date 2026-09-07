"""promptfoo `recount-verify`: the GradingResult mapping, keyless through a recording."""

from __future__ import annotations

from pathlib import Path

from recount.adapters.promptfoo import get_assert

DATA = Path("examples/olist/orders.parquet")
CONFIG = Path("examples/olist/metrics.yml")
REPORT = Path("spike/report_clean.md")  # = examples/olist/report.md on main
RECORDINGS = Path("bench/recordings/extract")


def _ctx(**extra: object) -> dict[str, object]:
    return {"vars": {"recount_data": str(DATA), "recount_config": str(CONFIG), **extra}}


def test_clean_report_passes_with_counts() -> None:
    rec = Path("bench/recordings/extract/a480cd830cd6f482.json")
    result = get_assert(REPORT.read_text(), _ctx(recount_recording=str(rec)))
    assert result["pass"] is True and result["score"] == 1.0
    assert result["reason"].startswith("40 PASS · 0 FAIL · 11 UNVERIFIABLE")
    assert result["namedScores"]["recount_fail"] == 0.0


def test_corrupted_report_fails_and_names_the_claim(corrupted_report: Path) -> None:
    result = get_assert(
        corrupted_report.read_text(),
        _ctx(recount_recording="bench/recordings/extract/0969239d1badef70.json"),
    )
    assert result["pass"] is False
    assert "FAIL c29" in result["reason"] and "4,228,002.62" in result["reason"]
    assert 0 < result["score"] < 1


def test_strict_flips_an_abstaining_report() -> None:
    rec = "bench/recordings/extract/a480cd830cd6f482.json"
    assert (
        get_assert(REPORT.read_text(), _ctx(recount_recording=rec, recount_strict=True))["pass"]
        is False
    )


def test_missing_vars_or_system_errors_never_pass() -> None:
    assert get_assert("x", {"vars": {}})["pass"] is False
    r = get_assert("x", _ctx(recount_recording="nope.json"))
    assert r["pass"] is False and "recount-verify:" in r["reason"]
