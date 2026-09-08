from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from recount.compile import (
    AggregatePlan,
    Measure,
    Period,
    PlanAdapter,
    RankPlan,
    SharePlan,
    TimeKey,
)

P = Period(start=date(2017, 7, 1), end=date(2017, 10, 1))


def test_period_is_half_open_and_non_empty() -> None:
    with pytest.raises(ValidationError, match="start < end"):
        Period(start=date(2017, 1, 1), end=date(2017, 1, 1))


def test_measure_sum_and_avg_need_a_column() -> None:
    with pytest.raises(ValidationError, match="needs a column"):
        Measure(agg="avg")
    assert Measure(agg="count").column is None


def test_share_of_an_average_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not defined"):
        SharePlan(
            time_column="d",
            measure=Measure(agg="avg", column="x"),
            period=P,
            part={"column": "state", "value": "SP"},  # type: ignore[arg-type]
        )


def test_rank_requires_an_order() -> None:
    """Stage 8: the plan carries the resolved end (compiler rows G9/G12), so a plan
    without one cannot be built and the engine has no default to fall back on."""
    with pytest.raises(ValidationError, match="order"):
        RankPlan.model_validate(
            {
                "time_column": "d",
                "measure": {"agg": "count"},
                "period": P.model_dump(),
                "group_by": {"by": "time", "grain": "quarter"},
                "subject_key": "2017-07-01",
            }
        )


def test_plans_are_frozen_closed_and_round_trip() -> None:
    plan = RankPlan(
        time_column="d",
        measure=Measure(agg="avg", column="days"),
        period=P,
        group_by=TimeKey(grain="quarter"),
        subject_key="2017-07-01",
        order="asc",
    )
    again = PlanAdapter.validate_json(plan.model_dump_json())
    assert again == plan and again.kind == "rank"
    with pytest.raises(ValidationError):
        plan.subject_key = "RJ"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        AggregatePlan(time_column="d", measure=Measure(agg="count"), period=P, sql="SELECT 1")  # type: ignore[call-arg]
