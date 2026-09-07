"""Numeric sweep: token formats, the year exclusion, and span coverage."""

from __future__ import annotations

import pytest

from recount.claims import ClaimAdapter
from recount.extract import coverage, numeric_tokens, span_intervals, sweep


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("grew 12.4% this year", ["12.4%"]),
        ("worth 1.42M in total", ["1.42M"]),
        ("R$1,447,714.17 in revenue", ["R$1,447,714.17"]),
        ("Indian format 1,41,834 units", ["1,41,834"]),
        ("took 9.3 days on average", ["9.3"]),
        ("43,428 orders and 2,747,559.5 in revenue", ["43,428", "2,747,559.5"]),
        ("about 10K buyers, 2bn views, $5", ["10K", "2bn", "$5"]),
        ("plain 27 states", ["27"]),
    ],
)
def test_token_formats(text: str, tokens: list[str]) -> None:
    assert [t.text for t in numeric_tokens(text)] == tokens


def test_context_carries_the_following_word() -> None:
    (t,) = numeric_tokens("averaging 12.4 days for delivery")
    assert t.context == "12.4 days"
    assert (t.start, t.end) == (10, 14)


@pytest.mark.parametrize("text", ["in 2017", "2017-Q3 revenue", "Q3 and Q4", "id c12", "v1.2.3"])
def test_years_and_glued_digits_are_not_tokens(text: str) -> None:
    assert numeric_tokens(text) == ()


@pytest.mark.parametrize("text", ["2,017", "2017%", "2017.5", "$2017", "1899", "2100"])
def test_a_year_needs_to_look_like_a_bare_year(text: str) -> None:
    assert len(numeric_tokens(text)) == 1


def test_span_intervals_cover_every_occurrence() -> None:
    art = "12 orders here and 12 orders there"
    assert span_intervals(art, ("12 orders",)) == ((0, 9), (19, 28))


def test_sweep_reports_only_uncovered_tokens() -> None:
    art = "Revenue was 1,234.50 across 20 orders in 3 states; 20 orders again."
    left = sweep(art, (("was 1,234.50", (1234.5,)), ("across 20 orders", (20.0,))))
    assert [t.context for t in left] == ["3 states", "20 orders"]
    whole = "Revenue was 1,234.50 across 20 orders in 3 states; 20 orders again."
    assert [t.context for t in sweep(art, ((whole, (1234.5, 20.0, 3.0)),))] == []


def test_token_values_scale_suffixes() -> None:
    text = "1.2M and 10K and 2bn and 12.4% and R$1,447,714.17"
    assert [t.value for t in numeric_tokens(text)] == [1_200_000.0, 10_000.0, 2e9, 12.4, 1447714.17]


def _claim(**fields: object) -> object:
    return ClaimAdapter.validate_python({"id": "c1", "confidence": "high", "period": "2017-Q4",
                                         **fields})  # fmt: skip


def test_token_to_field_coverage_flags_a_number_a_span_merely_encloses() -> None:
    """Stage 6, F-5 (docs/benchmark.md changelog 4): a growth claim whose span swallowed the
    neighbouring figure verifies 41.47 only; 17,280 is flagged until a claim binds it."""
    art = "order count expanded by 41.47% to peak at 17,280 orders."
    merged = _claim(type="growth", span="order count expanded by 41.47% to peak at 17,280 orders",
                    metric="orders", value=41.47, direction="increase",
                    baseline_period="2017-Q3")  # fmt: skip
    assert coverage([merged]) == ((merged.span, (41.47,)),)  # type: ignore[attr-defined]
    assert [t.context for t in sweep(art, coverage([merged]))] == ["17,280 orders"]
    level = _claim(type="point_value", span="to peak at 17,280 orders", metric="orders",
                   value=17280)  # fmt: skip
    assert sweep(art, coverage([merged, level])) == ()
    # a ranking binds its rank, nothing else
    third = _claim(type="ranking", span="3rd of 27 states", metric="orders", rank=3,
                   group_by="state", subject="SP")  # fmt: skip
    assert coverage([third]) == (("3rd of 27 states", (3.0,)),)
    assert [t.context for t in sweep("SP was 3rd of 27 states", coverage([third]))] == ["27 states"]
