"""Every policy branch, exercised without a database."""

from __future__ import annotations

from decimal import Decimal

import pytest

from recount.claims import AbstainReason, Comparison, Growth, PointValue, Ranking, Share
from recount.verify.policies import (
    RankRow,
    check_comparison,
    check_growth,
    check_point_value,
    check_ranking,
    check_share,
    half_ulp_tolerance,
)

_BASE = {"id": "t", "span": "s", "confidence": "high", "metric": "m", "period": "2017"}


def _pv(value: float | None) -> PointValue:
    return PointValue(type="point_value", value=value, **_BASE)


def _growth(value: float | None, direction: str) -> Growth:
    return Growth(type="growth", value=value, direction=direction, **_BASE)  # type: ignore[arg-type]


def _cmp(direction: str, value: float | None = None) -> Comparison:
    return Comparison(type="comparison", direction=direction, value=value, **_BASE)  # type: ignore[arg-type]


def _rank(rank: int, displaced: str | None = None) -> Ranking:
    return Ranking(type="ranking", rank=rank, group_by="state", displaced=displaced, **_BASE)


def _share(value: float | None) -> Share:
    return Share(type="share", value=value, subject="SP", **_BASE)


# ----------------------------------------------------------------- half_ulp


@pytest.mark.parametrize(
    ("stated", "tol"),
    [
        (43428, "0.5"),
        (13.0, "0.5"),  # a float carries no trailing zero: integral means 0 decimals
        (9.3, "0.05"),
        (12.98, "0.005"),
        (159.3796, "0.00005"),
        (2747559.5, "0.05"),
        (1e-7, "5E-8"),
        (1e16, "0.5"),
    ],
)
def test_half_ulp_tolerance(stated: float, tol: str) -> None:
    assert half_ulp_tolerance(stated) == Decimal(tol)


def test_rounding_drift_is_caught_and_the_correct_rounding_passes() -> None:
    # c27: true 41.4654; original 41.47 (diff 0.0046) vs drifted 41.52 (diff 0.0546)
    assert check_point_value(_pv(41.47), 41.4654).verdict == "PASS"
    drift = check_point_value(_pv(41.52), 41.4654)
    assert drift.verdict == "FAIL" and drift.policy == "half_ulp"
    assert drift.delta == pytest.approx(-0.0546)


def test_half_ulp_boundary_is_inclusive_and_exact() -> None:
    # 12.55 is a correct rounding of 12.555; float subtraction would say 0.00499999
    assert check_point_value(_pv(12.55), 12.555).verdict == "PASS"
    assert check_point_value(_pv(12.55), 12.5551).verdict == "FAIL"


def test_point_value_abstentions() -> None:
    vague = check_point_value(_pv(None), 12.0)
    assert vague.verdict == "UNVERIFIABLE" and vague.abstain_reason == AbstainReason.AMBIGUOUS
    empty = check_point_value(_pv(12.0), None)
    assert empty.verdict == "UNVERIFIABLE" and empty.abstain_reason == AbstainReason.NO_DATA


def test_share_mirrors_point_value() -> None:
    assert check_share(_share(39.31), 39.3087).verdict == "PASS"
    assert check_share(_share(5.97), 3.8063).verdict == "FAIL"  # c54 swapped_entity
    assert check_share(_share(None), 3.8).abstain_reason == AbstainReason.AMBIGUOUS
    assert check_share(_share(5.97), None).abstain_reason == AbstainReason.NO_DATA


# ------------------------------------------------------------------- growth


def test_growth_direction_is_checked_before_magnitude() -> None:
    # c25: computed +43.61, claim "declined by 43.61%": exact magnitude, wrong sign
    r = check_growth(_growth(43.61, "decrease"), 43.61)
    assert r.verdict == "FAIL" and r.policy == "direction" and r.delta is None
    assert check_growth(_growth(43.61, "increase"), 43.61).verdict == "PASS"
    assert check_growth(_growth(43.61, "increase"), -43.61).policy == "direction"


