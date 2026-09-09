"""Compiler rows, one test per row of docs/abstention.md, on synthetic claims and the
Olist fixture config. The end-to-end goldens live in tests/verify/test_goldens.py."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from recount.claims import (
    AbstainReason,
    Claim,
    ClaimAdapter,
    Comparison,
    Growth,
    PointValue,
    Ranking,
    Share,
)
from recount.compile import (
    Abstain,
    AggregatePlan,
    ComparePlan,
    EntityFilter,
    EntityKey,
    GrowthPlan,
    Measure,
    Period,
    RankPlan,
    SharePlan,
    TimeKey,
    compile_claim,
)
from recount.config import Entity, SemanticConfig, load_config

CFG = load_config(Path("tests/fixtures/olist_metrics.yml"))
RECORDS: list[dict[str, Any]] = json.loads(Path("tests/fixtures/labeled_claims.json").read_text())[
    "claims"
]
Y2017 = Period(start=date(2017, 1, 1), end=date(2018, 1, 1))
Q1 = Period(start=date(2017, 1, 1), end=date(2017, 4, 1))
Q2 = Period(start=date(2017, 4, 1), end=date(2017, 7, 1))
SP = EntityFilter(column="state", value="SP")


def fixture(cid: str) -> Claim:
    return ClaimAdapter.validate_python(
        next(r["claim"] for r in RECORDS if r["claim"]["id"] == cid)
    )


def echoed(cid: str) -> Claim:
    """A fixture claim whose span is prefixed with its metric name, so the M3 echo gate
    (Stage 6) lets the row under test decide. Fixture spans marked echo_gap (F5) would
    otherwise abstain M3 last."""
    c = fixture(cid)
    return c.model_copy(update={"span": f"{c.metric} {c.span}"})


def without_polarity(cfg: SemanticConfig, name: str) -> SemanticConfig:
    metrics = dict(cfg.metrics)
    metrics[name] = metrics[name].model_copy(update={"polarity": None})
    return cfg.model_copy(update={"metrics": metrics})


# Synthetic spans echo their metric ("revenue s") so the M3 echo gate lets the row under
# test decide; M3 itself is tested at the end.
def pv(metric: str = "revenue", value: float | None = 1.0, **kw: Any) -> PointValue:
    base: dict[str, Any] = {"id": "t", "span": f"{metric} s", "confidence": "high",
                            "period": "2017"}  # fmt: skip
    return PointValue(type="point_value", metric=metric, value=value, **(base | kw))


def _echoing(fields: dict[str, Any]) -> dict[str, Any]:
    return {"span": f"{fields['metric']} s", **fields}


def growth(**kw: Any) -> Growth:
    base: dict[str, Any] = {
        "id": "t", "confidence": "high", "metric": "orders", "value": 10.0,
        "direction": "increase", "period": "2017-Q2", "baseline_period": "2017-Q1",
    }  # fmt: skip
    return Growth(type="growth", **_echoing(base | kw))


def cmp(**kw: Any) -> Comparison:
    base: dict[str, Any] = {
        "id": "t", "confidence": "high", "metric": "avg_delivery_days", "value": None,
        "direction": "lower", "period": "2017-Q2", "baseline_period": "2017-Q1",
    }  # fmt: skip
    return Comparison(type="comparison", **_echoing(base | kw))


def rank(**kw: Any) -> Ranking:
    base: dict[str, Any] = {
        "id": "t", "confidence": "high", "metric": "orders", "rank": 1,
        "rank_from": "best", "group_by": "state", "subject": "Sao Paulo", "period": "2017",
    }  # fmt: skip
    return Ranking(type="ranking", **_echoing(base | kw))


def share(**kw: Any) -> Share:
    base: dict[str, Any] = {
        "id": "t", "confidence": "high", "metric": "order_share_pct", "value": 39.31,
        "subject": "Sao Paulo", "period": "2017",
    }  # fmt: skip
    return Share(type="share", **_echoing(base | kw))


def abstains(claim: Claim, reason: AbstainReason, detail: str, cfg: SemanticConfig = CFG) -> None:
    out = compile_claim(claim, cfg)
    assert isinstance(out, Abstain), out
    assert out.reason == reason, out
    assert detail in out.detail, out.detail


# ------------------------------------------------------------------ M


def test_m1_metric_aliases_resolve_under_norm() -> None:
    for name in ("revenue", "Total  Revenue", "GROSS REVENUE"):
        plan = compile_claim(pv(metric=name), CFG)
        assert isinstance(plan, AggregatePlan)
        assert plan.measure == Measure(agg="sum", column="revenue", round=2)


def test_m2_unknown_metric_is_schema_gap() -> None:
    abstains(fixture("c1"), AbstainReason.SCHEMA_GAP, "unknown metric 'state_count'")


# ------------------------------------------------------------------ E


def test_e1_null_subject_means_no_entity_filter() -> None:
    plan = compile_claim(fixture("c2"), CFG)
    assert isinstance(plan, AggregatePlan) and plan.entity is None and plan.period == Y2017


@pytest.mark.parametrize("subject", ["Sao Paulo", "São Paulo", "SAO PAULO", "SP", " sp "])
def test_e2_subject_resolves_from_alias_keys_and_stored_values_with_accents(subject: str) -> None:
    plan = compile_claim(pv(subject=subject), CFG)
    assert isinstance(plan, AggregatePlan) and plan.entity == SP


def test_e4_unknown_entity_is_schema_gap_before_any_vagueness() -> None:
    # c30 also lacks a baseline (V5); resolution is reported first (abstention §0.2).
    abstains(
        fixture("c30"), AbstainReason.SCHEMA_GAP, "unknown entity 'Southeast and South regions'"
    )


# ------------------------------------------------------------------ G


def test_binding_b_time_grain_group_by_resolves_from_time_column_never_entities() -> None:
    """Learning-log Stage 3 requirement (b), abstention G1/G8: c23 ranks quarters by
    avg_delivery_days. No entities dimension is named 'quarter' (C3 forbids it), and
    the claim still compiles, keyed on the time column."""
    assert "quarter" not in CFG.entities
    plan = compile_claim(echoed("c23"), CFG)
    assert plan == RankPlan(
        time_column="order_date",
        measure=Measure(agg="avg", column="delivery_days"),
        period=Y2017,  # scope "2017"
        group_by=TimeKey(grain="quarter"),
        subject_key="2017-07-01",
        order="asc",  # rank_from "best" through lower_is_better (G9)
    )


def test_g2_entity_ranking_keys_on_the_dimension_column() -> None:
    plan = compile_claim(echoed("c36"), CFG)
    assert isinstance(plan, RankPlan)
    assert plan.group_by == EntityKey(column="state") and plan.subject_key == "RJ"
    assert plan.period == Y2017 and plan.order == "desc"


def test_g3_unknown_group_by_is_schema_gap() -> None:
    abstains(rank(group_by="region"), AbstainReason.SCHEMA_GAP, "group_by 'region' is neither")


def test_g4_entity_ranking_needs_a_subject() -> None:
    abstains(rank(subject=None), AbstainReason.AMBIGUOUS, "ranking needs a subject")


def test_g5_subject_must_be_an_alias_of_that_dimension() -> None:
    cfg = CFG.model_copy(
        update={
            "entities": dict(CFG.entities) | {"city": Entity(column="city", aliases={"Rio": "RIO"})}
        }
    )
    abstains(rank(subject="Rio"), AbstainReason.SCHEMA_GAP, "'Rio' is not a 'state' alias", cfg)
    abstains(rank(subject="Nowhere"), AbstainReason.SCHEMA_GAP, "not a 'state' alias")


def test_g6_time_grain_ranking_within_an_entity_is_unsupported() -> None:
    abstains(
        rank(group_by="quarter", subject="Sao Paulo", period="2017-Q3", scope="2017"),
        AbstainReason.UNSUPPORTED_CLAIM_TYPE,
        "within an entity",
    )


def test_g7_ranking_years_is_withheld_as_no_data() -> None:
    abstains(
        rank(group_by="year", subject=None, period="2017", scope="2016 to 2018"),
        AbstainReason.NO_DATA,
        "ranking years is withheld",
    )


def test_g8_period_must_be_one_unit_and_scope_must_contain_it() -> None:
    base = {"group_by": "quarter", "subject": None, "metric": "avg_delivery_days"}
    abstains(
        rank(period="2017", scope="2017", **base), AbstainReason.AMBIGUOUS, "not a single quarter"
    )
    abstains(rank(period="2017-Q3", scope=None, **base), AbstainReason.AMBIGUOUS, "no scope stated")
    abstains(
        rank(period="2017-Q3", scope="2016", **base), AbstainReason.AMBIGUOUS, "lies outside scope"
    )
    abstains(
        rank(period="2017-Q3", scope="then", **base), AbstainReason.AMBIGUOUS, "scope: cannot parse"
    )
    plan = compile_claim(
        rank(period="2017-07", scope="2017-Q3", group_by="month", subject=None), CFG
    )
    assert isinstance(plan, RankPlan) and plan.group_by == TimeKey(grain="month")
    assert plan.subject_key == "2017-07-01" and plan.period == Period(
        start=date(2017, 7, 1), end=date(2017, 10, 1)
    )


def test_g9_a_best_worst_ranking_needs_polarity() -> None:
    """G9 (Stage 8): polarity is needed only where the claim ranks by quality. A claim
    that names the numeric end itself compiles without it — coverage the old rule lost."""
    no_pol = without_polarity(CFG, "orders")
    abstains(rank(), AbstainReason.SCHEMA_GAP, "needs polarity", no_pol)
    abstains(rank(rank_from="worst"), AbstainReason.SCHEMA_GAP, "needs polarity", no_pol)
    plan = compile_claim(rank(rank_from="highest"), no_pol)
    assert isinstance(plan, RankPlan) and plan.order == "desc"


def test_g12_rank_direction_comes_from_the_claim_not_the_polarity() -> None:
    """F-3: which end rank 1 counts from is the sentence's, not the config's. Both ends
    of one metric are expressible, and a claim that names neither abstains."""
    assert CFG.metrics["avg_delivery_days"].polarity == "lower_is_better"
    slowest = compile_claim(
        rank(metric="avg_delivery_days", rank_from="highest", subject="Sao Paulo"), CFG
    )
    fastest = compile_claim(
        rank(metric="avg_delivery_days", rank_from="lowest", subject="Sao Paulo"), CFG
    )
    assert isinstance(slowest, RankPlan) and slowest.order == "desc"
    assert isinstance(fastest, RankPlan) and fastest.order == "asc"
    # "best" on a lower_is_better metric is the low end; "worst" is the high end
    assert compile_claim(rank(metric="avg_delivery_days", rank_from="best"), CFG).order == "asc"
    assert compile_claim(rank(metric="avg_delivery_days", rank_from="worst"), CFG).order == "desc"
    abstains(rank(rank_from=None), AbstainReason.AMBIGUOUS, "no rank direction")


def test_g10_displaced_is_unsupported_rank_change() -> None:
    abstains(fixture("c11"), AbstainReason.UNSUPPORTED_CLAIM_TYPE, "'displaced unspecified'")
    abstains(rank(displaced="Rio de Janeiro"), AbstainReason.UNSUPPORTED_CLAIM_TYPE, "overtaking")


def test_g11_a_restricted_entity_ranking_universe_is_ambiguous() -> None:
    """F-4: the sentence's own restriction reaches the compiler instead of being dropped,
    and an unquantified one cannot be resolved — so it abstains rather than ranking the
    subject against every group in the data and FAILing a true sentence."""
    abstains(
        rank(scope="among top companies"),
        AbstainReason.AMBIGUOUS,
        "restricts the ranking universe to 'among top companies'",
    )
    abstains(rank(scope="2017"), AbstainReason.AMBIGUOUS, "cannot resolve '2017'")


# ------------------------------------------------------------------ D


def test_d1_unchanged_has_no_threshold() -> None:
    abstains(fixture("c5"), AbstainReason.AMBIGUOUS, "'unchanged' has no threshold")


def test_binding_a_better_worse_without_polarity_is_schema_gap() -> None:
    """Learning-log Stage 3 requirement (a), abstention D2: c17 'delivery performance
    improved' is only checkable because the config says lower avg_delivery_days is
    better. Remove the polarity and the compiler must abstain, never default."""
    improved = echoed("c17")
    plan = compile_claim(improved, CFG)  # D3
    assert isinstance(plan, ComparePlan) and plan.polarity == "lower_is_better"
    abstains(
        improved,
        AbstainReason.SCHEMA_GAP,
        "'better' needs metrics.avg_delivery_days.polarity",
        without_polarity(CFG, "avg_delivery_days"),
    )


def test_d4_higher_lower_compile_without_polarity() -> None:
    plan = compile_claim(cmp(direction="lower"), without_polarity(CFG, "avg_delivery_days"))
    assert isinstance(plan, ComparePlan) and plan.polarity is None
    assert plan.period == Q2 and plan.baseline == Q1


# ------------------------------------------------------------------ V


def test_v1_v2_v3_null_values_are_ambiguous() -> None:
    abstains(pv(value=None), AbstainReason.AMBIGUOUS, "no stated value")
    abstains(share(value=None), AbstainReason.AMBIGUOUS, "no stated share")
    abstains(fixture("c12"), AbstainReason.AMBIGUOUS, "no stated growth magnitude")


def test_v4_direction_only_comparison_compiles() -> None:
    plan = compile_claim(cmp(value=None), CFG)
    assert isinstance(plan, ComparePlan)


def test_v5_missing_baseline_is_ambiguous() -> None:
    abstains(fixture("c7"), AbstainReason.AMBIGUOUS, "no baseline period")
    abstains(growth(baseline_period=None), AbstainReason.AMBIGUOUS, "compared against what")


def test_v6_baseline_must_precede_the_period() -> None:
    """Row authored by the project owner: growth and comparison run backwards in time."""
    detail = "does not precede period"
    c17, c13 = fixture("c17"), fixture("c13")
    assert isinstance(c17, Comparison) and isinstance(c13, Growth)
    swapped_cmp = c17.model_copy(
        update={"period": c17.baseline_period, "baseline_period": c17.period}
    )
    swapped_growth = c13.model_copy(
        update={"period": c13.baseline_period, "baseline_period": c13.period}
    )
    abstains(swapped_cmp, AbstainReason.AMBIGUOUS, detail)
    abstains(swapped_growth, AbstainReason.AMBIGUOUS, detail)
    abstains(growth(period="2017-Q1", baseline_period="Q1 2017"), AbstainReason.AMBIGUOUS, detail)
    abstains(growth(period="2017-Q1", baseline_period="2017"), AbstainReason.AMBIGUOUS, detail)
    assert isinstance(compile_claim(c13, CFG), GrowthPlan)  # the fixture's own order is fine


# ------------------------------------------------------------------ X


def test_x1_share_metric_measures_the_row_count() -> None:
    plan = compile_claim(fixture("c33"), CFG)
    assert plan == SharePlan(
        time_column="order_date", measure=Measure(agg="count"), period=Y2017, part=SP
    )
    revenue_share = compile_claim(share(metric="revenue"), CFG)
    assert isinstance(revenue_share, SharePlan) and revenue_share.measure.agg == "sum"


def test_x2_share_of_an_average_is_ambiguous() -> None:
    abstains(share(metric="avg_order_value"), AbstainReason.AMBIGUOUS, "share of an average")


def test_x3_x4_share_metric_on_other_claim_types_is_unsupported() -> None:
    abstains(
        pv(metric="order share", subject="Sao Paulo"),
        AbstainReason.UNSUPPORTED_CLAIM_TYPE,
        "is a share",
    )
    abstains(
        growth(metric="order_share_pct"),
        AbstainReason.UNSUPPORTED_CLAIM_TYPE,
        "silently compute the count",
    )
    abstains(
        cmp(metric="order_share_pct"),
        AbstainReason.UNSUPPORTED_CLAIM_TYPE,
        "silently compute the count",
    )


def test_x5_ranking_by_a_share_metric_ranks_by_count() -> None:
    plan = compile_claim(rank(metric="order_share_pct"), CFG)
    assert isinstance(plan, RankPlan) and plan.measure == Measure(agg="count")


# ------------------------------------------------------------------ P


def test_p6_null_period_is_ambiguous() -> None:
    abstains(pv(period=None), AbstainReason.AMBIGUOUS, "no period stated")


def test_p7_p8_unparseable_or_reversed_periods_are_ambiguous() -> None:
    abstains(
        pv(period="first quarter"), AbstainReason.AMBIGUOUS, "cannot parse period 'first quarter'"
    )
    abstains(pv(period="2017-Q3 to 2017-Q1"), AbstainReason.AMBIGUOUS, "ends before it starts")
    abstains(
        growth(baseline_period="last quarter"),
        AbstainReason.AMBIGUOUS,
        "baseline period: cannot parse",
    )


def test_p11_overlapping_earlier_baseline_compiles() -> None:
    plan = compile_claim(cmp(period="2017-Q4", baseline_period="2017"), CFG)
    assert isinstance(plan, ComparePlan) and plan.baseline == Y2017


# ------------------------------------------------------------------ determinism


# ------------------------------------------------------------------ M3 (Stage 6, F-2)


def test_m3_span_must_echo_the_bound_metric() -> None:
    """The two Stage 5 false accepts: a rewritten metric bound to a real one from context."""
    abstains(
        pv(
            "average delivery time",
            9.3,
            span="average return time of just 9.3 days",
            subject="Sao Paulo",
        ),  # fmt: skip
        AbstainReason.SCHEMA_GAP,
        "metric_echo_failed: nothing in the span resolves to 'avg_delivery_days'",
    )
    abstains(
        pv("order volume", 8984, span="to reach 8,984 returns", period="2017-Q2"),
        AbstainReason.SCHEMA_GAP,
        "add that wording under metrics.orders.aliases",
    )
    # no wording at all is refused the same way: the binding came from outside the span
    abstains(pv("revenue", 1447714.17, span="to hit 1,447,714.17"), AbstainReason.SCHEMA_GAP,
             "metric_echo_failed")  # fmt: skip
    # any alias of the bound metric, whole-word under norm(), satisfies the echo
    for span in ("Total Revenue of 1.0", "gross  revenue 1.0", "REVENUE: 1.0"):
        assert isinstance(compile_claim(pv("revenue", 1.0, span=span), CFG), AggregatePlan), span
    # a substring is not a word: "orders" does not echo "borders"
    abstains(pv("orders", 5, span="5 borders"), AbstainReason.SCHEMA_GAP, "metric_echo_failed")


def test_schema_gap_details_name_the_rule_and_the_line_to_paste() -> None:
    """F-1: full-string matching surprised a new user into 25 of 36 first-run abstentions.
    The message that reports the gap now states the rule and prints the YAML to paste."""
    out = compile_claim(pv(metric="total driver tips", span="total driver tips of 1.0"), CFG)
    assert isinstance(out, Abstain)
    assert "matched in full after normalisation, never as a substring" in out.detail
    assert 'aliases: [..., "total driver tips"]' in out.detail
    entity = compile_claim(pv(subject="Ceara"), CFG)
    assert isinstance(entity, Abstain)
    assert '"Ceara": <the value stored in that column>' in entity.detail


def test_m3_share_span_may_name_the_row_count_metric() -> None:
    """'13.74% of total orders' names the share's denominator (C5), not another metric."""
    plan = compile_claim(share(span="accounted for 13.74% of total orders nationwide"), CFG)
    assert isinstance(plan, SharePlan)
    abstains(share(span="accounted for 13.74% of total revenue"), AbstainReason.SCHEMA_GAP,
             "metric_echo_failed")  # fmt: skip


def test_m3_is_the_last_gate_so_other_reasons_survive() -> None:
    # vague and unechoed: the vagueness row answers first (V3), as the table orders it
    abstains(growth(value=None, span="nearly doubled"), AbstainReason.AMBIGUOUS,
             "no stated growth magnitude")  # fmt: skip
    # unknown metric: M2 before M3
    abstains(pv("state_count", 27, span="27 states"), AbstainReason.SCHEMA_GAP, "unknown metric")


def test_compilation_is_deterministic() -> None:
    for cid in ("c3", "c13", "c17", "c23", "c33", "c11"):
        assert compile_claim(fixture(cid), CFG) == compile_claim(fixture(cid), CFG)
