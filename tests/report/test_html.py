"""HTML reporter: spans cut by verdict, the YAML stubs, display-substituted SQL,
determinism."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from recount.pipeline import verify_text
from recount.report import render_html, run_record
from recount.report.html import _QUOTED, segments, unpainted, yaml_stub
from recount.report.json_out import RunRecord

DATA = Path("examples/olist/orders.parquet")
CONFIG = Path("examples/olist/metrics.yml")
REPORT = Path("spike/report_clean.md")  # = examples/olist/report.md on main
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
    # All five sweep tokens are marked in this recording. A token that falls inside an
    # accepted claim's span is listed in the drawer instead: claim marks outrank tokens
    # (segments()), which is what keeps a grey mark from appearing inside a green one.
    assert sum(s.kind == "unextracted" for s in segs) == 5
    assert unpainted(rec, segs) == []  # every verdict in the header is on the page


def test_f6_a_nested_span_is_painted_and_the_header_reconciles(tmp_path: Path) -> None:
    """Acceptance F-6: `c15` "to hit 1,447,714.17" nests inside `c14`'s span in the shipped example,
    and the old segmentation dropped the inner one — 51 of 52 verdicts rendered while the
    header still said 52. The innermost claim now wins its own region, the outer keeps the
    rest, and any claim that is still not on screen is named in the header."""
    artifact = "Revenue rose to hit 1,447,714.17 in 2017.\n"
    claims = [
        {"id": "c14", "type": "growth", "span": "Revenue rose to hit 1,447,714.17",
         "confidence": "high", "metric": "revenue", "value": None, "direction": "increase",
         "period": "2017", "baseline_period": "2016"},
        {"id": "c15", "type": "point_value", "span": "to hit 1,447,714.17", "confidence": "high",
         "metric": "revenue", "value": 1447714.17, "period": "2017"},
    ]  # fmt: skip
    art, cl = tmp_path / "r.md", tmp_path / "claims.json"
    art.write_text(artifact)
    cl.write_text(json.dumps(claims))
    rec = verify_text(artifact, data=DATA, config=CONFIG, claims=cl, artifact_path=str(art))
    segs = segments(rec)
    assert "".join(s.text for s in segs) == artifact  # still covers the text exactly once
    assert [s.claim_id for s in segs if s.claim_id] == ["c14", "c15"]  # both painted
    assert [s.text for s in segs if s.claim_id] == ["Revenue rose ", "to hit 1,447,714.17"]
    assert unpainted(rec, segs) == []
    verdicts = sum(rec.counts[k] for k in ("PASS", "FAIL", "UNVERIFIABLE"))
    assert len(rec.claims) == 2 and verdicts == 2  # the header's total is on screen


def test_a_claim_no_mark_can_show_is_named_in_the_header(tmp_path: Path) -> None:
    """The other half of acceptance F-6's rule: when a claim genuinely cannot be painted, the header
    says which, so the counts are never larger than what the reader can find."""
    artifact = "Revenue was 1,447,714.17 in 2017.\n"
    claims = [
        {"id": "c1", "type": "point_value", "span": "Revenue was 1,447,714.17",
         "confidence": "high", "metric": "revenue", "value": 1447714.17, "period": "2017"},
    ]  # fmt: skip
    art, cl = tmp_path / "r.md", tmp_path / "claims.json"
    art.write_text(artifact)
    cl.write_text(json.dumps(claims))
    rec = verify_text(artifact, data=DATA, config=CONFIG, claims=cl, artifact_path=str(art))
    segs = segments(rec)
    assert unpainted(rec, segs) == []
    ghost = rec.claims[0].model_copy(update={"span": "a span the artifact does not contain"})
    rec = replace(rec, claims=(ghost,))
    assert unpainted(rec, segments(rec)) == ["c1"]
    assert "not marked below: c1" in render_html(rec, run_record(rec))


def test_yaml_stubs_follow_the_abstention_detail() -> None:
    rec, _ = _record()
    pairs = list(zip(rec.claims, rec.verdicts, strict=True))
    stubs = {c.id: yaml_stub(c, v) for c, v in pairs}
    by_detail = {v.detail.split(":")[0].split(" '")[0]: c.id for c, v in pairs}
    unknown = stubs[by_detail["unknown metric"]]
    assert unknown is not None and unknown.startswith("metrics:\n  commercial_performance:")
    # Every echo abstention gets a stub naming the metric it bound, whichever claims the
    # recording happens to produce: the stub follows the detail, not a pinned claim id.
    echoes = [(c, stubs[c.id]) for c, v in pairs if v.detail.startswith("metric_echo_failed")]
    assert echoes
    for claim, stub in echoes:
        assert stub is not None
        name = _QUOTED.findall(next(v.detail for c, v in pairs if c.id == claim.id))[0]
        assert f"metrics:\n  {name}:\n    aliases: [..., <the span's wording for {name}>]" in stub
    # ambiguous abstentions have no config fix
    assert stubs[by_detail["no stated growth magnitude"]] is None


def test_render_is_deterministic_and_self_contained(tmp_path: Path) -> None:
    rec, record = _record()
    a = render_html(rec, record)
    b = render_html(rec, record)
    assert a == b
    assert "<script src=" not in a and "<link " not in a  # no external assets
    assert "parameters substituted for display" in a and "$start" in a
    # the JSON payload is raw (the JS escapes on render), so SQL operators survive once
    assert '\\"order_date\\" >= $start' in a and "&gt;=" not in a
    assert record["artifact_sha256"][:12] in a
