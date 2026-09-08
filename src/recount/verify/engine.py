"""Verification engine: one fixed parameterized SQL template per plan kind.

Rendering rule (the closed world): each template is one constant below with three
kinds of slot (two constants for rankings: with and without a min_rows universe).
  * identifier slots ({t}, {col}, {dim}, {key}): double-quoted column names taken
    from the plan, which the loader validated against the dataset schema and which
    execute() re-checks against Dataset.columns before rendering;
  * keyword slots ({value}, {order}, {entity}): fixed fragments selected by Literal
    fields (SUM/COUNT/AVG, ASC/DESC, the optional entity clause, the ROUND wrapper);
  * bound parameters ($start, $end, $entity, $grain, $digits, $min_rows): every data-shaped
    value. Entity values and dates never touch SQL text.
Nothing derived from claim text or dataset contents is ever rendered into SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from recount.claims import Claim, Comparison, Growth, PointValue, Ranking, Share
from recount.compile import (
    Abstain,
    AggregatePlan,
    ComparePlan,
    ComputePlan,
    EntityFilter,
    GrowthPlan,
    Measure,
    RankPlan,
    SharePlan,
    TimeKey,
    compile_claim,
)
from recount.config import SemanticConfig
from recount.io import Dataset
from recount.verify import policies
from recount.verify.policies import PolicyResult, RankRow
from recount.verify.verdict import Param, Verdict

# ------------------------------------------------------------------ templates

AGGREGATE_SQL = """\
SELECT {value} AS value, COUNT(*) AS n_rows, COUNT({used}) AS n_used
FROM data
WHERE {t} >= $start AND {t} < $end{entity}"""

GROWTH_SQL = """\
WITH cur AS (SELECT {value} AS v, COUNT(*) AS n FROM data
             WHERE {t} >= $cur_start AND {t} < $cur_end{entity}),
     base AS (SELECT {value} AS v, COUNT(*) AS n FROM data
              WHERE {t} >= $base_start AND {t} < $base_end{entity})
SELECT cur.v AS current, base.v AS baseline,
       100.0 * (cur.v - base.v) / NULLIF(base.v, 0) AS pct_change,
       cur.n AS n_current, base.n AS n_baseline
FROM cur, base"""

COMPARE_SQL = """\
WITH cur AS (SELECT {value} AS v, COUNT(*) AS n FROM data
             WHERE {t} >= $cur_start AND {t} < $cur_end{entity}),
     base AS (SELECT {value} AS v, COUNT(*) AS n FROM data
              WHERE {t} >= $base_start AND {t} < $base_end{entity})
SELECT cur.v AS current, base.v AS baseline, cur.v - base.v AS diff,
       cur.n AS n_current, base.n AS n_baseline
FROM cur, base"""

RANK_SQL = """\
SELECT key, value, n_rows, n_used, RANK() OVER (ORDER BY value {order} NULLS LAST) AS rank
FROM (SELECT CAST({key} AS VARCHAR) AS key, {value} AS value,
             COUNT(*) AS n_rows, COUNT({used}) AS n_used
      FROM data
      WHERE {t} >= $start AND {t} < $end
      GROUP BY 1)
WHERE key IS NOT NULL
ORDER BY rank, key"""

# The same ranking with a minimum-support universe (metrics.<m>.min_rows, F-4): groups
# below the threshold are still returned, with their row count and a NULL rank, so a
# subject that fell out of the universe can be told apart from one the data never had
# (policies.check_ranking, abstention N5). A second constant rather than a slot in
# RANK_SQL, so that a config without min_rows executes byte-identical SQL to before.
RANK_MIN_ROWS_SQL = """\
SELECT key, value, n_rows, n_used,
       CASE WHEN supported
            THEN RANK() OVER (PARTITION BY supported ORDER BY value {order} NULLS LAST)
       END AS rank
FROM (SELECT CAST({key} AS VARCHAR) AS key, {value} AS value,
             COUNT(*) AS n_rows, COUNT({used}) AS n_used,
             COUNT(*) >= $min_rows AS supported
      FROM data
      WHERE {t} >= $start AND {t} < $end
      GROUP BY 1)
WHERE key IS NOT NULL
ORDER BY rank NULLS LAST, key"""

SHARE_SQL = """\
SELECT 100.0 * {part} / NULLIF({whole}, 0) AS share_pct,
       {part} AS part, {whole} AS whole, COUNT(*) AS n_rows
