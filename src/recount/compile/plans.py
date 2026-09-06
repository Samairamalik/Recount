"""ComputePlans: what the engine computes, as closed-world typed objects.

A plan carries resolved column names, half-open period bounds and a group key;
never SQL text, never claim text. The engine renders each plan kind into its one
fixed template (verify/engine.py). The claim's assertion (stated value, direction,
rank) stays on the Claim and is compared against the computed result by
verify/policies.py, so a policy reads direction from the claim field itself.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

Polarity = Literal["higher_is_better", "lower_is_better"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Period(_Frozen):
    """Half-open interval [start, end) on the plan's time column."""

    start: date
    end: date

    @model_validator(mode="after")
    def _non_empty(self) -> Period:
        if not self.start < self.end:
            raise ValueError(f"period must satisfy start < end, got [{self.start}, {self.end})")
        return self


class EntityFilter(_Frozen):
    column: str
    # The stored value ("SP"), already resolved from the report's alias. Bound as a
    # parameter, never rendered into SQL text.
    value: str


class Measure(_Frozen):
    agg: Literal["sum", "count", "avg"]
    column: str | None = None
    # Decimals DuckDB ROUND applies to the aggregate before it leaves SQL.
    round: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _column_matches_agg(self) -> Measure:
        if self.agg in ("sum", "avg") and self.column is None:
            raise ValueError(f"agg {self.agg!r} needs a column")
        return self


class EntityKey(_Frozen):
    by: Literal["entity"] = "entity"
    column: str


class TimeKey(_Frozen):
    """Group by a calendar grain of the plan's time column (learning-log, Stage 3 req. b)."""

    by: Literal["time"] = "time"
    grain: Literal["month", "quarter", "year"]


GroupKey = Annotated[EntityKey | TimeKey, Field(discriminator="by")]


class AggregatePlan(_Frozen):
    kind: Literal["aggregate"] = "aggregate"
    time_column: str
    measure: Measure
    period: Period
    entity: EntityFilter | None = None


class GrowthPlan(_Frozen):
    kind: Literal["growth"] = "growth"
    time_column: str
    measure: Measure
    period: Period
    baseline: Period
    entity: EntityFilter | None = None


class ComparePlan(_Frozen):
    kind: Literal["compare"] = "compare"
    time_column: str
    measure: Measure
    period: Period
    baseline: Period
    entity: EntityFilter | None = None
    # Needed only for better/worse claims; None makes those abstain (schema_gap).
    polarity: Polarity | None = None


class RankPlan(_Frozen):
    kind: Literal["rank"] = "rank"
    time_column: str
    measure: Measure
    # The ranking universe (e.g. the whole year when ranking quarters).
    period: Period
    group_by: GroupKey
    # The group the claim is about, as the engine's VARCHAR key: an entity value
    # ("SP") or a grain start date ("2017-07-01").
    subject_key: str
    # Required: rank 1 means "best", and without polarity there is no ordering.
    polarity: Polarity


class SharePlan(_Frozen):
    kind: Literal["share"] = "share"
    time_column: str
    measure: Measure
    period: Period
    part: EntityFilter

    @model_validator(mode="after")
    def _share_of_sum_or_count(self) -> SharePlan:
        if self.measure.agg == "avg":
            raise ValueError("a share of an average is not defined")
        return self


ComputePlan = Annotated[
    AggregatePlan | GrowthPlan | ComparePlan | RankPlan | SharePlan, Field(discriminator="kind")
]
PlanAdapter: TypeAdapter[ComputePlan] = TypeAdapter(ComputePlan)
