"""Recount CLI. Stage 5 ships only `recount bench` (a Stage 6 preview: pyproject.toml
already names this module as the `recount` entry point); Stage 6 adds the rest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from recount.bench.corrupt import SEEDS, generate, write_suite
from recount.bench.runner import (
    BenchError,
    Paths,
    plan_calls,
    render_table,
    run_bench,
    write_readme,
)
from recount.config import load_config

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.callback()
def main() -> None:
    """Recount: deterministic verification of numeric claims in LLM-generated reports."""


def _seeds(text: str) -> tuple[int, ...]:
    return tuple(int(s) for s in text.split(",") if s.strip())


@app.command()
def bench(
    live: Annotated[
        bool, typer.Option(help="Make live calls for artifacts without a recording.")
    ] = False,
    seeds: Annotated[str, typer.Option(help="Comma-separated seeds.")] = ",".join(map(str, SEEDS)),
    out: Annotated[Path, typer.Option(help="Results JSON.")] = Path("bench/results/latest.json"),
    write_readme_table: Annotated[
        bool, typer.Option("--write-readme", help="Rewrite README between BENCH markers.")
    ] = False,
    recordings: Annotated[Path, typer.Option(help="Recorded responses directory.")] = Path(
        "bench/recordings"
    ),
    config: Annotated[
        Path, typer.Option(help="Semantic config the verifier runs with (F-3: an alias-on copy).")
    ] = Paths.config,
    rpm: Annotated[float, typer.Option(help="Live calls per minute (C6).")] = 10.0,
    model: Annotated[
        str | None, typer.Option(help="Live model for extractor AND judge (default: the pin).")
    ] = None,
    no_judge: Annotated[bool, typer.Option(help="Skip the judge baseline.")] = False,
    plan: Annotated[bool, typer.Option(help="Only print how many live calls a run needs.")] = False,
    dump_suite: Annotated[
        Path | None, typer.Option(help="Write every artifact and the manifest here.")
    ] = None,
) -> None:
    """Run the corruption benchmark (docs/benchmark.md)."""
    paths = Paths(recordings=recordings, config=config)
    seed_tuple = _seeds(seeds)
    if dump_suite is not None:
        cfg = load_config(paths.suite_config)
        labels = json.loads(paths.labels.read_text())["claims"]
        write_suite(
            generate(paths.clean.read_text(), labels, cfg, paths.dataset, seed_tuple), dump_suite
        )
        console.print(f"suite written to {dump_suite}")
    if plan:
        console.print(plan_calls(paths, seed_tuple))
        return
    client = None
    if live:
        from recount.extract import GeminiClient

        client = GeminiClient() if model is None else GeminiClient(model=model)
    previous = json.loads(out.read_text()) if out.exists() else None
    try:
        results = run_bench(
            paths, seeds=seed_tuple, live=client, rpm=rpm, with_judge=not no_judge,
            previous=previous, log=lambda s: console.print(f"[dim]{s}[/dim]"),
        )  # fmt: skip
    except BenchError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=2) from e
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    _print(results)
    if write_readme_table:
        write_readme(Path("README.md"), render_table(results))
        console.print("README.md updated")
    console.print(
        f"results: {out} · live calls {results['live_calls']} · replays {results['replays']}"
    )


def _print(results: dict[str, object]) -> None:
    table = Table(title="Recount benchmark")
    for col in (
        "class",
        "n",
        "claims",
        "detected",
        "by abstention",
        "false accept",
        "unextracted",
        "collateral",
        "judge det.",
        "judge FA",
    ):
        table.add_column(col)
    classes = results["classes"]
    assert isinstance(classes, dict)
    for name, r in classes.items():
        keys = (
            "n",
            "distinct_claims",
            "detected",
            "detected_by_abstention",
            "false_accept",
            "unextracted_total",
            "collateral_false_flags",
            "judge_detected",
            "judge_false_accept",
        )
        table.add_row(name, *(str(r[k]) for k in keys))  # fmt: skip
    console.print(table)
    if classes["exact_match"]["false_accept"]:
        console.print(
            "[bold red]FALSE ACCEPTS on exact-match classes: "
            "root-cause before anything else (Gate G4).[/bold red]"
        )


if __name__ == "__main__":
    app()
