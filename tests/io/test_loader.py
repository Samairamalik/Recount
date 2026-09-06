from __future__ import annotations

from pathlib import Path

import pytest

from recount.config import Entity, Metric, SemanticConfig, load_config
from recount.io import LoadError, load_dataset

OLIST = load_config(Path("tests/fixtures/olist_metrics.yml"))
PARQUET = Path("examples/olist/orders.parquet")


def test_parquet_loads_and_reports_schema() -> None:
    ds = load_dataset(PARQUET, OLIST)
    assert ds.n_rows == 43428
    assert ds.columns == {
        "order_id": "VARCHAR",
        "order_date": "DATE",
        "state": "VARCHAR",
        "revenue": "DOUBLE",
        "delivery_days": "BIGINT",
    }


def _csv(tmp_path: Path, header: str, *lines: str) -> Path:
    p = tmp_path / "d.csv"
    p.write_text("\n".join([header, *lines]) + "\n")
    return p


def test_csv_loads(tmp_path: Path) -> None:
    cfg = SemanticConfig(
        time_column="day",
        entities={"city": Entity(column="city")},
        metrics={"sales": Metric(agg="sum", column="sales")},
    )
    ds = load_dataset(_csv(tmp_path, "day,city,sales", "2017-01-01,A,1.5", "2017-01-02,B,2"), cfg)
    assert ds.n_rows == 2
    assert ds.columns["day"] == "DATE"


def test_unsupported_format_and_missing_file(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match="unsupported"):
        load_dataset(_csv(tmp_path, "a").rename(tmp_path / "d.xlsx"), OLIST)
    with pytest.raises(LoadError, match="not found"):
        load_dataset(tmp_path / "missing.csv", OLIST)


def test_schema_problems_are_reported_together() -> None:
    cfg = SemanticConfig(
        time_column="nope",
        entities={"state": Entity(column="region")},
        metrics={
            "revenue": Metric(agg="sum", column="revenue"),
            "words": Metric(agg="avg", column="order_id"),
            "gone": Metric(agg="sum", column="absent"),
        },
    )
    with pytest.raises(LoadError) as err:
        load_dataset(PARQUET, cfg)
    msg = str(err.value)
    assert "time_column 'nope'" in msg
    assert "entity 'state': column 'region'" in msg
    assert "metric 'words': column 'order_id' is VARCHAR, not numeric" in msg
    assert "metric 'gone': column 'absent'" in msg
    assert "revenue" not in msg


def test_time_column_must_be_temporal(tmp_path: Path) -> None:
    cfg = SemanticConfig(time_column="day", entities={}, metrics={})
    with pytest.raises(LoadError, match="not DATE/TIMESTAMP"):
        load_dataset(_csv(tmp_path, "day", "monday", "tuesday"), cfg)


def test_count_metric_column_may_be_any_type(tmp_path: Path) -> None:
    cfg = SemanticConfig(
        time_column="day", entities={}, metrics={"n": Metric(agg="count", column="who")}
    )
    assert load_dataset(_csv(tmp_path, "day,who", "2017-01-01,x"), cfg).n_rows == 1


def test_caps() -> None:
    with pytest.raises(LoadError, match="cap is 10$"):
        load_dataset(PARQUET, OLIST, max_bytes=10)
    with pytest.raises(LoadError, match="rows; cap is 100$"):
        load_dataset(PARQUET, OLIST, max_rows=100)
