"""Claim contracts: the only shape in which artifact text may reach a verdict.

Every model is frozen and forbids extra fields, so the extractor cannot smuggle
anything past the schema and label-only fields cannot leak in. `Claim` is a
discriminated union on `type`; validate with `ClaimAdapter`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class _ClaimBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    # Verbatim assertion. Exact-substring-of-artifact is enforced at extraction,
    # where the artifact is in hand; the model alone cannot check it.
    span: str = Field(min_length=1)
    # Extractor's certainty about its own extraction, not about the sentence's
    # truth. Required so an omitted value can never silently read as "high".
    confidence: Literal["high", "low"]
    # Entity as written. 13 of 39 spike spans named no entity at all; `subject`
    # was the only carrier, and span-local verification would have false-flagged them.
    subject: str | None = None
    # As written; alias resolution belongs to the compiler.
    metric: str
    # As written ("2017-Q3"); parsing belongs to the compiler. Null is never guessed.
    period: str | None
    # Informational only. No verdict depends on it.
    unit: str | None = None


class PointValue(_ClaimBase):
    type: Literal["point_value"]
    # Null only for vague magnitudes ("substantial revenue"); those abstain.
    value: float | None


class Growth(_ClaimBase):
    type: Literal["growth"]
    # Stated magnitude in percent, never signed: the sign lives in `direction` only.
    value: float | None = Field(ge=0)
    # Required and two-valued, with no "unspecified": a verifier must be unable to
    # compare magnitude without a sign (spike c25, the sign-blind false accept).
    # A directionless sentence forces the extractor to commit; a wrong commit
    # yields FAIL, a false flag, which is the safe failure.
    direction: Literal["increase", "decrease"]
    # Null abstains in the compiler; the spike's silent "previous quarter" fallback was a guess.
    baseline_period: str | None = None


class Comparison(_ClaimBase):
    type: Literal["comparison"]
    # "better"/"worse" are only checkable with metric polarity from config;
    # "unchanged" has no threshold and always abstains, but is recorded, not dropped.
    direction: Literal["higher", "lower", "better", "worse", "unchanged"]
    # Stated absolute difference, if any, as an unsigned magnitude: the sign lives
    # in `direction` only (like Growth), so a sign/direction conflict cannot exist.
    # Null for a direction-only comparison.
    value: float | None = Field(ge=0)
    baseline_period: str | None = None


class Ranking(_ClaimBase):
    type: Literal["ranking"]
    # Which end of the ordering rank 1 counts from, as the sentence names it. Stage 8
    # amendment (F-3): the end a superlative names is a property of the sentence, not of
    # the metric, and one report can hold both ends of one metric ("peaking at 1,263.31
    # seconds" and "a low ... in the fourth quarter"). Before this field the end came from
    # `metrics.<m>.polarity`, which answers a different question ("which way is better"),
    # so a truthful superlative on a lower_is_better metric FAILed. "highest"/"lowest" name
    # the numeric end directly; "best"/"worst" are the quality wording ("peak fulfillment
    # efficiency", "the worst delivery times") and resolve through polarity, exactly as
    # Comparison splits higher/lower from better/worse. Null abstains (abstention G12):
    # a claims file or recording predating the field is never read as "highest".
    rank_from: Literal["highest", "lowest", "best", "worst"] | None = None
    # Position counted from the `rank_from` end: rank 3 with "lowest" is the third smallest.
    rank: int = Field(ge=1)
    # An entities dimension ("state") or a time grain ("quarter").
    group_by: str
    # "SP overtook RJ": captured so the compiler can abstain or check both sides,
    # instead of silently degrading to "SP is #1" (spike d1). Non-null means the
    # text asserts an overtaking; "unspecified" is the reserved value for an
    # unnamed party ("took the lead"). Abstains unsupported_claim_type (abstention G10).
    displaced: str | None = None
    # The ranking universe as written. For a time-grain ranking it is a period ("of the
    # year" -> "2017"), never inferred from a calendar (abstention G8). Stage 8 (F-4): on
    # an entity ranking it carries the sentence's own restriction of the universe verbatim
    # ("among top companies"), which is unquantified and therefore abstains (G11) instead
    # of being silently dropped and ranked against every group in the data.
    scope: str | None = None


class Share(_ClaimBase):
    type: Literal["share"]
    # Stated share in percent.
    value: float | None

    @model_validator(mode="after")
    def _subject_required(self) -> Share:
        if self.subject is None:
            raise ValueError("share claims need a subject: a share of what, held by whom")
        return self


Claim = Annotated[PointValue | Growth | Comparison | Ranking | Share, Field(discriminator="type")]
ClaimAdapter: TypeAdapter[Claim] = TypeAdapter(Claim)


class AbstainReason(StrEnum):
    """Why the compiler refused to verify. Grouped by what the user can do about it.

    Specific diagnostics (which metric, which entity) belong in the verdict's `detail`.
    """

    # Tool limitation: this claim type is not handled. File an issue.
    UNSUPPORTED_CLAIM_TYPE = "unsupported_claim_type"
    # Config lacks the metric, entity, dimension, or polarity. Fixable in YAML.
    SCHEMA_GAP = "schema_gap"
    # The sentence is irreducibly vague. Only a rewrite fixes it.
    AMBIGUOUS = "ambiguous"
    # The dataset has no rows for this slice, the growth baseline is zero, or the
    # ranking subject is not among the groups. Check the period/entity, or the data.
    # Added in Stage 2 (see docs/learning-log.md): the engine, not the compiler, raises it.
    NO_DATA = "no_data"
