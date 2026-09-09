"""The compiler: (Claim, SemanticConfig) -> ComputePlan | Abstain.

The specification is docs/abstention.md; every branch below cites its row id and
the code must match the table exactly. When the table has no row for a situation
the compiler abstains rather than guesses. Deterministic and pure: it reads the
claim's typed fields, resolves everything through the config, and never touches the
dataset or the clock. `span` is read for exactly one check, the metric echo (M3,
Stage 6): it is verbatim artifact text that the extractor validated, the door
changelog 2 opened for `stated_decimals`. No LLM (wall 1), no SQL (wall 2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from recount.claims import AbstainReason, Claim, Comparison, Growth, PointValue, Ranking, Share
from recount.compile.periods import Grain, PeriodError, parse_period, unit_grain
from recount.compile.plans import (
    AggregatePlan,
    ComparePlan,
    ComputePlan,
    EntityFilter,
    EntityKey,
    GrowthPlan,
    Measure,
    Period,
    Polarity,
    RankPlan,
    SharePlan,
    TimeKey,
)
from recount.config import Metric, SemanticConfig, entity_index, metric_index, norm

_AMBIGUOUS = AbstainReason.AMBIGUOUS
_SCHEMA_GAP = AbstainReason.SCHEMA_GAP
_UNSUPPORTED = AbstainReason.UNSUPPORTED_CLAIM_TYPE
_NO_DATA = AbstainReason.NO_DATA

_GRAINS: dict[str, TimeKey] = {
    "month": TimeKey(grain="month"),
    "quarter": TimeKey(grain="quarter"),
    "year": TimeKey(grain="year"),
}


@dataclass(frozen=True)
class Abstain:
    reason: AbstainReason
    detail: str


def compile_claim(claim: Claim, cfg: SemanticConfig) -> ComputePlan | Abstain:
    plan = _compile(claim, cfg)
    if isinstance(plan, Abstain):
        return plan
    # M3 — the echo gate, last before a plan leaves: the span must name the metric the
    # claim bound to (F-2). Evaluated last so an abstention for any other reason keeps
    # the more specific diagnostic.
    name = metric_index(cfg)[norm(claim.metric)]
    if not _echoes(claim, cfg, name):
        return Abstain(
            _SCHEMA_GAP,
            f"metric_echo_failed: nothing in the span resolves to '{name}' (bound from metric"
            f" '{claim.metric}'); if the span's wording means '{name}', add that wording"
            f" under metrics.{name}.aliases:\n    aliases: [..., <the span's wording>]",
        )
    return plan


def _compile(claim: Claim, cfg: SemanticConfig) -> ComputePlan | Abstain:
    # M1 / M2 — metric first: a schema gap is the abstention the user can fix in YAML.
    name = metric_index(cfg).get(norm(claim.metric))
    if name is None:
        return Abstain(
            _SCHEMA_GAP,
            f"unknown metric '{claim.metric}'; names and aliases are matched in full after"
            f" normalisation, never as a substring, so a prefixed wording needs its own"
            f" alias. Config metrics: {', '.join(cfg.metrics)}. To fix, add under the one"
            f' this means:\n    aliases: [..., "{claim.metric}"]',
        )
    metric = cfg.metrics[name]
    if isinstance(claim, Ranking):
        return _ranking(claim, cfg, name, metric)

    entity = _entity(claim.subject, cfg)  # E1, E2, E4
    if isinstance(entity, Abstain):
        return entity

    # X — claim type vs metric kind
    if isinstance(claim, Share):
        if metric.agg == "avg":  # X2
            return Abstain(_AMBIGUOUS, "a share of an average is not defined")
    elif metric.agg == "share":
        if isinstance(claim, PointValue):  # X3
            return Abstain(
                _UNSUPPORTED,
                f"'{name}' is a share; a point_value claim cannot carry a share"
                " (the engine pairs point_value with aggregate plans)",
            )
        return Abstain(  # X4
            _UNSUPPORTED,
            "growth/comparison of a share is not supported; compiling it would silently"
            " compute the count, not the share",
        )

    # D — comparison direction and polarity
    if isinstance(claim, Comparison):
        if claim.direction == "unchanged":  # D1
            return Abstain(_AMBIGUOUS, "'unchanged' has no threshold")
        if claim.direction in ("better", "worse") and metric.polarity is None:  # D2, BINDING (a)
            return Abstain(_SCHEMA_GAP, f"'{claim.direction}' needs metrics.{name}.polarity")

    # V1–V5 — stated value and baseline presence
    if isinstance(claim, PointValue) and claim.value is None:  # V1
        return Abstain(
            _AMBIGUOUS, f"no stated value; '{claim.metric}' is asserted without a number"
        )
    if isinstance(claim, Share) and claim.value is None:  # V2
        return Abstain(_AMBIGUOUS, "no stated share")
    if isinstance(claim, Growth) and claim.value is None:  # V3
        return Abstain(_AMBIGUOUS, "no stated growth magnitude")
    if isinstance(claim, Growth | Comparison) and claim.baseline_period is None:  # V5
        return Abstain(
            _AMBIGUOUS,
            f"no baseline period: '{claim.metric}' in {claim.period} is compared against what?",
        )

    # P — periods
    period = _period("period", claim.period)  # P1–P8
    if isinstance(period, Abstain):
        return period
    measure = _measure(metric)
    t = cfg.time_column
    if isinstance(claim, PointValue):
        return AggregatePlan(time_column=t, measure=measure, period=period, entity=entity)
    if isinstance(claim, Share):
        assert entity is not None  # Share requires a subject at the schema level
        return SharePlan(time_column=t, measure=measure, period=period, part=entity)  # X1

    assert claim.baseline_period is not None  # V5 above
    baseline = _period("baseline period", claim.baseline_period)  # P9
    if isinstance(baseline, Abstain):
        return baseline
    if baseline.start >= period.start:  # V6 (authored by the project owner)
        return Abstain(
            _AMBIGUOUS,
            f"baseline '{claim.baseline_period}' does not precede period '{claim.period}';"
            " growth and comparison run backwards in time",
        )
    # P11: an overlapping-but-earlier baseline is a defined computation.
    if isinstance(claim, Growth):
        return GrowthPlan(
            time_column=t, measure=measure, period=period, baseline=baseline, entity=entity
        )
    return ComparePlan(  # D3 (better/worse with polarity), D4 (higher/lower), V4 (direction-only)
        time_column=t,
        measure=measure,
        period=period,
        baseline=baseline,
        entity=entity,
        polarity=metric.polarity,
    )


def _ranking(
    claim: Ranking, cfg: SemanticConfig, name: str, metric: Metric
) -> ComputePlan | Abstain:
    # G1 — a time grain resolves from time_column, never from entities (BINDING b).
    grain: Grain | None = None
    group_by = norm(claim.group_by)
    subject_key: str
    if group_by in _GRAINS:
        key: EntityKey | TimeKey = _GRAINS[group_by]
        grain = _GRAINS[group_by].grain
        if claim.subject is not None:  # G6
            return Abstain(
                _UNSUPPORTED,
                f"ranking {grain}s within an entity is not supported; RankPlan has no entity scope",
            )
        if grain == "year":  # G7 — stopgap for partial-year coverage until the P12 runtime check
            return Abstain(
                _NO_DATA,
                "ranking years is withheld: a partly covered year would rank against full ones",
            )
    else:
        dims = {norm(d): d for d in cfg.entities}
        dim = dims.get(group_by)
        if dim is None:  # G3
            return Abstain(
                _SCHEMA_GAP,
                f"group_by '{claim.group_by}' is neither an entities dimension"
                f" ({', '.join(cfg.entities)}) nor a time grain (month, quarter, year)",
            )
        key = EntityKey(column=cfg.entities[dim].column)  # G2
        if claim.subject is None:  # G4
            return Abstain(_AMBIGUOUS, f"ranking needs a subject: who holds rank {claim.rank}?")
        resolved = entity_index(cfg).get(norm(claim.subject))
        if resolved is None or resolved[0] != dim:  # G5
            return Abstain(
                _SCHEMA_GAP,
                f"'{claim.subject}' is not a '{claim.group_by}' alias; add it under"
                f' entities.{dim}.aliases:\n    aliases:\n      "{claim.subject}":'
                " <the value stored in that column>",
            )
        subject_key = resolved[1]
    if claim.rank_from is None:  # G12 — the sentence's end, never guessed from the config
        return Abstain(
            _AMBIGUOUS,
            f"no rank direction: is rank {claim.rank} the highest or the lowest '{name}'?",
        )
    if claim.rank_from in ("best", "worst") and metric.polarity is None:  # G9
        return Abstain(
            _SCHEMA_GAP,
            f"ranking '{name}' from the {claim.rank_from} end needs polarity (which way is"
            f" better); set metrics.{name}.polarity",
        )
    order = _order(claim.rank_from, metric.polarity)
    if claim.displaced is not None:  # G10 — precise sentence, missing capability
        return Abstain(
            _UNSUPPORTED,
            f"'displaced {claim.displaced}' asserts an overtaking, a rank change between two"
            " periods; rank-change verification is not supported",
        )
    period = _period("period", claim.period)  # P1–P8
    if isinstance(period, Abstain):
        return period
    measure = _measure(metric)  # X5: a share metric ranks by the row count
    if grain is None:
        if claim.scope is not None:  # G11
            return Abstain(
                _AMBIGUOUS,
                f"the span restricts the ranking universe to '{claim.scope}'; Recount ranks"
                f" every {claim.group_by} in period '{claim.period}' (minus any below"
                f" metrics.{name}.min_rows) and cannot resolve '{claim.scope}'",
            )
        return RankPlan(
            time_column=cfg.time_column,
            measure=measure,
            period=period,
            group_by=key,
            subject_key=subject_key,
            order=order,
            min_rows=metric.min_rows,
        )
    # G8 — the period is one unit of the grain; scope is the universe and must contain it.
    if unit_grain(period) != grain:
        return Abstain(
            _AMBIGUOUS,
            f"period '{claim.period}' is not a single {grain};"
            f" which {grain} holds rank {claim.rank}?",
        )
    if claim.scope is None:
        return Abstain(_AMBIGUOUS, f"no scope stated: rank {claim.rank} among which {grain}s?")
    scope = _period("scope", claim.scope)  # P9
    if isinstance(scope, Abstain):
        return scope
    if period.start < scope.start or scope.end < period.end:
        return Abstain(_AMBIGUOUS, f"period '{claim.period}' lies outside scope '{claim.scope}'")
    return RankPlan(
        time_column=cfg.time_column,
        measure=measure,
        period=scope,
        group_by=key,
        subject_key=period.start.isoformat(),
        order=order,
        min_rows=metric.min_rows,
    )


def _order(
    rank_from: Literal["highest", "lowest", "best", "worst"], polarity: Polarity | None
) -> Literal["asc", "desc"]:
    """Which end rank 1 counts from (G9/G12). 'highest'/'lowest' name the numeric end;
    'best'/'worst' are quality wording and resolve through polarity, which G9 has already
    required to be present."""
    if rank_from in ("highest", "lowest"):
        return "desc" if rank_from == "highest" else "asc"
    assert polarity is not None  # G9
    best_end: Literal["asc", "desc"] = "desc" if polarity == "higher_is_better" else "asc"
    if rank_from == "best":
        return best_end
    return "asc" if best_end == "desc" else "desc"


def _echoes(claim: Claim, cfg: SemanticConfig, name: str) -> bool:
    """M3: does the span contain, as whole words after norm(), a name or alias of the
    metric the claim bound to? The extractor can bind a rewritten metric ("average return
    time") to a real one from context (F-2, two false accepts); the config vocabulary is the
    only thing that may turn wording into a metric, so unknown wording abstains. A share
    span may instead name a row-count metric (agg count, no column): that is the share's
    denominator by C5 ("13.74% of total orders")."""
    text = norm(claim.span)
    wanted = {name}
    if isinstance(claim, Share):
        wanted |= {n for n, m in cfg.metrics.items() if m.agg == "count" and m.column is None}
    return any(
        re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text)
        for alias, owner in metric_index(cfg).items()
        if owner in wanted
    )


def _entity(subject: str | None, cfg: SemanticConfig) -> EntityFilter | None | Abstain:
    if subject is None:  # E1 — the whole dataset in the period
        return None
    resolved = entity_index(cfg).get(
        norm(subject)
    )  # E2 — alias keys and stored values, config only
    if resolved is None:  # E4
        return Abstain(
            _SCHEMA_GAP,
            f"unknown entity '{subject}'; aliases are matched in full after normalisation."
            f" To fix, add under the dimension it belongs to:\n    aliases:\n"
            f'      "{subject}": <the value stored in that column>',
        )
    dim, value = resolved
    return EntityFilter(column=cfg.entities[dim].column, value=value)


def _period(field: str, text: str | None) -> Period | Abstain:
    if text is None:  # P6 / P9
        return Abstain(
            _AMBIGUOUS, f"no {field} stated; the compiler never assumes the whole dataset"
        )
    try:
        return parse_period(text)
    except PeriodError as e:  # P7 / P8
        return Abstain(_AMBIGUOUS, f"{field}: {e}" if field != "period" else str(e))


def _measure(metric: Metric) -> Measure:
    if metric.agg == "share":  # X1 / X5 — a share is a share of the period's row count (C5)
        return Measure(agg="count", column=None, round=metric.round)
    return Measure(agg=metric.agg, column=metric.column, round=metric.round)
