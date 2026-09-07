"""`recount bench`: the keyless paths (plan, suite dump, missing recordings)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from recount.cli import app

runner = CliRunner()


def test_plan_and_dump_suite(tmp_path: Path) -> None:
    out = tmp_path / "suite"
    result = runner.invoke(app, ["bench", "--plan", "--seeds", "1", "--dump-suite", str(out)])
    assert result.exit_code == 0, result.output
    assert "'artifacts': 25" in result.output
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["variants"]) == 24 and (out / "clean.md").exists()
    assert (out / manifest["variants"][0]["variant_id"]).with_suffix(".md").exists()


def test_replay_without_recordings_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "bench",
            "--seeds",
            "1",
            "--recordings",
            str(tmp_path / "none"),
            "--out",
            str(tmp_path / "r.json"),
        ],
    )
    assert result.exit_code == 2
    assert "no extract recording" in result.output
