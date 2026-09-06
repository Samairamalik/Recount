"""Property tests (Hypothesis) over random in-memory tables.

round-trip truth:  a claim built from the computed value PASSES
no false accept:   a stated value beyond half-ulp tolerance FAILS
sign-blindness:    growth with the wrong direction FAILS whatever the magnitude
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import duckdb
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from recount.claims import Growth, PointValue
from recount.compile import AggregatePlan, EntityFilter, GrowthPlan, Measure, Period
from recount.config import Entity, Metric, SemanticConfig
from recount.io import Dataset, attach
from recount.verify import execute, verify
from recount.verify.policies import half_ulp_tolerance

CFG = SemanticConfig(
    time_column="d",
    entities={"state": Entity(column="state")},
    metrics={
        "revenue": Metric(agg="sum", column="revenue", round=2),
        "orders": Metric(agg="count"),
        "avg_days": Metric(agg="avg", column="days"),
    },
)
CON = duckdb.connect()
CON.execute("CREATE TABLE data (d DATE, state VARCHAR, revenue DOUBLE, days BIGINT)")

Q = [
    Period(start=date(2017, 1, 1), end=date(2017, 4, 1)),
    Period(start=date(2017, 4, 1), end=date(2017, 7, 1)),
    Period(start=date(2017, 7, 1), end=date(2017, 10, 1)),
    Period(start=date(2017, 10, 1), end=date(2018, 1, 1)),
]
YEAR = Period(start=date(2017, 1, 1), end=date(2018, 1, 1))

row = st.tuples(
    st.dates(min_value=date(2017, 1, 1), max_value=date(2017, 12, 31)),
    st.sampled_from(["SP", "RJ", "MG"]),
    st.floats(min_value=0.01, max_value=10_000, allow_nan=False).map(lambda x: round(x, 2)),
    st.one_of(st.none(), st.integers(min_value=0, max_value=60)),
)
rows = st.lists(row, min_size=1, max_size=40)
measures = st.sampled_from(
    [
        Measure(agg="sum", column="revenue", round=2),
        Measure(agg="count"),
        Measure(agg="avg", column="days"),
    ]
)
periods = st.sampled_from([*Q, YEAR])
entities = st.one_of(
    st.none(), st.sampled_from(["SP", "RJ"]).map(lambda v: EntityFilter(column="state", value=v))
)
decimals = st.integers(min_value=0, max_value=4)


def _load(data: list[tuple[date, str, float, int | None]]) -> Dataset:
    CON.execute("DELETE FROM data")
    CON.executemany("INSERT INTO data VALUES (?, ?, ?, ?)", data)
    return attach(CON, CFG)


def _pv(value: float) -> PointValue:
    return PointValue(
        type="point_value", id="p", span="s", confidence="high", metric="m", period="p", value=value
    )


def _growth(value: float, direction: str) -> Growth:
    return Growth(
        type="growth",
        id="g",
        span="s",
        confidence="high",
        metric="m",
        period="p",
        value=value,
        direction=direction,  # type: ignore[arg-type]
    )


@settings(max_examples=300, deadline=None)
@given(data=rows, measure=measures, period=periods, entity=entities, d=decimals)
def test_claim_built_from_the_computed_value_passes(data, measure, period, entity, d) -> None:  # type: ignore[no-untyped-def]
    ds = _load(data)
    plan = AggregatePlan(time_column="d", measure=measure, period=period, entity=entity)
    computed = execute(ds, plan).values["value"]
    assume(computed is not None)
    v = verify(ds, _pv(round(computed, d)), plan)
    assert v.verdict == "PASS", v.detail


@settings(max_examples=1000, deadline=None)  # Gate G2: no false accepts over 1k cases
@given(
    data=rows,
    measure=measures,
    period=periods,
    entity=entities,
    d=decimals,
    k=st.integers(min_value=-50, max_value=50).filter(lambda k: k != 0),
)
def test_stated_value_beyond_tolerance_fails(data, measure, period, entity, d, k) -> None:  # type: ignore[no-untyped-def]
    ds = _load(data)
    plan = AggregatePlan(time_column="d", measure=measure, period=period, entity=entity)
    computed = execute(ds, plan).values["value"]
    assume(computed is not None)
    stated = float(Decimal(str(round(computed, d))) + Decimal(k).scaleb(-d))
    assume(abs(Decimal(str(stated)) - Decimal(str(computed))) > half_ulp_tolerance(stated))
    v = verify(ds, _pv(stated), plan)
    assert v.verdict == "FAIL" and v.policy == "half_ulp", v.detail


PAIRS = [(a, b) for a in Q for b in Q if a != b]


def _row_in(period: Period, state: str):  # type: ignore[no-untyped-def]
    last = date.fromordinal(period.end.toordinal() - 1)
    return st.tuples(
        st.dates(min_value=period.start, max_value=last),
        st.just(state),
        st.floats(min_value=0.01, max_value=10_000, allow_nan=False).map(lambda x: round(x, 2)),
        st.one_of(st.none(), st.integers(min_value=0, max_value=60)),
    )


@st.composite
def growth_cases(draw):  # type: ignore[no-untyped-def]
    """Random table guaranteed to have rows in both periods (for the entity, if any),
    so the baseline is rarely empty and Hypothesis is not filtering most inputs."""
    cur, base = draw(st.sampled_from(PAIRS))
    entity = draw(entities)
    state = entity.value if entity else "SP"
    data = (
        draw(rows)
        + draw(st.lists(_row_in(cur, state), min_size=1, max_size=20))
        + draw(st.lists(_row_in(base, state), min_size=1, max_size=20))
    )
    return data, cur, base, entity


@settings(max_examples=500, deadline=None)
@given(
    case=growth_cases(),
    measure=measures,
    magnitude=st.sampled_from(["exact", "rounded", "arbitrary"]),
    d=decimals,
    arbitrary=st.floats(min_value=0, max_value=1_000, allow_nan=False),
)
def test_growth_with_flipped_direction_fails_regardless_of_magnitude(  # type: ignore[no-untyped-def]
    case, measure, magnitude, d, arbitrary
) -> None:
    data, cur, base, entity = case
    ds = _load(data)
    plan = GrowthPlan(time_column="d", measure=measure, period=cur, baseline=base, entity=entity)
    pct = execute(ds, plan).values["pct_change"]
    assume(pct is not None and pct != 0)  # all-NULL avg slice, or an exactly equal pair
    right = "increase" if pct > 0 else "decrease"
    wrong = "decrease" if pct > 0 else "increase"
    stated = {"exact": abs(pct), "rounded": round(abs(pct), d), "arbitrary": arbitrary}[magnitude]
    flipped = verify(ds, _growth(stated, wrong), plan)
    assert flipped.verdict == "FAIL" and flipped.policy == "direction", flipped.detail
    # and the same magnitude with the right sign round-trips
    assert verify(ds, _growth(round(abs(pct), d), right), plan).verdict == "PASS"
