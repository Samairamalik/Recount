"""Period parser: grammar, half-open endpoints, quarter/year boundaries, leap years
(docs/abstention.md §P)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from recount.compile import Period, PeriodError, parse_period, unit_grain


def _p(start: date, end: date) -> Period:
    return Period(start=start, end=end)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("2017", date(2017, 1, 1), date(2018, 1, 1)),  # P1
        ("2017-Q1", date(2017, 1, 1), date(2017, 4, 1)),  # P2, every spelling
        ("2017Q2", date(2017, 4, 1), date(2017, 7, 1)),
        ("2017 Q3", date(2017, 7, 1), date(2017, 10, 1)),
        ("Q3 2017", date(2017, 7, 1), date(2017, 10, 1)),
        ("Q4-2017", date(2017, 10, 1), date(2018, 1, 1)),  # Q4 crosses the year boundary
        ("q1 2017", date(2017, 1, 1), date(2017, 4, 1)),  # case-insensitive
        ("2017-07", date(2017, 7, 1), date(2017, 8, 1)),  # P3
        ("July 2017", date(2017, 7, 1), date(2017, 8, 1)),
        ("Jul 2017", date(2017, 7, 1), date(2017, 8, 1)),
        ("2017 December", date(2017, 12, 1), date(2018, 1, 1)),  # December -> next Jan 1
        ("2016-02", date(2016, 2, 1), date(2016, 3, 1)),  # leap February, 29 days
        ("2017-02", date(2017, 2, 1), date(2017, 3, 1)),  # 28 days
        ("2017-07-15", date(2017, 7, 15), date(2017, 7, 16)),  # P4
        ("2016-02-29", date(2016, 2, 29), date(2016, 3, 1)),  # leap day exists
        ("2017-12-31", date(2017, 12, 31), date(2018, 1, 1)),
        ("2017-01-01 to 2017-06-30", date(2017, 1, 1), date(2017, 7, 1)),  # P5, inclusive end
        ("2017-Q1..2017-Q2", date(2017, 1, 1), date(2017, 7, 1)),
        ("2017 – 2018", date(2017, 1, 1), date(2019, 1, 1)),  # en dash, spaced
        ("2017 - 2018", date(2017, 1, 1), date(2019, 1, 1)),  # spaced hyphen
        ("Jan 2017 to 2017-Q3", date(2017, 1, 1), date(2017, 10, 1)),  # mixed grains
        ("  2017-q3  ", date(2017, 7, 1), date(2017, 10, 1)),  # whitespace tolerant
    ],
)
def test_accepted_forms(text: str, start: date, end: date) -> None:
    assert parse_period(text) == _p(start, end)


def test_endpoints_are_half_open() -> None:
    q3 = parse_period("2017-Q3")
    assert q3.start == date(2017, 7, 1)  # first day included
    assert q3.end == date(2017, 10, 1)  # first day of the next quarter, excluded
    assert q3.end - timedelta(days=1) == date(2017, 9, 30)  # last included day
    assert (q3.end - q3.start).days == 92
    assert (parse_period("2016-02").end - parse_period("2016-02").start).days == 29
    assert (parse_period("2016").end - parse_period("2016").start).days == 366


@given(st.integers(min_value=1, max_value=9998))
def test_quarters_tile_the_year_without_gap_or_overlap(year: int) -> None:
    qs = [parse_period(f"{year:04d}-Q{n}") for n in (1, 2, 3, 4)]
    assert qs[0].start == date(year, 1, 1)
    for a, b in zip(qs, qs[1:], strict=False):
        assert a.end == b.start
    assert qs[3].end == date(year + 1, 1, 1) == parse_period(f"{year + 1:04d}-Q1").start


@pytest.mark.parametrize(
    "text",
    [
        "first quarter",
        "Q3",  # no year
        "H1 2017",
        "FY2017",
        "2017-2018",  # bare hyphen is not a range separator
        "2017-13",
        "2017-02-29",  # impossible date (extraction error, P7 note)
        "2017-00",
        "last year",
        "YTD",
        "",
        "2017-Q5",
        "Smarch 2017",
        "2017 to",
        "2017 to 2018 to 2019",
    ],
)
def test_p7_unparseable_text_raises(text: str) -> None:
    with pytest.raises(PeriodError, match="cannot parse period"):
        parse_period(text)


def test_p8_reversed_range_raises() -> None:
    with pytest.raises(PeriodError, match="ends before it starts"):
        parse_period("2017-Q3 to 2017-Q1")
    with pytest.raises(PeriodError, match="ends before it starts"):
        parse_period("2017 to 2017-Q1")  # B ends before A ends
    assert parse_period("2017-Q1 to 2017-Q1") == parse_period("2017-Q1")  # degenerate, valid


def test_unit_grain_recognises_exactly_one_unit() -> None:
    assert unit_grain(parse_period("2017")) == "year"
    assert unit_grain(parse_period("2017-Q3")) == "quarter"
    assert unit_grain(parse_period("2017-01 to 2017-03")) == "quarter"  # same interval
    assert unit_grain(parse_period("2017-07")) == "month"
    assert unit_grain(parse_period("2017-07-15")) is None
    assert unit_grain(parse_period("2017-Q1 to 2017-Q2")) is None
    assert unit_grain(parse_period("2017-02 to 2017-04")) is None  # not quarter-aligned
