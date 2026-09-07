"""`recount init --data`: infers columns, writes a commented template the loader accepts,
never overwrites silently."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from recount.cli import app
from recount.config import load_config
from recount.io import load_dataset

DATA = Path("examples/olist/orders.parquet")
CONFIG = Path("examples/olist/metrics.yml")
REPORT = Path("spike/report_clean.md")  # = examples/olist/report.md on main
RECORDINGS = Path("bench/recordings/extract")
runner = CliRunner()


def test_init_writes_a_loadable_template(tmp_path: Path) -> None:
    out = tmp_path / "metrics.yml"
    r = runner.invoke(app, ["init", "--data", str(DATA), "--out", str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert "time_column: order_date" in text
    assert "order_id" not in text.split("entities:")[1].split("metrics:")[0]  # ids are keys
    assert "  state:\n    column: state" in text
    assert "avg_delivery_days:" in text and "total_revenue:" in text
    cfg = load_config(out)  # the template is valid as written
    assert load_dataset(DATA, cfg).n_rows == 43428
    # refuses to overwrite without --force
    r = runner.invoke(app, ["init", "--data", str(DATA), "--out", str(out)])
    assert r.exit_code == 2 and "exists" in r.output
    r = runner.invoke(app, ["init", "--data", str(DATA), "--out", str(out), "--force",
                            "--time-column", "order_date"])  # fmt: skip
    assert r.exit_code == 0


def test_init_on_a_missing_or_odd_file_exits_2(tmp_path: Path) -> None:
    r = runner.invoke(app, ["init", "--data", "nope.parquet", "--out", str(tmp_path / "m.yml")])
    assert r.exit_code == 2 and "dataset not found" in r.output
    odd = tmp_path / "x.txt"
    odd.write_text("a,b\n1,2\n")
    r = runner.invoke(app, ["init", "--data", str(odd), "--out", str(tmp_path / "m.yml")])
    assert r.exit_code == 2 and "unsupported dataset format" in r.output
