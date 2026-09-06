"""Period parser: a period string as written -> half-open Period (docs/abstention.md §P).

Grammar (after norm(): casefold, whitespace collapsed), every form half-open:
  year     2017                                   [2017-01-01, 2018-01-01)
  quarter  2017-Q3 | 2017Q3 | 2017 Q3 | Q3 2017 | Q3-2017
  month    2017-07 | July 2017 | Jul 2017 | 2017 July
  day      2017-07-15 (a valid calendar date)     [2017-07-15, 2017-07-16)
  range    A to B | A..B | A – B | A - B  (spaced hyphen); A, B any single form;
           the written end is inclusive: 2017-01-01 to 2017-06-30 -> [.., 2017-07-01)
A bare hyphen never makes a range ("2017-2018"): it is the ISO separator inside
2017-07 and 2017-07-15, and "2017-18" could be a fiscal year or a mistyped month.
Nothing relative ("last year") parses: the parser never reads the clock.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

from recount.compile.plans import Period
from recount.config import norm

Grain = Literal["month", "quarter", "year"]

ACCEPTED_FORMS = "YYYY, YYYY-Qn, YYYY-MM, YYYY-MM-DD, Month YYYY, or 'A to B'"

_YEAR = re.compile(r"^(\d{4})$")
_QUARTER_YQ = re.compile(r"^(\d{4})[- ]?q([1-4])$")
_QUARTER_QY = re.compile(r"^q([1-4])[- ](\d{4})$")
_MONTH_NUM = re.compile(r"^(\d{4})-(\d{2})$")
_MONTH_NAME_MY = re.compile(r"^([a-z]+) (\d{4})$")
_MONTH_NAME_YM = re.compile(r"^(\d{4}) ([a-z]+)$")
_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RANGE_SEP = re.compile(r" to |\.\.| [-–—] ")

_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)  # fmt: skip
_MONTHS: dict[str, int] = {}
for _i, _name in enumerate(_MONTH_NAMES, 1):
    _MONTHS[_name] = _i
    _MONTHS[_name[:3]] = _i


class PeriodError(ValueError):
    """Not a period in the accepted grammar (P7), or a range that ends before it starts (P8)."""


def parse_period(text: str) -> Period:
    t = norm(text)
    parts = _RANGE_SEP.split(t)
    if len(parts) == 2:
        a, b = _unit(parts[0], text), _unit(parts[1], text)
        if b.start < a.start or b.end < a.end:  # P8
            raise PeriodError(f"period range '{text}' ends before it starts")
        return Period(start=a.start, end=b.end)  # P5
    return _unit(t, text)


def unit_grain(period: Period) -> Grain | None:
    """The grain this period is exactly one unit of, or None (abstention G8)."""
    s = period.start
    if s.day != 1:
        return None
    if s.month == 1 and period.end == date(s.year + 1, 1, 1):
        return "year"
    if s.month in (1, 4, 7, 10) and period.end == _add_months(s, 3):
        return "quarter"
    if period.end == _add_months(s, 1):
        return "month"
    return None


def _unit(t: str, original: str) -> Period:
    try:
        return _match_unit(t)
    except ValueError as e:  # bad calendar date (2017-02-29) or an out-of-range year
        raise PeriodError(f"cannot parse period '{original}'; {e}") from e
    except _NoForm:
        raise PeriodError(
            f"cannot parse period '{original}'; accepted forms: {ACCEPTED_FORMS}"
        ) from None


class _NoForm(Exception):
    pass


def _match_unit(t: str) -> Period:
    if m := _YEAR.match(t):  # P1
        start = date(int(m[1]), 1, 1)
        return Period(start=start, end=_add_months(start, 12))
    if m := _QUARTER_YQ.match(t):  # P2
        return _quarter(int(m[1]), int(m[2]))
    if m := _QUARTER_QY.match(t):  # P2
        return _quarter(int(m[2]), int(m[1]))
    if m := _MONTH_NUM.match(t):  # P3
        return _month(int(m[1]), int(m[2]))
    if m := _MONTH_NAME_MY.match(t):  # P3
        if m[1] in _MONTHS:
            return _month(int(m[2]), _MONTHS[m[1]])
    if m := _MONTH_NAME_YM.match(t):  # P3
        if m[2] in _MONTHS:
            return _month(int(m[1]), _MONTHS[m[2]])
    if m := _DAY.match(t):  # P4
        start = date(int(m[1]), int(m[2]), int(m[3]))
        return Period(start=start, end=start + timedelta(days=1))
    raise _NoForm


def _quarter(year: int, q: int) -> Period:
    start = date(year, 3 * q - 2, 1)
    return Period(start=start, end=_add_months(start, 3))


def _month(year: int, month: int) -> Period:
    start = date(year, month, 1)  # raises ValueError for month 13
    return Period(start=start, end=_add_months(start, 1))


def _add_months(start: date, months: int) -> date:
    total = start.year * 12 + (start.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)
