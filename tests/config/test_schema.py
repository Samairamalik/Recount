from pathlib import Path

import pytest
from pydantic import ValidationError

from recount.config import (
    Entity,
    Metric,
    SemanticConfig,
    entity_index,
    load_config,
    metric_index,
    norm,
)

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


# ----------------------------------------------------------- vocabulary (abstention §0.1, C1–C5)


def _cfg(entities: dict[str, Entity], metrics: dict[str, Metric] | None = None) -> SemanticConfig:
    return SemanticConfig(
        time_column="d", entities=entities, metrics=metrics or {"orders": Metric(agg="count")}
    )


def test_norm_strips_accents_case_and_whitespace() -> None:
    assert norm("São  Paulo") == "sao paulo"
    assert norm("PARANÁ") == norm("Parana") == "parana"
    assert norm("  Rio   de Janeiro ") == "rio de janeiro"


def test_c1_metric_aliases_collide_under_norm() -> None:
    with pytest.raises(ValidationError, match="claimed by both"):
        _cfg(
            {},
            {
                "revenue": Metric(agg="sum", column="r", aliases=["Total Revenue"]),
                "orders": Metric(agg="count", aliases=["total  revenue"]),
            },
        )


def test_metric_index_maps_normalised_aliases_to_names() -> None:
    cfg = load_config(OLIST)
    idx = metric_index(cfg)
    assert idx["gross revenue"] == "revenue" and idx["orders"] == "orders"
    assert "GROSS Revenue" not in idx and idx[norm("GROSS Revenue")] == "revenue"


def test_c3_dimension_named_like_a_time_grain_is_rejected() -> None:
    with pytest.raises(ValidationError, match="reserved time grain"):
        _cfg({"Quarter": Entity(column="q")})


def test_c4_token_resolving_to_two_targets_is_rejected() -> None:
    with pytest.raises(ValidationError, match="resolves to both"):
        _cfg(
            {
                "state": Entity(column="state", aliases={"Sao Paulo": "SP"}),
                "city": Entity(column="city", aliases={"São Paulo": "SAO PAULO"}),
            }
        )
    with pytest.raises(ValidationError, match="resolves to both"):
        _cfg({"state": Entity(column="state", aliases={"Parana": "PR", "Paraná": "PA"})})


def test_c4_same_target_spelled_twice_is_allowed_and_values_resolve() -> None:
    cfg = _cfg({"state": Entity(column="state", aliases={"Sao Paulo": "SP", "São Paulo": "SP"})})
    idx = entity_index(cfg)
    assert idx == {"sao paulo": ("state", "SP"), "sp": ("state", "SP")}


def test_c4_unspecified_is_reserved() -> None:
    with pytest.raises(ValidationError, match="reserved"):
        _cfg({"state": Entity(column="state", aliases={"Unspecified": "XX"})})
    with pytest.raises(ValidationError, match="reserved"):
        _cfg({"state": Entity(column="state", aliases={"Nowhere": "unspecified"})})


def test_c5_share_metric_takes_no_column() -> None:
    with pytest.raises(ValidationError, match="takes no column"):
        Metric(agg="share", column="state")
    assert Metric(agg="share").column is None
