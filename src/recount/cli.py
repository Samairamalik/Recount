"""Recount CLI: `verify`, `init`, `bench`.

Exit-code contract (docs/cli.md):
  0  every checked claim PASSed (UNVERIFIABLE and unextracted numerics are reported, not
     fatal, unless --strict)
  1  at least one FAIL; with --strict also any UNVERIFIABLE or unextracted numeric
  2  system error: artifact empty or over the size cap, dataset unreadable or not matching
     the config, config invalid (YAML line cited), extraction invalid twice (raw output
     saved), a claim that crashed the engine (partial results are still written)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError
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
from recount.config.template import metrics_template
from recount.extract import ExtractError
from recount.io import LoadError, describe_dataset
from recount.pipeline import ArtifactError, PartialFailure, verify_text
from recount.report import render_html, render_markdown, run_record, summary_line
from recount.report import render_table as verdict_table
from recount.report.json_out import RunRecord

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2
DOCS = "https://github.com/Samairamalik/Recount/blob/main/docs/cli.md"

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.callback()
def main() -> None:
    """Recount: deterministic verification of numeric claims in LLM-generated reports."""


# ------------------------------------------------------------------ verify


def _config_error(path: Path, e: Exception) -> str:
    """One actionable sentence with a YAML line reference (docs/cli.md, exit 2)."""
    if isinstance(e, yaml.YAMLError):
        mark = getattr(e, "problem_mark", None)
        at = f" at line {mark.line + 1}" if mark is not None else ""
        return f"config {path} is not valid YAML{at}: {getattr(e, 'problem', e)}"
    if isinstance(e, ValidationError):
        lines = path.read_text().splitlines()
        parts = []
        for err in e.errors()[:3]:
            loc = [str(x) for x in err["loc"]]
            key = next((x for x in reversed(loc) if not x.isdigit()), None)
            line = next(
                (
                    i
                    for i, ln in enumerate(lines, 1)
                    if key and re.match(rf"\s*{re.escape(key)}:", ln)
                ),
                None,
            )
            at = f" (line {line})" if line else ""
            parts.append(f"{'.'.join(loc)}{at}: {err['msg']}")
        return f"config {path} is invalid: " + "; ".join(parts)
    return f"config {path}: {e}"


def _annotations(rec: RunRecord) -> list[str]:
    """GitHub workflow commands, one per FAIL (error) and UNVERIFIABLE (notice), with the
    line of the span in the artifact; unextracted numerics are warnings under --strict."""
    out = []
    for claim, v in zip(rec.claims, rec.verdicts, strict=True):
        if v.verdict == "PASS":
            continue
        i = rec.artifact.find(claim.span)
        line = rec.artifact.count("\n", 0, max(i, 0)) + 1
        level = "error" if v.verdict == "FAIL" else "notice"
        msg = f"{claim.id} {v.verdict}: {claim.span!r} — {v.detail}".replace("\n", " ")
        out.append(
            f"::{level} file={rec.artifact_path},line={line},title=Recount {v.verdict}::{msg}"
        )
    if rec.strict:
        for t in rec.extraction.unextracted_numeric:
            line = rec.artifact.count("\n", 0, t.start) + 1
            out.append(
                f"::warning file={rec.artifact_path},line={line},title=Recount unextracted::"
                f"no claim verifies {t.context!r}"
            )
    return out


def _emit(rec: RunRecord, *, json_out: Path | None, html_out: Path | None, md_out: Path | None,
          annotations: bool, quiet: bool) -> None:  # fmt: skip
    record = run_record(rec)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    if html_out is not None:
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(render_html(rec, record))
    if md_out is not None:
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(render_markdown(rec))
    if not quiet:
        console.print(verdict_table(rec))
        console.print(summary_line(rec))
        for t in rec.extraction.unextracted_numeric:
            console.print(f"[dim]unextracted numeric: {t.context!r}[/dim]")
        if rec.claims == () and rec.extraction.unextracted_numeric:
            console.print(
                "[yellow]no claims were extracted but the report contains numbers:"
                " is this report about this data?[/yellow]"
            )
    if annotations:
        for line in _annotations(rec):
            print(line)


@app.command()
def verify(
    artifact: Annotated[Path, typer.Argument(help="The report (Markdown or plain text).")],
    data: Annotated[Path, typer.Option(help="Dataset: .parquet or .csv.")],
    config: Annotated[Path, typer.Option(help="Semantic config (metrics.yml).")],
    json_out: Annotated[Path | None, typer.Option("--json", help="Write the run record.")] = None,
    html_out: Annotated[
        Path | None, typer.Option("--html", help="Write the annotated HTML.")
    ] = None,
    md_out: Annotated[
        Path | None, typer.Option("--md", help="Write the verdict table as Markdown.")
    ] = None,
    strict: Annotated[
        bool, typer.Option(help="Also fail on UNVERIFIABLE or an unextracted numeric.")
    ] = False,
    claims: Annotated[
        Path | None, typer.Option(help="Pre-extracted claims JSON: fully offline.")
    ] = None,
    recording: Annotated[
        Path | None, typer.Option(help="Replay a recorded extraction (keyless).")
    ] = None,
    recordings: Annotated[
        Path | None, typer.Option(help="Directory of recordings keyed by artifact sha256[:16].")
    ] = None,
    model: Annotated[
        str | None, typer.Option(help="Live extractor model (default: the pin).")
    ] = None,
    annotations: Annotated[
        bool, typer.Option(help="Print GitHub workflow-command annotations per verdict.")
    ] = False,
    quiet: Annotated[bool, typer.Option(help="No table on stdout.")] = False,
) -> None:
    """Verify every numeric claim in ARTIFACT against DATA under CONFIG."""
    try:
        text = artifact.read_text()
    except OSError as e:
        console.print(f"[red]cannot read artifact: {e}[/red] · {DOCS}")
        raise typer.Exit(code=EXIT_ERROR) from e
    raw_dump = artifact.with_suffix(artifact.suffix + ".raw.txt")
    try:
        rec = verify_text(
            text, data=data, config=config, strict=strict, claims=claims, recording=recording,
            recordings=recordings, model=model, raw_dump=raw_dump, artifact_path=str(artifact),
        )  # fmt: skip
    except ArtifactError as e:
        console.print(f"[red]{e}[/red] · {DOCS}#exit-codes")
        raise typer.Exit(code=EXIT_ERROR) from e
    except (yaml.YAMLError, ValidationError) as e:
        console.print(f"[red]{_config_error(config, e)}[/red] · {DOCS}#config")
        raise typer.Exit(code=EXIT_ERROR) from e
    except LoadError as e:
        console.print(f"[red]{e}[/red] · {DOCS}#dataset")
        raise typer.Exit(code=EXIT_ERROR) from e
    except (ExtractError, FileNotFoundError) as e:
        saved = f" (raw output saved to {raw_dump})" if raw_dump.exists() else ""
        console.print(f"[red]extraction failed: {e}{saved}[/red] · {DOCS}#extraction")
        raise typer.Exit(code=EXIT_ERROR) from e
    except PartialFailure as e:
        _emit(e.record, json_out=json_out, html_out=html_out, md_out=md_out,
              annotations=annotations, quiet=quiet)  # fmt: skip
        console.print(f"[red]{len(e.errors)} claim(s) crashed the engine: {e}[/red] · {DOCS}")
        raise typer.Exit(code=EXIT_ERROR) from e
    _emit(rec, json_out=json_out, html_out=html_out, md_out=md_out, annotations=annotations,
          quiet=quiet)  # fmt: skip
    raise typer.Exit(code=rec.exit_code())


# ------------------------------------------------------------------ init


@app.command()
def init(
    data: Annotated[Path, typer.Option(help="Dataset: .parquet or .csv.")],
    out: Annotated[Path, typer.Option(help="Where to write the template.")] = Path("metrics.yml"),
    time_column: Annotated[
        str | None, typer.Option(help="Override the inferred DATE/TIMESTAMP column.")
    ] = None,
    force: Annotated[bool, typer.Option(help="Overwrite an existing file.")] = False,
) -> None:
    """Infer columns and types from DATA and write a commented metrics.yml to edit."""
    if out.exists() and not force:
        console.print(f"[red]{out} exists; pass --force to overwrite[/red]")
        raise typer.Exit(code=EXIT_ERROR)
    try:
        columns = describe_dataset(data)
    except LoadError as e:
        console.print(f"[red]{e}[/red] · {DOCS}#dataset")
        raise typer.Exit(code=EXIT_ERROR) from e
    out.write_text(metrics_template(str(data), columns, time_column))
    console.print(
        f"wrote {out}: {len(columns)} columns; edit the aliases, then run `recount verify`"
    )


# ------------------------------------------------------------------ bench


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
