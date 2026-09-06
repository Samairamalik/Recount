"""Engine behaviour that the goldens do not pin: hostile values, guards, NULL/empty
semantics, and the text ⇸ SQL wall."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from recount.claims import AbstainReason, ClaimAdapter, PointValue, Ranking, Share
from recount.compile import (
    AggregatePlan,
    EntityFilter,
    EntityKey,
    GrowthPlan,
    Measure,
    Period,
    RankPlan,
    SharePlan,
    TimeKey,
)
from recount.config import load_config
from recount.io import load_dataset
from recount.verify import VerifyError, execute, verify

CFG = load_config(Path("tests/fixtures/olist_metrics.yml"))
DS = load_dataset(Path("examples/olist/orders.parquet"), CFG)
YEAR = Period(start=date(2017, 1, 1), end=date(2018, 1, 1))
Y2016 = Period(start=date(2016, 1, 1), end=date(2017, 1, 1))
ORDERS = Measure(agg="count")
REVENUE = Measure(agg="sum", column="revenue", round=2)
DAYS = Measure(agg="avg", column="delivery_days")
HOSTILE = "SP' OR 1=1 --"


def _pv(value: float, subject: str | None = None) -> PointValue:
    return PointValue(
        type="point_value",
        id="t",
        span="s",
        confidence="high",
        metric="orders",
        period="2017",
        value=value,
        subject=subject,
    )


def test_hostile_entity_value_is_a_bound_parameter_not_sql() -> None:
    plan = AggregatePlan(
        time_column="order_date",
        measure=ORDERS,
        period=YEAR,
        entity=EntityFilter(column="state", value=HOSTILE),
    )
    v = verify(DS, _pv(43428, HOSTILE), plan)
    assert v.computed_value == 0  # no state is literally named that; nothing was injected
    assert v.verdict == "FAIL"
    assert v.params["entity"] == HOSTILE
    assert HOSTILE not in v.sql and "1=1" not in v.sql
    share = SharePlan(
        time_column="order_date",
        measure=ORDERS,
        period=YEAR,
        part=EntityFilter(column="state", value=HOSTILE),
    )
    assert execute(DS, share).values["share_pct"] == 0


def test_sql_text_never_contains_claim_text_or_values() -> None:
    claim = Share(
        type="share",
        id="c33",
        span="representing roughly two-fifths of all orders at 39.31%",
        confidence="high",
        metric="order_share_pct",
        period="2017",
        subject="Sao Paulo",
        value=39.31,
    )
    plan = SharePlan(
        time_column="order_date",
        measure=ORDERS,
        period=YEAR,
        part=EntityFilter(column="state", value="SP"),
    )
    v = verify(DS, claim, plan)
    for text in ("Sao Paulo", "39.31", "SP", "two-fifths", "2017"):
        assert text not in v.sql
    assert v.params == {"start": date(2017, 1, 1), "end": date(2018, 1, 1), "entity": "SP"}


def test_unknown_column_is_refused_before_rendering() -> None:
    plan = AggregatePlan(
        time_column="order_date", measure=Measure(agg="sum", column="nope"), period=YEAR
    )
    with pytest.raises(VerifyError, match="nope"):
        execute(DS, plan)


def test_claim_plan_kind_mismatch_is_an_error_not_a_verdict() -> None:
    plan = SharePlan(
        time_column="order_date",
        measure=ORDERS,
        period=YEAR,
        part=EntityFilter(column="state", value="SP"),
    )
    with pytest.raises(VerifyError, match="point_value"):
        verify(DS, _pv(1), plan)


def test_avg_reports_the_null_excluded_denominator() -> None:
    v = execute(DS, AggregatePlan(time_column="order_date", measure=DAYS, period=YEAR))
    assert v.row_counts == {"n_rows": 43428, "n_used": 43426}


def test_empty_slice_sum_abstains_no_data_but_count_is_zero() -> None:
    empty_sum = AggregatePlan(time_column="order_date", measure=REVENUE, period=Y2016)
    v = verify(DS, _pv(1.0), empty_sum)
    assert v.verdict == "UNVERIFIABLE" and v.abstain_reason == AbstainReason.NO_DATA
    assert v.row_counts["n_rows"] == 0
    empty_count = AggregatePlan(time_column="order_date", measure=ORDERS, period=Y2016)
    assert verify(DS, _pv(0), empty_count).verdict == "PASS"
    assert verify(DS, _pv(5), empty_count).verdict == "FAIL"


def test_zero_baseline_growth_abstains_no_data() -> None:
    claim = ClaimAdapter.validate_python(
        {
            "id": "g",
            "type": "growth",
            "span": "s",
            "confidence": "high",
            "metric": "orders",
            "period": "2017",
            "baseline_period": "2016",
            "value": 10.0,
            "direction": "increase",
        }
    )
    plan = GrowthPlan(time_column="order_date", measure=ORDERS, period=YEAR, baseline=Y2016)
    v = verify(DS, claim, plan)
    assert v.abstain_reason == AbstainReason.NO_DATA
    assert v.row_counts == {"n_current": 43428, "n_baseline": 0}


def test_rank_by_month_grain_and_absent_subject() -> None:
    plan = RankPlan(
        time_column="order_date",
        measure=ORDERS,
        period=YEAR,
        group_by=TimeKey(grain="month"),
        subject_key="2017-11-01",
        polarity="higher_is_better",
    )
    computed = execute(DS, plan)
    assert computed.row_counts["n_groups"] == 12
    assert computed.rows[0].key == "2017-11-01"  # Black Friday month
    assert computed.params["grain"] == "month"
    claim = Ranking(
        type="ranking",
        id="r",
        span="s",
        confidence="high",
        metric="orders",
        period="2017-11",
        rank=1,
        group_by="month",
    )
    assert verify(DS, claim, plan).verdict == "PASS"
    absent = plan.model_copy(update={"subject_key": "2019-01-01"})
    assert verify(DS, claim, absent).abstain_reason == AbstainReason.NO_DATA


def test_rank_excludes_null_keys_and_counts_groups() -> None:
    plan = RankPlan(
        time_column="order_date",
        measure=REVENUE,
        period=YEAR,
        group_by=EntityKey(column="state"),
        subject_key="SP",
        polarity="higher_is_better",
    )
    computed = execute(DS, plan)
    assert computed.row_counts == {"n_rows": 43428, "n_groups": 27}
    assert [r.key for r in computed.rows[:3]] == ["SP", "RJ", "MG"]
