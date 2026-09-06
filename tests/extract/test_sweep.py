"""Numeric sweep: token formats, the year exclusion, and span coverage."""

from __future__ import annotations

import pytest

from recount.extract import numeric_tokens, span_intervals, sweep


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
    left = sweep(art, ("was 1,234.50", "across 20 orders"))
    assert [t.context for t in left] == ["3 states", "20 orders"]
    assert (
        sweep(art, ("Revenue was 1,234.50 across 20 orders in 3 states; 20 orders again.",)) == ()
    )
