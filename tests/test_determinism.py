"""Byte-identical determinism on the full pipeline (docs/design.md, wall 3 and the
benchmark's C4 rule): the same artifact, dataset and config produce the same run record,
the same HTML and the same Markdown, in one process, across two processes, and under a
shuffled row order. The only field allowed to differ is the wall-clock timings."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb
from hypothesis import given, settings
from hypothesis import strategies as st

from recount.claims import ClaimAdapter
from recount.config import Entity, Metric, SemanticConfig
from recount.io import attach
from recount.pipeline import verify_text
from recount.report import render_html, render_markdown, run_record
from recount.verify import verify_claim

DATA = Path("examples/olist/orders.parquet")
CONFIG = Path("examples/olist/metrics.yml")
REPORT = Path("spike/report_clean.md")  # = examples/olist/report.md on main
RECORDINGS = Path("bench/recordings/extract")
_TIMINGS = re.compile(r'"timings_s": \{[^}]*\}')


def _strip_timings(text: str) -> str:
    return _TIMINGS.sub('"timings_s": {}', text)


def test_same_inputs_same_record_html_and_markdown_in_process() -> None:
    runs = [
        verify_text(REPORT.read_text(), data=DATA, config=CONFIG, recordings=RECORDINGS,
                    artifact_path=str(REPORT))
        for _ in range(2)
    ]  # fmt: skip
    records = [run_record(r) for r in runs]
    for rec in records:
        assert set(rec.pop("timings_s")) == {"load", "extract", "verify"}
    assert records[0] == records[1]
    assert render_html(runs[0], records[0]) == render_html(runs[1], records[1])
    assert render_markdown(runs[0]) == render_markdown(runs[1])


def test_two_processes_agree_byte_for_byte_except_timings(tmp_path: Path) -> None:
    outs = []
    for i in range(2):
        d = tmp_path / str(i)
        d.mkdir()
        cmd = [sys.executable, "-m", "recount.cli", "verify", str(REPORT), "--data", str(DATA),
               "--config", str(CONFIG), "--recordings", str(RECORDINGS), "--json",
               str(d / "v.json"), "--html", str(d / "r.html"), "--md", str(d / "t.md"),
               "--quiet"]  # fmt: skip
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        assert p.returncode == 0, p.stdout + p.stderr
        outs.append(d)
    a, b = outs
    assert (a / "r.html").read_bytes() == (b / "r.html").read_bytes()
    assert (a / "t.md").read_bytes() == (b / "t.md").read_bytes()
    ja, jb = (a / "v.json").read_text(), (b / "v.json").read_text()
    assert _strip_timings(ja) == _strip_timings(jb)
    # and nothing else in the record is time-, path- or process-dependent
    ra, rb = json.loads(ja), json.loads(jb)
    assert {k for k in ra if ra[k] != rb[k]} <= {"timings_s"}


# ------------------------------------------------- property: row order and repeated runs

CFG = SemanticConfig(
    time_column="d",
    entities={"state": Entity(column="state")},
    metrics={
        "revenue": Metric(agg="sum", column="revenue", round=2, polarity="higher_is_better"),
        "orders": Metric(agg="count", polarity="higher_is_better"),
        "avg_days": Metric(agg="avg", column="days", polarity="lower_is_better"),
    },
)
CON = duckdb.connect()
CON.execute("CREATE TABLE data (d DATE, state VARCHAR, revenue DOUBLE, days BIGINT)")

row = st.tuples(
    st.dates(min_value=date(2017, 1, 1), max_value=date(2017, 12, 31)),
    st.sampled_from(["SP", "RJ", "MG"]),
    st.floats(min_value=0.01, max_value=10_000, allow_nan=False).map(lambda x: round(x, 2)),
    st.one_of(st.none(), st.integers(min_value=0, max_value=60)),
)
rows = st.lists(row, min_size=1, max_size=40)


def _claim(kind: str, metric: str, subject: str | None, value: float):  # type: ignore[no-untyped-def]
    base = {"id": "p", "span": f"{metric} was {value}", "confidence": "high", "metric": metric,
            "subject": subject, "period": "2017-Q3", "value": value}  # fmt: skip
    if kind == "point_value":
        return ClaimAdapter.validate_python({**base, "type": "point_value"})
    if kind == "growth":
        return ClaimAdapter.validate_python(
            {**base, "type": "growth", "direction": "increase", "baseline_period": "2017-Q2"}
        )
    del base["value"]
    return ClaimAdapter.validate_python(
        {**base, "type": "ranking", "span": f"{subject} led all states in {metric}",
         "rank": 1, "group_by": "state", "period": "2017"}
    )  # fmt: skip


def _verdicts(data, claims):  # type: ignore[no-untyped-def]
    CON.execute("DELETE FROM data")
    CON.executemany("INSERT INTO data VALUES (?, ?, ?, ?)", data)
    ds = attach(CON, CFG)
    return [verify_claim(ds, c, CFG).model_dump(mode="json") for c in claims]


@settings(max_examples=300, deadline=None)
@given(
    data=rows,
    permutation=st.randoms(use_true_random=False),
    metric=st.sampled_from(["revenue", "orders", "avg_days"]),
    subject=st.sampled_from([None, "SP", "RJ"]),
    value=st.floats(min_value=0, max_value=20_000, allow_nan=False).map(lambda x: round(x, 2)),
)
def test_verdicts_are_invariant_under_row_order_and_repetition(  # type: ignore[no-untyped-def]
    data, permutation, metric, subject, value
) -> None:
    claims = [
        _claim("point_value", metric, subject, value),
        _claim("growth", metric, subject, value),
        _claim("ranking", metric, subject or "SP", value),
    ]
    first = _verdicts(data, claims)
    again = _verdicts(data, claims)
    shuffled = list(data)
    permutation.shuffle(shuffled)
    reordered = _verdicts(shuffled, claims)
    assert first == again == reordered