FROM data
WHERE {t} >= $start AND {t} < $end"""

_ENTITY_CLAUSE = " AND {dim} = $entity"
_TIME_KEY = "CAST(DATE_TRUNC($grain, {t}) AS DATE)"


class VerifyError(Exception):
    """A plan the engine cannot run: unknown column, or a claim/plan kind mismatch."""


@dataclass(frozen=True)
class Computed:
    sql: str
    params: dict[str, Param]
    row_counts: dict[str, int]
    values: dict[str, float | None] = field(default_factory=dict)
    rows: tuple[RankRow, ...] = ()


# ------------------------------------------------------------------ rendering


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _check_columns(ds: Dataset, *names: str | None) -> None:
    unknown = [n for n in names if n is not None and n not in ds.columns]
    if unknown:
        raise VerifyError(f"plan names columns not in the dataset: {unknown}")


def _measure_fragments(m: Measure, params: dict[str, Param]) -> tuple[str, str]:
    """-> (aggregate expression, expression COUNT() uses for n_used)."""
    if m.agg == "count":
        used = "*" if m.column is None else _ident(m.column)
        value = "COUNT(" + used + ")"
    else:
        assert m.column is not None  # enforced by Measure's validator
        used = _ident(m.column)
        value = m.agg.upper() + "(" + used + ")"
    if m.round is not None:
        value = "ROUND(" + value + ", $digits)"
        params["digits"] = m.round
    return value, used


def _entity_fragment(entity: EntityFilter | None, params: dict[str, Param]) -> str:
    if entity is None:
        return ""
    params["entity"] = entity.value
    return _ENTITY_CLAUSE.format(dim=_ident(entity.column))


def _float(x: Any) -> float | None:
    return None if x is None else float(x)


def _one_row(ds: Dataset, sql: str, params: dict[str, Param]) -> tuple[Any, ...]:
    row = ds.con.execute(sql, params).fetchone()
    if row is None:  # an aggregate without GROUP BY always yields one row
        raise VerifyError("template returned no row")
    return tuple(row)


# ------------------------------------------------------------------ execution


def execute(ds: Dataset, plan: ComputePlan) -> Computed:
    if isinstance(plan, AggregatePlan):
        return _aggregate(ds, plan)
    if isinstance(plan, GrowthPlan):
        return _two_period(ds, plan, GROWTH_SQL, "pct_change")
    if isinstance(plan, ComparePlan):
        return _two_period(ds, plan, COMPARE_SQL, "diff")
    if isinstance(plan, RankPlan):
        return _rank(ds, plan)
    return _share(ds, plan)


def _aggregate(ds: Dataset, plan: AggregatePlan) -> Computed:
    entity_col = plan.entity.column if plan.entity else None
    _check_columns(ds, plan.time_column, plan.measure.column, entity_col)
    params: dict[str, Param] = {"start": plan.period.start, "end": plan.period.end}
    value, used = _measure_fragments(plan.measure, params)
    sql = AGGREGATE_SQL.format(
        value=value,
        used=used,
        t=_ident(plan.time_column),
        entity=_entity_fragment(plan.entity, params),
    )
    v, n_rows, n_used = _one_row(ds, sql, params)
    return Computed(
        sql=sql,
        params=params,
        row_counts={"n_rows": int(n_rows), "n_used": int(n_used)},
        values={"value": _float(v)},
    )


def _two_period(
    ds: Dataset, plan: GrowthPlan | ComparePlan, template: str, change_name: str
) -> Computed:
    entity_col = plan.entity.column if plan.entity else None
    _check_columns(ds, plan.time_column, plan.measure.column, entity_col)
    params: dict[str, Param] = {
        "cur_start": plan.period.start,
        "cur_end": plan.period.end,
        "base_start": plan.baseline.start,
        "base_end": plan.baseline.end,
    }
    value, _ = _measure_fragments(plan.measure, params)
    sql = template.format(
        value=value, t=_ident(plan.time_column), entity=_entity_fragment(plan.entity, params)
    )
    current, baseline, change, n_cur, n_base = _one_row(ds, sql, params)
    return Computed(
        sql=sql,
        params=params,
        row_counts={"n_current": int(n_cur), "n_baseline": int(n_base)},
        values={
            "current": _float(current),
            "baseline": _float(baseline),
            change_name: _float(change),
        },
    )


def _rank(ds: Dataset, plan: RankPlan) -> Computed:
    key_col = None if isinstance(plan.group_by, TimeKey) else plan.group_by.column
    _check_columns(ds, plan.time_column, plan.measure.column, key_col)
    params: dict[str, Param] = {"start": plan.period.start, "end": plan.period.end}
    t = _ident(plan.time_column)
    if isinstance(plan.group_by, TimeKey):
        params["grain"] = plan.group_by.grain
        key = _TIME_KEY.format(t=t)
    else:
        key = _ident(plan.group_by.column)
    value, used = _measure_fragments(plan.measure, params)
    template = RANK_SQL
    if plan.min_rows is not None:
        template = RANK_MIN_ROWS_SQL
        params["min_rows"] = plan.min_rows
    sql = template.format(
        key=key, value=value, used=used, t=t, order="DESC" if plan.order == "desc" else "ASC"
    )
    raw = ds.con.execute(sql, params).fetchall()
    rows = tuple(
        RankRow(key=str(k), value=_float(v), rank=None if r is None else int(r), n_rows=int(n))
        for k, v, n, _, r in raw
    )
    n_rows = sum(int(n) for _, _, n, _, _ in raw)
    counts = {"n_rows": n_rows, "n_groups": sum(1 for r in rows if r.rank is not None)}
    if plan.min_rows is not None:  # the universe is smaller than the data: say by how much
        counts["n_groups_excluded"] = sum(1 for r in rows if r.rank is None)
    return Computed(sql=sql, params=params, row_counts=counts, rows=rows)


def _share(ds: Dataset, plan: SharePlan) -> Computed:
    _check_columns(ds, plan.time_column, plan.measure.column, plan.part.column)
    params: dict[str, Param] = {
        "start": plan.period.start,
        "end": plan.period.end,
        "entity": plan.part.value,
    }
    whole, _ = _measure_fragments(plan.measure, params)
    part = whole + " FILTER (WHERE " + _ident(plan.part.column) + " = $entity)"
    sql = SHARE_SQL.format(part=part, whole=whole, t=_ident(plan.time_column))
    share_pct, part_v, whole_v, n_rows = _one_row(ds, sql, params)
    return Computed(
        sql=sql,
        params=params,
        row_counts={"n_rows": int(n_rows)},
        values={"share_pct": _float(share_pct), "part": _float(part_v), "whole": _float(whole_v)},
    )


# ------------------------------------------------------------------ verdicts

_PAIRS: tuple[tuple[type, type], ...] = (
    (PointValue, AggregatePlan),
    (Growth, GrowthPlan),
    (Comparison, ComparePlan),
    (Ranking, RankPlan),
    (Share, SharePlan),
)


def verify(ds: Dataset, claim: Claim, plan: ComputePlan) -> Verdict:
    """Execute the plan's template, then apply the policy for the claim's type."""
    if not any(isinstance(claim, c) and isinstance(plan, p) for c, p in _PAIRS):
        raise VerifyError(
            f"claim type {claim.type!r} cannot be verified by plan kind {plan.kind!r}"
        )
    computed = execute(ds, plan)
    result = _apply_policy(claim, plan, computed)
    return Verdict(
        claim_id=claim.id,
        verdict=result.verdict,
        claimed_value=result.claimed_value,
        computed_value=result.computed_value,
        delta=result.delta,
        policy=result.policy,
        detail=result.detail,
        sql=computed.sql,
        params=computed.params,
        row_counts=computed.row_counts,
        abstain_reason=result.abstain_reason,
    )


def _apply_policy(claim: Claim, plan: ComputePlan, computed: Computed) -> PolicyResult:
    if isinstance(claim, PointValue):
        return policies.check_point_value(claim, computed.values["value"])
    if isinstance(claim, Growth):
        return policies.check_growth(claim, computed.values["pct_change"])
    if isinstance(claim, Comparison):
        assert isinstance(plan, ComparePlan)
        return policies.check_comparison(
            claim, computed.values["current"], computed.values["baseline"], plan.polarity
        )
    if isinstance(claim, Ranking):
        assert isinstance(plan, RankPlan)
        return policies.check_ranking(claim, plan.subject_key, computed.rows, plan.min_rows)
    return policies.check_share(claim, computed.values["share_pct"])


def verify_claim(ds: Dataset, claim: Claim, cfg: SemanticConfig) -> Verdict:
    """Compile, then verify. A compiler abstention becomes an UNVERIFIABLE verdict
    that executed nothing (empty sql/params/row_counts)."""
    plan = compile_claim(claim, cfg)
    if isinstance(plan, Abstain):
        claimed = float(claim.rank) if isinstance(claim, Ranking) else claim.value
        return Verdict(
            claim_id=claim.id,
            verdict="UNVERIFIABLE",
            claimed_value=claimed,
            computed_value=None,
            delta=None,
            policy="abstain",
            detail=plan.detail,
            sql="",
            params={},
            row_counts={},
            abstain_reason=plan.reason,
        )
    return verify(ds, claim, plan)
