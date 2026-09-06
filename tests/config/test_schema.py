from pathlib import Path

import pytest
from pydantic import ValidationError

from recount.config import Metric, SemanticConfig, load_config

OLIST = Path("tests/fixtures/olist_metrics.yml")


def test_olist_config_loads() -> None:
    cfg = load_config(OLIST)
    assert cfg.time_column == "order_date"
    assert cfg.tolerance_rule == "half_ulp"
    assert cfg.entities["state"].aliases["Sao Paulo"] == "SP"
    assert set(cfg.metrics) == {
        "revenue",
        "orders",
        "avg_order_value",
        "avg_delivery_days",
        "order_share_pct",
    }
    assert cfg.metrics["revenue"].round == 2
    assert cfg.metrics["orders"].column is None
    assert cfg.metrics["avg_delivery_days"].polarity == "lower_is_better"
    assert "gross revenue" in cfg.metrics["revenue"].aliases


def test_sum_needs_a_column() -> None:
    with pytest.raises(ValidationError, match="needs a column"):
        Metric(agg="sum")


def test_polarity_has_no_default() -> None:
    assert Metric(agg="count").polarity is None


def test_alias_cannot_belong_to_two_metrics() -> None:
    with pytest.raises(ValidationError, match="claimed by both"):
        SemanticConfig(
            time_column="d",
            entities={},
            metrics={
                "revenue": Metric(agg="sum", column="r", aliases=["sales"]),
                "orders": Metric(agg="count", aliases=["sales"]),
            },
        )


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SemanticConfig.model_validate(
            {"time_column": "d", "entities": {}, "metrics": {}, "entity_column": "state"}
        )
