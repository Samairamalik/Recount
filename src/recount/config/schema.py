"""SemanticConfig: the user's YAML that binds report vocabulary to dataset columns.

Same flat shape as the Stage 0 spike config, extended where the spike showed a
need: per-metric rounding (float sums are not order-stable) and polarity
(which direction of a metric is "better").

Vocabulary matching (metric names/aliases, entity alias keys and stored values,
dimension names) goes through `norm()` on both sides, and the config is validated
so that every normalised token resolves to exactly one thing. Rules C1–C5 of
docs/abstention.md live here.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Ranking group_by words resolved from time_column, never from entities (abstention G1).
TIME_GRAINS: tuple[str, ...] = ("month", "quarter", "year")
# Reserved value of Ranking.displaced for an unnamed displaced party (abstention G10).
UNSPECIFIED = "unspecified"


def norm(text: str) -> str:
    """NFKD, drop combining marks, casefold, collapse whitespace (abstention §0.1)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    column: str
    # alias as written in reports -> value as stored in the column
    aliases: dict[str, str] = Field(default_factory=dict)


class Metric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agg: Literal["sum", "count", "avg", "share"]
    # Required for sum/avg. count without a column counts rows. share never takes
    # a column: it is the entity's row count over the period's row count (C5).
    column: str | None = None
    aliases: list[str] = Field(default_factory=list)
    # Decimals the computed value is rounded to before comparison. Pinned per
    # metric because SUM over DOUBLE varies with row order (spike d6).
    round: int | None = Field(default=None, ge=0)
    # No default on purpose: a silent "higher is better" is a false-accept path.
    polarity: Literal["higher_is_better", "lower_is_better"] | None = None
    # Minimum rows a group needs to enter a ranking universe by this metric (Stage 8,
    # F-4: on real data a one-row group wins any average). None means no filter, so no
    # existing config changes behaviour; `recount init` writes an active 30 on avg
    # metrics. A subject below it abstains no_data (N5), never FAILs: the claim is not
    # adjudicable at the support the config declares, which is not the same as wrong.
    min_rows: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _column_matches_agg(self) -> Metric:
        if self.agg in ("sum", "avg") and self.column is None:
            raise ValueError(f"agg {self.agg!r} needs a column")
        if self.agg == "share" and self.column is not None:  # C5
            raise ValueError(
                "agg 'share' takes no column: a share is the entity's row count over the"
                " period's row count, and no other denominator is accepted"
            )
        return self


class SemanticConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str | None = None
    time_column: str
    entities: dict[str, Entity]
    metrics: dict[str, Metric]
    # half_ulp: pass iff |stated - true| <= 0.5 * 10^-(decimals in stated).
    # The only rule so far; it caught the spike's rounding_drift corruption.
    tolerance_rule: Literal["half_ulp"] = "half_ulp"

    @model_validator(mode="after")
    def _vocabulary_resolves_uniquely(self) -> SemanticConfig:
        metric_index(self)  # C1
        entity_index(self)  # C3, C4
        return self


def metric_index(cfg: SemanticConfig) -> dict[str, str]:
    """norm(name or alias) -> metric name. Raises if one token names two metrics (C1)."""
    owner: dict[str, str] = {}
    for name, metric in cfg.metrics.items():
        for alias in (name, *metric.aliases):
            token = norm(alias)
            if owner.setdefault(token, name) != name:
                raise ValueError(f"alias {alias!r} claimed by both {owner[token]!r} and {name!r}")
    return owner


def entity_index(cfg: SemanticConfig) -> dict[str, tuple[str, str]]:
    """norm(alias key or stored value) -> (dimension, stored value), across all dimensions.

    Raises if a dimension is named like a time grain (C3), if one token would
    resolve to two different targets, or if a token is the reserved word
    'unspecified' (C4). Two spellings of the same target ("Sao Paulo" and
    "São Paulo" -> SP) are allowed: they resolve identically.
    """
    owner: dict[str, tuple[str, str]] = {}
    for dim, entity in cfg.entities.items():
        if norm(dim) in TIME_GRAINS:
            raise ValueError(
                f"entity dimension {dim!r} is a reserved time grain {TIME_GRAINS};"
                " rankings by it would never reach the entities table"
            )
        for key, value in entity.aliases.items():
            for token in (key, value):
                t = norm(token)
                if t == UNSPECIFIED:
                    raise ValueError(f"entity alias {token!r} is reserved (Ranking.displaced)")
                target = (dim, value)
                if owner.setdefault(t, target) != target:
                    raise ValueError(
                        f"entity alias {token!r} resolves to both {owner[t]} and {target}"
                    )
    return owner


def load_config(path: Path) -> SemanticConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    return SemanticConfig.model_validate(data)
