"""Verdict reporters (deterministic zone): JSON run record, Rich table, static HTML."""

from recount.report.cli_table import render_markdown, render_table, summary_line
from recount.report.html import render_html
from recount.report.json_out import RunRecord, run_record

__all__ = [
    "RunRecord",
    "render_html",
    "render_markdown",
    "render_table",
    "run_record",
    "summary_line",
]
