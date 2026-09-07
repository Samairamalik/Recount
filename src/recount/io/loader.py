"""Dataset loader: CSV/Parquet -> a DuckDB relation named `data`, validated against the config.

The file path goes through the DuckDB Python API, never into SQL text (CREATE VIEW
cannot take a bound parameter). Schema validation lives here so that every column
name a ComputePlan carries is known to exist with a usable type before any template
is rendered. Dataset contents are never read by this module beyond COUNT(*).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from recount.config import SemanticConfig

TABLE = "data"
MAX_BYTES = 1 << 30  # 1 GiB
MAX_ROWS = 100_000_000  # DuckDB single-node comfort zone (spec §2.5)

_TIME_TYPES = ("DATE", "TIMESTAMP")
_NUMERIC_TYPES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "UHUGEINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
)


class LoadError(Exception):
    """The dataset cannot be used with this config (missing/mistyped columns, caps)."""


@dataclass(frozen=True)
class Dataset:
    """A connection on which `data` is registered and validated against the config."""

    con: duckdb.DuckDBPyConnection
    columns: dict[str, str]  # column name -> DuckDB type, as reported by the engine
    n_rows: int


def load_dataset(
    path: Path,
    config: SemanticConfig,
    *,
    max_bytes: int = MAX_BYTES,
    max_rows: int = MAX_ROWS,
) -> Dataset:
    if not path.is_file():
        raise LoadError(f"dataset not found: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise LoadError(f"dataset is {size} bytes; cap is {max_bytes}")
    con = duckdb.connect()
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        rel = con.read_parquet(str(path))
    elif suffix == ".csv":
        rel = con.read_csv(str(path))
    else:
        raise LoadError(f"unsupported dataset format {suffix!r}; use .csv or .parquet")
    con.register(TABLE, rel)
    return attach(con, config, max_rows=max_rows)


def describe_dataset(path: Path) -> dict[str, str]:
    """Column name -> DuckDB type, for `recount init`. Same readers and caps as
    `load_dataset`; no config needed and no contents read beyond the schema."""
    if not path.is_file():
        raise LoadError(f"dataset not found: {path}")
    con = duckdb.connect()
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        rel = con.read_parquet(str(path))
    elif suffix == ".csv":
        rel = con.read_csv(str(path))
    else:
        raise LoadError(f"unsupported dataset format {suffix!r}; use .csv or .parquet")
    return {str(name): str(dtype) for name, dtype in zip(rel.columns, rel.types, strict=True)}


def attach(
    con: duckdb.DuckDBPyConnection, config: SemanticConfig, *, max_rows: int = MAX_ROWS
) -> Dataset:
    """Validate an already-registered `data` relation. Tests use this with in-memory tables."""
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = $t ORDER BY ordinal_position",
        {"t": TABLE},
    ).fetchall()
    columns: dict[str, str] = {str(name): str(dtype) for name, dtype in rows}
    if not columns:
        raise LoadError(f"no relation named {TABLE!r} is registered")
    problems = _schema_problems(columns, config)
    if problems:
        raise LoadError("dataset does not match config:\n  " + "\n  ".join(problems))
    row = con.execute("SELECT COUNT(*) FROM data").fetchone()
    n_rows = int(row[0]) if row else 0
    if n_rows > max_rows:
        raise LoadError(f"dataset has {n_rows} rows; cap is {max_rows}")
    return Dataset(con=con, columns=columns, n_rows=n_rows)


def _schema_problems(columns: dict[str, str], config: SemanticConfig) -> list[str]:
    out: list[str] = []
    t = config.time_column
    if t not in columns:
        out.append(f"time_column {t!r} is not a dataset column")
    elif not columns[t].startswith(_TIME_TYPES):
        out.append(f"time_column {t!r} is {columns[t]}, not DATE/TIMESTAMP")
    for name, metric in config.metrics.items():
        col = metric.column
        if col is None:
            continue
        if col not in columns:
            out.append(f"metric {name!r}: column {col!r} is not a dataset column")
        elif metric.agg != "count" and not columns[col].startswith(_NUMERIC_TYPES):
            out.append(f"metric {name!r}: column {col!r} is {columns[col]}, not numeric")
    for name, entity in config.entities.items():
        if entity.column not in columns:
            out.append(f"entity {name!r}: column {entity.column!r} is not a dataset column")
    return out
