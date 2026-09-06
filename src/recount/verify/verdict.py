"""Verdict: the audit record for one claim. Frozen; serializes to JSON as-is."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from recount.claims import AbstainReason

Param = str | int | date | None
VerdictLabel = Literal["PASS", "FAIL", "UNVERIFIABLE"]


class Verdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    verdict: VerdictLabel
    # The number the claim stated (growth: unsigned magnitude; ranking: the rank).
    claimed_value: float | None
    # What the engine computed for the same quantity (growth: signed pct change;
    # ranking: the subject's rank). None when the slice had no data.
    computed_value: float | None
    # computed - claimed in the unit the policy compared (growth: |pct| - stated).
    delta: float | None
    # Which policy branch decided: half_ulp, direction, rank, or abstain.
    policy: str
    detail: str
    # Exactly the SQL text executed and the parameters bound to it.
    sql: str
    params: dict[str, Param]
    row_counts: dict[str, int]
    abstain_reason: AbstainReason | None = None
