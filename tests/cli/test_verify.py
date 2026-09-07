"""`recount verify`: the exit-code contract (FR-009), the offline paths (--claims,
--recording, --recordings), every exit-2 sentence, and the three output files."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from recount.cli import app

DATA = Path("examples/olist/orders.parquet")
CONFIG = Path("examples/olist/metrics.yml")
REPORT = Path("spike/report_clean.md")  # = examples/olist/report.md on main
RECORDINGS = Path("bench/recordings/extract")
runner = CliRunner()
BASE = ["verify", str(REPORT), "--data", str(DATA), "--config", str(CONFIG)]


def test_clean_report_exits_0_and_strict_exits_1(tmp_path: Path) -> None:
    out = tmp_path / "v.json"
    r = runner.invoke(app, [*BASE, "--recordings", str(RECORDINGS), "--json", str(out), "--quiet"])
    assert r.exit_code == 0, r.output
    record = json.loads(out.read_text())
    assert record["summary"] == {
        "PASS": 40, "FAIL": 0, "UNVERIFIABLE": 11, "rejected": 4, "unextracted_numeric": 5
    }  # fmt: skip
    assert record["exit_code"] == 0 and record["extractor_model"] == "gemini-3.1-flash-lite"
    assert len(record["artifact_sha256"]) == 64 and len(record["dataset_sha256"]) == 64
    assert set(record["timings_s"]) == {"load", "extract", "verify"}
    # strict: the 11 abstentions and 5 unextracted numerics become a failure
    r = runner.invoke(app, [*BASE, "--recordings", str(RECORDINGS), "--strict", "--quiet"])
    assert r.exit_code == 1


def test_corrupted_report_exits_1_with_an_annotation(
    corrupted_report: Path, tmp_path: Path
) -> None:
    md = tmp_path / "s.md"
    r = runner.invoke(
        app,
        ["verify", str(corrupted_report), "--data", str(DATA), "--config", str(CONFIG),
         "--recordings", str(RECORDINGS), "--md", str(md), "--annotations", "--quiet"],
    )  # fmt: skip
    assert r.exit_code == 1, r.output
    assert "::error file=" in r.output and "generating 4,228,002.62 in revenue" in r.output
    assert "title=Recount FAIL" in r.output
    table = md.read_text()
    assert "❌ FAIL" in table and "1 FAIL" in table and "exit code 1" in table


def test_claims_file_is_fully_offline(tmp_path: Path) -> None:
    claims = tmp_path / "claims.json"
    claims.write_text(json.dumps([
        {"id": "c1", "type": "point_value", "span": "processed 43,428 orders", "metric": "orders",
         "value": 43428, "period": "2017", "confidence": "high", "subject": None, "unit": "count"},
        {"id": "c2", "type": "point_value", "span": "not in the report", "metric": "orders",
         "value": 1, "period": "2017", "confidence": "high", "subject": None, "unit": None},
    ]))  # fmt: skip
    out = tmp_path / "v.json"
    r = runner.invoke(app, [*BASE, "--claims", str(claims), "--json", str(out), "--quiet"])
    assert r.exit_code == 0, r.output
    record = json.loads(out.read_text())
    assert record["extractor_model"] == "claims-file"
    assert [v["verdict"] for v in record["verdicts"]] == ["PASS"]
    assert [x["reason"] for x in record["rejected"]] == ["span_not_verbatim"]  # same post-checks


def test_missing_recording_is_exit_2_not_a_pass(tmp_path: Path) -> None:
    r = runner.invoke(app, [*BASE, "--recordings", str(tmp_path), "--quiet"])
    assert r.exit_code == 2 and "no recording for this artifact" in r.output


def test_dataset_and_config_errors_exit_2(tmp_path: Path) -> None:
    r = runner.invoke(app, ["verify", str(REPORT), "--data", "nope.parquet", "--config",
                            str(CONFIG), "--quiet"])  # fmt: skip
    assert r.exit_code == 2 and "dataset not found" in r.output
    bad = tmp_path / "bad.yml"
    bad.write_text("time_column: order_date\nentities: {}\nmetrics:\n  revenue:\n    agg: sum\n")
    r = runner.invoke(app, ["verify", str(REPORT), "--data", str(DATA), "--config", str(bad),
                            "--quiet"])  # fmt: skip
    assert r.exit_code == 2 and "line 4" in r.output and "needs a column" in r.output
    bad.write_text("time_column: [\n")
    r = runner.invoke(app, ["verify", str(REPORT), "--data", str(DATA), "--config", str(bad),
                            "--quiet"])  # fmt: skip
    assert r.exit_code == 2 and "not valid YAML at line 2" in r.output
    mismatch = tmp_path / "mismatch.yml"
    mismatch.write_text("time_column: nope\nentities: {}\nmetrics:\n  orders:\n    agg: count\n")
    r = runner.invoke(app, ["verify", str(REPORT), "--data", str(DATA), "--config",
                            str(mismatch), "--quiet"])  # fmt: skip
    assert r.exit_code == 2 and "does not match config" in r.output


def test_html_report_is_written(tmp_path: Path) -> None:
    html = tmp_path / "r.html"
    r = runner.invoke(app, [*BASE, "--recordings", str(RECORDINGS), "--html", str(html), "--quiet"])
    assert r.exit_code == 0
    text = html.read_text()
    assert text.startswith("<!doctype html>") and 'mark class="PASS"' in text
    assert "processed 43,428 orders" in text and "40 PASS" in text
