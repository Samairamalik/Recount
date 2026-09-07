"""HTML reporter: spans cut by verdict, the YAML stubs, display-substituted SQL,
determinism."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from recount.pipeline import verify_text
from recount.report import render_html, run_record
from recount.report.html import segments, yaml_stub
from recount.report.json_out import RunRecord

DATA = Path("examples/olist/orders.parquet")
CONFIG = Path("examples/olist/metrics.yml")
REPORT = Path("examples/olist/report.md")
RECORDINGS = Path("bench/recordings/extract")


def _record() -> tuple[RunRecord, dict[str, Any]]:
    rec = verify_text(REPORT.read_text(), data=DATA, config=CONFIG, recordings=RECORDINGS,
                      artifact_path=str(REPORT))  # fmt: skip
    return rec, run_record(rec)


def test_segments_cover_the_artifact_exactly_once() -> None:
    rec, _ = _record()
    segs = segments(rec)
    assert "".join(s.text for s in segs) == REPORT.read_text()
    kinds = {s.kind for s in segs}
    assert kinds >= {"text", "PASS", "UNVERIFIABLE", "unextracted"}
    # 5 unextracted tokens; "17,280 orders" sits inside the merged growth claim's span, so it
    # is listed in the drawer rather than marked (marks do not nest)
    assert sum(s.kind == "unextracted" for s in segs) == 4


def test_yaml_stubs_follow_the_abstention_detail() -> None:
    rec, _ = _record()
    pairs = list(zip(rec.claims, rec.verdicts, strict=True))
    stubs = {c.id: yaml_stub(c, v) for c, v in pairs}
    by_detail = {v.detail.split(":")[0].split(" '")[0]: c.id for c, v in pairs}
    unknown = stubs[by_detail["unknown metric"]]
    assert unknown is not None and unknown.startswith("metrics:\n  commercial_performance:")
    echo = stubs[by_detail["metric_echo_failed"]]
    assert echo is not None and "aliases: [..., <the span's wording for revenue>]" in echo
    # ambiguous abstentions have no config fix
    assert stubs[by_detail["no stated growth magnitude"]] is None


def test_render_is_deterministic_and_self_contained(tmp_path: Path) -> None:
    rec, record = _record()
    a = render_html(rec, record)
    b = render_html(rec, record)
    assert a == b
    assert "<script src=" not in a and "<link " not in a  # no external assets
    assert "parameters substituted for display" in a and "$start" in a
    assert record["artifact_sha256"][:12] in a
