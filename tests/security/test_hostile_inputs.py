"""Hostile inputs (docs/design.md threats T3, T4, T7): SQL-injection-shaped names through
the whole compile -> verify path, hostile column names inside the dataset itself, a config
that tries to smuggle code, and oversized inputs hitting every cap with a clean exit 2.

The property under test is the same everywhere: nothing shaped like data is ever rendered
into SQL text. Entity values and dates are bound parameters; column names are quoted
identifiers the loader has already validated against the real schema; claim text never
reaches the engine except through a schema-validated Claim, and then only as a value."""

from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from recount.claims import AbstainReason, ClaimAdapter
from recount.cli import app
from recount.config import Entity, Metric, SemanticConfig, load_config
from recount.io import load_dataset
from recount.verify import verify_claim

DATA = Path("examples/olist/orders.parquet")
CONFIG = Path("examples/olist/metrics.yml")
REPORT = Path("spike/report_clean.md")
OLIST = load_config(Path("tests/fixtures/olist_metrics.yml"))
DS = load_dataset(DATA, OLIST)
runner = CliRunner()

HOSTILE = (
    "SP'; DROP TABLE data; --",
    'SP" OR 1=1 --',
    "x' UNION SELECT 1,2,3 --",
    "$entity OR 1=1 --",  # looks like a bound-parameter placeholder
    "{t}",  # looks like a template slot
    'state") = 1 OR ("state',
    "Robert'); DELETE FROM data; --",
    "'; ATTACH ':memory:' AS m; --",
    "🙂 ' OR '1'='1",
    "SP' /* */ --",
)
INTACT = "SELECT COUNT(*) FROM data"


def _n_rows() -> int:
    row = DS.con.execute(INTACT).fetchone()
    assert row is not None
    return int(row[0])


def _pv(metric: str, subject: str | None, value: float, span: str, period: str = "2017"):  # type: ignore[no-untyped-def]
    return ClaimAdapter.validate_python(
        {"id": "h", "type": "point_value", "span": span, "confidence": "high", "metric": metric,
         "subject": subject, "period": period, "value": value}
    )  # fmt: skip


# ------------------------------------------------------------ T4: names through the compiler


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_entity_alias_resolves_to_a_bound_value_never_sql(name: str) -> None:
    cfg = OLIST.model_copy(
        update={"entities": {"state": Entity(column="state", aliases={name: "SP"})}}
    )
    v = verify_claim(DS, _pv("orders", name, 17071, "with 17,071 orders"), cfg)
    assert v.verdict == "PASS", v.detail
    assert v.params["entity"] == "SP"
    assert name not in v.sql and "DROP" not in v.sql and "1=1" not in v.sql
    assert _n_rows() == 43428


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_stored_value_is_bound_and_yields_a_verdict_not_an_error(name: str) -> None:
    """The alias maps to a stored value that looks like SQL. It is bound as a parameter,
    matches no row, and the count is honestly 0: a FAIL, never an injection."""
    cfg = OLIST.model_copy(
        update={"entities": {"state": Entity(column="state", aliases={"Nowhere": name})}}
    )
    v = verify_claim(DS, _pv("orders", "Nowhere", 5, "logged 5 orders"), cfg)
    assert v.verdict == "FAIL" and v.computed_value == 0
    assert v.params["entity"] == name and name not in v.sql
    assert _n_rows() == 43428


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_metric_alias_never_reaches_sql(name: str) -> None:
    cfg = OLIST.model_copy(
        update={"metrics": {**OLIST.metrics, "orders": Metric(agg="count", aliases=[name])}}
    )
    v = verify_claim(DS, _pv(name, None, 43428, f"{name} reached 43,428"), cfg)
    assert v.verdict == "PASS", v.detail  # the echo gate matched the alias as a whole word
    assert name not in v.sql and "DROP" not in v.sql
    assert _n_rows() == 43428


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_claim_fields_abstain_or_bind_but_never_render(name: str) -> None:
    unknown_subject = verify_claim(DS, _pv("orders", name, 1, "1 order"), OLIST)
    assert unknown_subject.abstain_reason == AbstainReason.SCHEMA_GAP
    assert unknown_subject.sql == ""
    bad_period = verify_claim(DS, _pv("orders", None, 1, "1 order", period=name), OLIST)
    assert bad_period.abstain_reason == AbstainReason.AMBIGUOUS and bad_period.sql == ""
    unknown_metric = verify_claim(DS, _pv(name, None, 1, "1 order"), OLIST)
    assert unknown_metric.abstain_reason == AbstainReason.SCHEMA_GAP and unknown_metric.sql == ""
    assert _n_rows() == 43428


