"""The verdict table for the terminal (Rich) and for Markdown (PR summaries), with the same
column order and verdict colours as the HTML: green PASS, red FAIL, amber UNVERIFIABLE."""

from __future__ import annotations

from rich.table import Table

from recount.report.json_out import RunRecord

COLOURS = {"PASS": "green", "FAIL": "red", "UNVERIFIABLE": "yellow"}
COLUMNS = ("id", "verdict", "claim", "claimed", "computed", "delta", "policy", "detail")


def _num(x: float | None) -> str:
    return "" if x is None else f"{x:,.4f}".rstrip("0").rstrip(".")


def _rows(rec: RunRecord) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for claim, v in zip(rec.claims, rec.verdicts, strict=True):
        out.append(
            (
                claim.id,
                v.verdict,
                claim.span,
                _num(v.claimed_value),
                _num(v.computed_value),
                _num(v.delta),
                v.policy if v.abstain_reason is None else str(v.abstain_reason),
                v.detail,
            )
        )
    return out


def summary_line(rec: RunRecord) -> str:
    c = rec.counts
    parts = [f"{c['PASS']} PASS", f"{c['FAIL']} FAIL", f"{c['UNVERIFIABLE']} UNVERIFIABLE"]
    if c["unextracted_numeric"]:
        parts.append(f"{c['unextracted_numeric']} unextracted numeric")
    if c["rejected"]:
        parts.append(f"{c['rejected']} rejected")
    return " · ".join(parts)


def render_table(rec: RunRecord) -> Table:
    table = Table(title="Recount verdicts", show_lines=False)
    for col in COLUMNS:
        table.add_column(col, overflow="fold", max_width=48 if col in ("claim", "detail") else None)
    for row in _rows(rec):
        colour = COLOURS[row[1]]
        table.add_row(*row, style=colour if row[1] == "FAIL" else None)
    return table


def render_markdown(rec: RunRecord, title: str = "Recount verdicts") -> str:
    """The same table as GitHub-flavoured Markdown (the Action's job summary)."""
    icon = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "UNVERIFIABLE": "⚠️ UNVERIFIABLE"}
    lines = [
        f"### {title}",
        "",
        f"**{summary_line(rec)}** · exit code {rec.exit_code()}",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    for row in _rows(rec):
        cells = [icon[row[1]] if i == 1 else c.replace("|", "\\|") for i, c in enumerate(row)]
        lines.append("| " + " | ".join(cells) + " |")
    if rec.extraction.unextracted_numeric:
        toks = ", ".join(f"`{t.context}`" for t in rec.extraction.unextracted_numeric)
        lines += ["", f"Unextracted numerics (no claim verifies them): {toks}"]
    if rec.extraction.rejected:
        lines += ["", "Rejected wire objects: " + ", ".join(
            f"`{r.reason}`" for r in rec.extraction.rejected
        )]  # fmt: skip
    return "\n".join(lines) + "\n"
