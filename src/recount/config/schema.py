"""SemanticConfig: the user's YAML that binds report vocabulary to dataset columns.

Same flat shape as the Stage 0 spike config, extended where the spike showed a
need: per-metric rounding (float sums are not order-stable) and polarity
(which direction of a metric is "better").
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    column: str
    # alias as written in reports -> value as stored in the column
    aliases: dict[str, str] = Field(default_factory=dict)


class Metric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agg: Literal["sum", "count", "avg", "share"]
    # Required for sum/avg. count/share without a column count rows.
    column: str | None = None
    aliases: list[str] = Field(default_factory=list)
    # Decimals the computed value is rounded to before comparison. Pinned per
    # metric because SUM over DOUBLE varies with row order (spike d6).
    round: int | None = Field(default=None, ge=0)
    # No default on purpose: a silent "higher is better" is a false-accept path.
    polarity: Literal["higher_is_better", "lower_is_better"] | None = None

    @model_validator(mode="after")
    def _column_matches_agg(self) -> Metric:
        if self.agg in ("sum", "avg") and self.column is None:
            raise ValueError(f"agg {self.agg!r} needs a column")
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
    def _aliases_unambiguous(self) -> SemanticConfig:
        owner: dict[str, str] = {}
        for name, metric in self.metrics.items():
            for alias in {name, *metric.aliases}:
                if alias in owner and owner[alias] != name:
                    raise ValueError(
                        f"alias {alias!r} claimed by both {owner[alias]!r} and {name!r}"
                    )
                owner[alias] = name
        return self


def load_config(path: Path) -> SemanticConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    return SemanticConfig.model_validate(data)