# ------------------------------------------------------ T4: names inside the dataset itself


def test_hostile_column_names_are_quoted_identifiers(tmp_path: Path) -> None:
    """The schema is the one place a *name* is rendered into SQL. Column names that contain
    quotes, spaces, semicolons and keywords are double-quoted with the quote doubled, so
    the templates still address the right column and nothing else runs."""
    time_col = 'order "date"'
    state_col = "state; DROP TABLE data; --"
    revenue_col = "rev enue"
    csv = tmp_path / "hostile.csv"
    cols = (time_col, state_col, revenue_col)
    header = ",".join(f'"{c.replace(chr(34), chr(34) * 2)}"' for c in cols)
    csv.write_text(
        header + "\n"
        + "2017-01-05,SP,10.50\n2017-02-01,SP,20.25\n2017-03-01,RJ,5.00\n2017-04-01,SP,1.25\n"
    )
    cfg = SemanticConfig(
        time_column=time_col,
        entities={"state": Entity(column=state_col, aliases={"Sao Paulo": "SP"})},
        metrics={"revenue": Metric(agg="sum", column=revenue_col, round=2)},
    )
    ds = load_dataset(csv, cfg)
    assert set(ds.columns) == {time_col, state_col, revenue_col}
    v = verify_claim(ds, _pv("revenue", "Sao Paulo", 32.0, "32.0 in revenue"), cfg)
    assert v.verdict == "PASS", v.detail
    assert '"order ""date"""' in v.sql and '"state; DROP TABLE data; --"' in v.sql
    assert '"rev enue"' in v.sql
    assert v.row_counts == {"n_rows": 3, "n_used": 3}
    row = ds.con.execute(INTACT).fetchone()
    assert row is not None and row[0] == 4


def test_hostile_cell_values_are_only_ever_compared(tmp_path: Path) -> None:
    """A cell that looks like SQL is a group key like any other: it forms its own group in
    a ranking and matches nothing in an entity filter. Its text never enters the query."""
    csv = tmp_path / "cells.csv"
    rows = ["day,state,revenue", "2017-01-01,SP,3", "2017-01-02,RJ,2"]
    rows += [f'2017-01-03,"{name.replace(chr(34), chr(34) * 2)}",1' for name in HOSTILE]
    csv.write_text("\n".join(rows) + "\n")
    cfg = SemanticConfig(
        time_column="day",
        entities={"state": Entity(column="state", aliases={"Sao Paulo": "SP"})},
        metrics={"revenue": Metric(agg="sum", column="revenue", polarity="higher_is_better")},
    )
    ds = load_dataset(csv, cfg)
    ranking = ClaimAdapter.validate_python(
        {"id": "r", "type": "ranking", "span": "Sao Paulo led all states in revenue",
         "confidence": "high", "metric": "revenue", "subject": "Sao Paulo", "period": "2017",
         "rank": 1, "rank_from": "best", "group_by": "state"}
    )  # fmt: skip
    v = verify_claim(ds, ranking, cfg)
    assert v.verdict == "PASS", v.detail
    assert v.row_counts == {"n_rows": 2 + len(HOSTILE), "n_groups": 2 + len(HOSTILE)}
    for name in HOSTILE:
        assert name not in v.sql
    assert ds.con.execute(INTACT).fetchone() == (2 + len(HOSTILE),)


# ----------------------------------------------------------- T3: code in config and claims


