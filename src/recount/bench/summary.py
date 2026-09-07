"""The judge's data summary (docs/benchmark.md J2–J4): deterministic aggregate tables
computed by fixed SQL over the loaded dataset and rendered as Markdown.

This is the one place where values derived from the dataset are prepared for a prompt,
and only `bench/baseline_judge.py` may send them (CLAUDE.md §0, the eval-only exception).
Group keys are cell values, so an injected instruction (B8) shows up here on purpose.
No raw rows are ever included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from recount.config import Metric, SemanticConfig
from recount.io import Dataset

NATIONAL_SQL = "SELECT {exprs}COUNT(*) AS n_rows FROM data"
PERIOD_SQL = (
    "SELECT CAST(DATE_TRUNC('quarter', {t}) AS DATE) AS period, {exprs}COUNT(*) AS n_rows "
    "FROM data GROUP BY 1 ORDER BY 1"
)
GROUP_SQL = (
    "SELECT CAST({dim} AS VARCHAR) AS key, {exprs}COUNT(*) AS n_rows "
    "FROM data GROUP BY 1 ORDER BY 1"
)

DEFAULT_DECIMALS = 4


@dataclass(frozen=True)
class Column:
    name: str
    metric: Metric


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _measures(cfg: SemanticConfig) -> list[Column]:
    return [Column(n, m) for n, m in cfg.metrics.items() if m.agg != "share"]


def _shares(cfg: SemanticConfig) -> list[str]:
    return [n for n, m in cfg.metrics.items() if m.agg == "share"]


def _expr(col: Column) -> str:
    m = col.metric
    if m.agg == "count":
        inner = "COUNT(*)" if m.column is None else "COUNT(" + _ident(m.column) + ")"
    else:
        assert m.column is not None  # enforced by Metric's validator
        inner = m.agg.upper() + "(" + _ident(m.column) + ")"
    return inner + " AS " + _ident(col.name) + ", "


def _fmt(value: Any, col: Column | None = None) -> str:
    if value is None:
        return "null"
    if col is not None and col.metric.agg == "count":
        return str(int(value))
    d = DEFAULT_DECIMALS if col is None or col.metric.round is None else col.metric.round
    return f"{float(value):.{d}f}"


def _rows(ds: Dataset, sql: str) -> list[dict[str, Any]]:
    cur = ds.con.execute(sql)
    names = [str(d[0]) for d in cur.description or []]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def _ranks(rows: list[dict[str, Any]], col: Column) -> dict[str, int]:
    """RANK() semantics (ties share a rank), rank 1 = best by the metric's polarity."""
    if col.metric.polarity is None:
        return {}
    keyed = [(r["key"], r[col.name]) for r in rows if r[col.name] is not None]
    reverse = col.metric.polarity == "higher_is_better"
    ordered = sorted(keyed, key=lambda kv: kv[1], reverse=reverse)
    ranks: dict[str, int] = {}
    for i, (key, value) in enumerate(ordered):
        ranks[key] = ranks[ordered[i - 1][0]] if i and value == ordered[i - 1][1] else i + 1
    return ranks


def _table(header: list[str], body: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def summarize(ds: Dataset, cfg: SemanticConfig) -> str:
    measures = _measures(cfg)
    shares = _shares(cfg)
    exprs = "".join(_expr(c) for c in measures)
    t = _ident(cfg.time_column)
    parts: list[str] = []

    national = _rows(ds, NATIONAL_SQL.format(exprs=exprs))[0]
    parts.append("### Whole dataset\n\n" + _table(
        [c.name for c in measures] + ["rows"],
        [[_fmt(national[c.name], c) for c in measures] + [str(national["n_rows"])]],
    ))  # fmt: skip

    periods = _rows(ds, PERIOD_SQL.format(t=t, exprs=exprs))
    growable = [c for c in measures if c.metric.agg in ("sum", "count")]
    header = ["quarter starting"] + [c.name for c in measures]
    header += [c.name + " change vs previous quarter (%)" for c in growable] + ["rows"]
    body: list[list[str]] = []
    for i, r in enumerate(periods):
        row = [str(r["period"])] + [_fmt(r[c.name], c) for c in measures]
        for c in growable:
            if i == 0 or not periods[i - 1][c.name]:
                row.append("n/a")
            else:
                base = float(periods[i - 1][c.name])
                row.append(_fmt(100.0 * (float(r[c.name]) - base) / base))
        row.append(str(r["n_rows"]))
        body.append(row)
    parts.append("### By quarter\n\n" + _table(header, body))

    for dim_name, dim in cfg.entities.items():
        rows = _rows(ds, GROUP_SQL.format(dim=_ident(dim.column), exprs=exprs))
        total = sum(int(r["n_rows"]) for r in rows)
        ranks = {c.name: _ranks(rows, c) for c in measures}
        header = [dim_name] + [c.name for c in measures] + [s + " (%)" for s in shares]
        header += ["rank by " + c.name for c in measures if c.metric.polarity] + ["rows"]
        body = []
        for r in rows:
            row = [str(r["key"])] + [_fmt(r[c.name], c) for c in measures]
            row += [_fmt(100.0 * int(r["n_rows"]) / total) for _ in shares]
            row += [str(ranks[c.name].get(r["key"], "")) for c in measures if c.metric.polarity]
            row.append(str(r["n_rows"]))
            body.append(row)
        aliases = ", ".join(f"{k} = {v}" for k, v in dim.aliases.items())
        parts.append(f"### By {dim_name} (all values; names: {aliases})\n\n" + _table(header, body))

    return "\n\n".join(parts) + "\n"