def test_growth_zero_change_is_neither_increase_nor_decrease() -> None:
    assert check_growth(_growth(0, "increase"), 0.0).verdict == "FAIL"
    assert check_growth(_growth(0, "decrease"), 0.0).verdict == "FAIL"


def test_growth_magnitude_after_direction() -> None:
    r = check_growth(_growth(80.0, "increase"), 78.0591)
    assert r.verdict == "FAIL" and r.policy == "half_ulp"
    assert r.computed_value == 78.0591  # signed pct is reported, magnitude was compared


def test_growth_abstentions() -> None:
    assert check_growth(_growth(None, "increase"), 81.5).abstain_reason == AbstainReason.AMBIGUOUS
    assert check_growth(_growth(10.0, "increase"), None).abstain_reason == AbstainReason.NO_DATA


# --------------------------------------------------------------- comparison


def test_unchanged_always_abstains() -> None:
    r = check_comparison(_cmp("unchanged"), 10.0, 10.0, "higher_is_better")
    assert r.verdict == "UNVERIFIABLE" and r.abstain_reason == AbstainReason.AMBIGUOUS


def test_better_and_worse_need_polarity() -> None:
    r = check_comparison(_cmp("better"), 12.55, 13.09, None)
    assert r.verdict == "UNVERIFIABLE" and r.abstain_reason == AbstainReason.SCHEMA_GAP
    # c17: delivery days fell, lower is better -> improved
    assert check_comparison(_cmp("better"), 12.55, 13.09, "lower_is_better").verdict == "PASS"
    assert check_comparison(_cmp("worse"), 12.55, 13.09, "lower_is_better").verdict == "FAIL"
    assert check_comparison(_cmp("better"), 12.55, 13.09, "higher_is_better").verdict == "FAIL"
    assert check_comparison(_cmp("worse"), 12.55, 13.09, "higher_is_better").verdict == "PASS"


def test_higher_lower_ignore_polarity_and_check_stated_difference() -> None:
    assert check_comparison(_cmp("higher"), 20.0, 10.0, None).verdict == "PASS"
    assert check_comparison(_cmp("lower"), 20.0, 10.0, None).verdict == "FAIL"
    assert check_comparison(_cmp("higher"), 10.0, 10.0, None).verdict == "FAIL"
    with_value = check_comparison(_cmp("higher", 10.0), 20.0, 10.0, None)
    assert with_value.verdict == "PASS" and with_value.policy == "half_ulp"
    assert check_comparison(_cmp("higher", 10.5), 20.0, 10.0, None).verdict == "FAIL"


def test_comparison_no_data() -> None:
    assert check_comparison(_cmp("higher"), None, 1.0, None).abstain_reason == AbstainReason.NO_DATA


# ------------------------------------------------------------------ ranking

ROWS = (
    RankRow("SP", 17071, 1),
    RankRow("RJ", 5968, 2),
    RankRow("MG", 5240, 3),
    RankRow("SC", 1653, 6),
)


def test_rank_matches_or_fails() -> None:
    ok = check_ranking(_rank(2), "RJ", ROWS)
    assert ok.verdict == "PASS" and ok.policy == "rank" and ok.computed_value == 2
    bad = check_ranking(_rank(3), "SC", ROWS)  # c41 wrong_ranking
    assert bad.verdict == "FAIL" and bad.computed_value == 6 and bad.delta == 3


def test_ties_share_a_rank() -> None:
    tied = (RankRow("A", 5, 1), RankRow("B", 5, 1), RankRow("C", 1, 3))
    assert check_ranking(_rank(1), "B", tied).verdict == "PASS"
    assert check_ranking(_rank(2), "C", tied).verdict == "FAIL"


def test_ranking_abstentions() -> None:
    assert check_ranking(_rank(1, displaced="RJ"), "SP", ROWS).abstain_reason == (
        AbstainReason.UNSUPPORTED_CLAIM_TYPE  # abstention G10
    )
    assert check_ranking(_rank(1), "XX", ROWS).abstain_reason == AbstainReason.NO_DATA