def test_config_with_a_python_tag_is_refused_as_invalid_yaml(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    cfg = tmp_path / "evil.yml"
    cfg.write_text(
        "time_column: order_date\nentities: {}\nmetrics:\n  orders:\n    agg: count\n"
        f"x: !!python/object/apply:pathlib.Path.touch [{json.dumps(str(marker))}]\n"
    )
    r = runner.invoke(app, ["verify", str(REPORT), "--data", str(DATA), "--config", str(cfg),
                            "--recordings", "bench/recordings/extract", "--quiet"])  # fmt: skip
    assert r.exit_code == 2 and "not valid YAML" in r.output
    assert not marker.exists()


def test_hostile_claims_file_reaches_a_verdict_and_leaves_the_table_intact(
    tmp_path: Path,
) -> None:
    """A claims file is the extractor's output; a hostile one can carry SQL in every string
    field and an extra `verdict` key. Spans that are verbatim get a real verdict (FAIL: the
    number is wrong); the extra key is a foreign field and that object is rejected."""
    lines = [f"Sales for {name} reached 99 orders in 2017." for name in HOSTILE]
    artifact = tmp_path / "hostile.md"
    artifact.write_text("# Hostile report\n\n" + "\n".join(lines) + "\n")
    claims = [
        {"id": f"c{i}", "type": "point_value", "span": f"Sales for {name} reached 99 orders",
         "metric": "orders", "subject": name, "period": "2017", "confidence": "high",
         "value": 99, "unit": None}
        for i, name in enumerate(HOSTILE, 1)
    ]  # fmt: skip
    claims.append({**claims[0], "id": "c99", "span": "Hostile report", "verdict": "PASS",
                   "value": 43428, "subject": None})  # fmt: skip
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(json.dumps(claims))
    out = tmp_path / "v.json"
    r = runner.invoke(app, ["verify", str(artifact), "--data", str(DATA), "--config",
                            str(CONFIG), "--claims", str(claims_file), "--json", str(out),
                            "--quiet"])  # fmt: skip
    assert r.exit_code == 0, r.output  # every hostile subject is unknown: schema_gap, no SQL
    record = json.loads(out.read_text())
    assert [x["reason"] for x in record["rejected"]] == ["foreign_field"]
    assert {v["verdict"] for v in record["verdicts"]} == {"UNVERIFIABLE"}
    assert all(v["sql"] == "" for v in record["verdicts"])
    assert _n_rows() == 43428


# ----------------------------------------------------------------------- T7: the caps


def _cli(*extra: str) -> tuple[int, str]:
    args = ["verify", str(REPORT), "--data", str(DATA), "--config", str(CONFIG),
            "--recordings", "bench/recordings/extract", "--quiet", *extra]  # fmt: skip
    r = runner.invoke(app, args)
    return r.exit_code, r.output


def test_dataset_caps_are_a_one_line_exit_2(monkeypatch: pytest.MonkeyPatch) -> None:
    from recount import pipeline

    monkeypatch.setattr(pipeline, "load_dataset", functools.partial(load_dataset, max_bytes=10))
    code, out = _cli()
    assert code == 2 and "cap is 10" in out and "Traceback" not in out
    monkeypatch.setattr(pipeline, "load_dataset", functools.partial(load_dataset, max_rows=100))
    code, out = _cli()
    assert code == 2 and "43428 rows; cap is 100" in out and "Traceback" not in out


def test_oversized_artifact_is_refused_before_any_extraction(tmp_path: Path) -> None:
    from recount.pipeline import MAX_ARTIFACT_BYTES

    big = tmp_path / "big.md"
    big.write_text("Revenue was 1,234.50 in 2017. " * (MAX_ARTIFACT_BYTES // 30 + 1))
    out = tmp_path / "v.json"
    args = ["verify", str(big), "--data", str(DATA), "--config", str(CONFIG),
            "--recordings", str(tmp_path), "--json", str(out), "--quiet"]  # fmt: skip
    r = runner.invoke(app, args)
    assert r.exit_code == 2 and "cap is 1048576" in r.output and "Traceback" not in r.output
    assert not out.exists()  # no recording was looked up, no verdict was written
    empty = tmp_path / "empty.md"
    empty.write_text("  \n")
    r = runner.invoke(app, ["verify", str(empty), "--data", str(DATA), "--config", str(CONFIG),
                            "--claims", str(tmp_path / "none.json"), "--quiet"])  # fmt: skip
    assert r.exit_code == 2 and "artifact is empty" in r.output


def test_artifact_just_under_the_cap_runs_offline_and_sweeps_every_number(
    tmp_path: Path,
) -> None:
    """A dense, near-cap artifact through the offline path: linear sweep, no blow-up, and
    every number the one claim does not bind is reported."""
    sentence = "Orders were 43,428 in 2017 and 17,071 in Sao Paulo. "
    n = (1 << 20) // len(sentence.encode()) - 1
    artifact = tmp_path / "dense.md"
    artifact.write_text(sentence * n)
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(json.dumps([
        {"id": "c1", "type": "point_value", "span": "Orders were 43,428", "metric": "orders",
         "subject": None, "period": "2017", "confidence": "high", "value": 43428, "unit": None}
    ]))  # fmt: skip
    out = tmp_path / "v.json"
    r = runner.invoke(app, ["verify", str(artifact), "--data", str(DATA), "--config",
                            str(CONFIG), "--claims", str(claims_file), "--json", str(out),
                            "--quiet"])  # fmt: skip
    assert r.exit_code == 0, r.output
    record = json.loads(out.read_text())
    assert record["summary"]["PASS"] == 1
    # the span occurs n times and covers n copies of 43,428; the n copies of 17,071 remain
    assert record["summary"]["unextracted_numeric"] == n
