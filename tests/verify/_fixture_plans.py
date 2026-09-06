"""TEST SCAFFOLDING ONLY: maps the hand-labeled fixture claims to ComputePlans.

Superseded by the Stage 3 compiler (src/recount/compile/compiler.py), which will do
alias resolution, period parsing and abstention properly. This module knows only
what the Olist fixture needs: "2017" and "2017-Qn" periods, state aliases from the
config, the five metric names and the quarter time grain. It never abstains: it
raises when it cannot build a plan, and the golden test lists those claims by hand.
Nothing under src/ may import this module (tests/architecture wall 3).
"""

from __future__ import annotations

from datetime import date

from recount.claims import Claim, Comparison, Growth, PointValue, Ranking
from recount.compile import (
    AggregatePlan,
    ComparePlan,
    ComputePlan,
    EntityFilter,
    EntityKey,
    GrowthPlan,
    Measure,
    Period,
    RankPlan,
    SharePlan,
    TimeKey,
)
from recount.config import SemanticConfig

YEAR = Period(start=date(2017, 1, 1), end=date(2018, 1, 1))
QUARTERS = {
    "2017-Q1": Period(start=date(2017, 1, 1), end=date(2017, 4, 1)),
    "2017-Q2": Period(start=date(2017, 4, 1), end=date(2017, 7, 1)),
    "2017-Q3": Period(start=date(2017, 7, 1), end=date(2017, 10, 1)),
    "2017-Q4": Period(start=date(2017, 10, 1), end=date(2018, 1, 1)),
}


def period(text: str | None) -> Period:
    if text == "2017":
        return YEAR
    if text in QUARTERS:
        return QUARTERS[text]
    raise ValueError(f"fixture scaffolding cannot parse period {text!r}")


def measure(cfg: SemanticConfig, name: str) -> Measure:
    m = cfg.metrics[name]
    agg = "count" if m.agg == "share" else m.agg
    return Measure(agg=agg, column=m.column, round=m.round)


def state_code(cfg: SemanticConfig, subject: str) -> str:
    return cfg.entities["state"].aliases[subject]


def entity(cfg: SemanticConfig, subject: str | None) -> EntityFilter | None:
    if subject is None:
        return None
    return EntityFilter(column=cfg.entities["state"].column, value=state_code(cfg, subject))


def plan_for(claim: Claim, cfg: SemanticConfig) -> ComputePlan:
    t = cfg.time_column
    m = measure(cfg, claim.metric)
    if isinstance(claim, PointValue):
        return AggregatePlan(
            time_column=t, measure=m, period=period(claim.period), entity=entity(cfg, claim.subject)
        )
    if isinstance(claim, Growth):
        return GrowthPlan(
            time_column=t,
            measure=m,
            period=period(claim.period),
            baseline=period(claim.baseline_period),
            entity=entity(cfg, claim.subject),
        )
    if isinstance(claim, Comparison):
        return ComparePlan(
            time_column=t,
            measure=m,
            period=period(claim.period),
            baseline=period(claim.baseline_period),
            entity=entity(cfg, claim.subject),
            polarity=cfg.metrics[claim.metric].polarity,
        )
    if isinstance(claim, Ranking):
        polarity = cfg.metrics[claim.metric].polarity
        assert polarity is not None, "ranking needs polarity"
        if claim.group_by == "quarter":
            return RankPlan(
                time_column=t,
                measure=m,
                period=period(claim.scope),
                group_by=TimeKey(grain="quarter"),
                subject_key=period(claim.period).start.isoformat(),
                polarity=polarity,
            )
        assert claim.subject is not None
        return RankPlan(
            time_column=t,
            measure=m,
            period=period(claim.period),
            group_by=EntityKey(column=cfg.entities[claim.group_by].column),
            subject_key=state_code(cfg, claim.subject),
            polarity=polarity,
        )
    part = entity(cfg, claim.subject)
    assert part is not None  # Share's validator requires a subject
    return SharePlan(time_column=t, measure=m, period=period(claim.period), part=part)
