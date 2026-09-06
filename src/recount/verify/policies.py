"""Comparison policies: pure functions from (claim, computed) to a verdict fragment.

No DuckDB here. Every branch is enumerated so it can be explained unaided:

  stated value missing  -> UNVERIFIABLE ambiguous   (vague magnitude; compiler abstains first)
  computed value None   -> UNVERIFIABLE no_data     (empty slice, zero baseline, subject absent)
  direction (growth, comparison), checked BEFORE any magnitude:
      growth  increase needs pct > 0; decrease needs pct < 0; exactly 0 fails both
      comparison higher/lower on the sign of current - baseline;
                 better/worse map through metric polarity (None -> schema_gap);
                 unchanged -> ambiguous, always
  ranking displaced set -> UNVERIFIABLE unsupported_claim_type (rank change; abstention G10)
  half_ulp: PASS iff |stated - computed| <= 0.5 * 10^-d, d = decimals in the stated number
  rank:     PASS iff the subject's SQL RANK() equals the claimed rank (ties share a rank)

NULLs: AVG excludes NULLs and SUM ignores them (SQL semantics); COUNT(*) counts every
row. The verdict reports n_rows and n_used so the denominator is visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from recount.claims import AbstainReason, Comparison, Growth, PointValue, Ranking, Share
from recount.compile import Polarity
from recount.verify.verdict import VerdictLabel


@dataclass(frozen=True)
class PolicyResult:
    verdict: VerdictLabel
    policy: str
    detail: str
    claimed_value: float | None = None
    computed_value: float | None = None
    delta: float | None = None
    abstain_reason: AbstainReason | None = None


@dataclass(frozen=True)
class RankRow:
    key: str
    value: float | None
    rank: int


def _abstain(reason: AbstainReason, detail: str, claimed: float | None = None) -> PolicyResult:
    return PolicyResult(
        verdict="UNVERIFIABLE",
        policy="abstain",
        detail=detail,
        claimed_value=claimed,
        abstain_reason=reason,
    )


# --------------------------------------------------------------------- half_ulp


def half_ulp_tolerance(stated: float) -> Decimal:
    """0.5 * 10^-d, where d is the number of decimals in the stated number as written.

    Uses the shortest round-trip repr, so 9.3 has d=1 (tol 0.05) and 43428 has d=0
    (tol 0.5, which is exact for integer-valued truths). A float carries no trailing
    zeros, so an integral value (13.0) is treated as written with 0 decimals.
    """
    exponent = Decimal(str(stated)).normalize().as_tuple().exponent
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    return Decimal("0.5").scaleb(-decimals)


def _half_ulp(
    stated: float, computed: float, *, signed_computed: float | None = None
) -> PolicyResult:
    """Compare in Decimal so the boundary case is exact, not float-subtraction noise."""
    tol = half_ulp_tolerance(stated)
    delta = Decimal(str(computed)) - Decimal(str(stated))
    ok = abs(delta) <= tol
    return PolicyResult(
        verdict="PASS" if ok else "FAIL",
        policy="half_ulp",
        detail=(f"|{stated} - {computed}| = {abs(delta)} {'<=' if ok else '>'} tolerance {tol}"),
        claimed_value=stated,
        computed_value=computed if signed_computed is None else signed_computed,
        delta=float(delta),
    )


# ------------------------------------------------------------------ per-claim-type


def check_point_value(claim: PointValue, computed: float | None) -> PolicyResult:
    if claim.value is None:
        return _abstain(AbstainReason.AMBIGUOUS, "no stated value to compare against")
    if computed is None:
        return _abstain(AbstainReason.NO_DATA, "no rows in this slice", claim.value)
    return _half_ulp(claim.value, computed)


def check_share(claim: Share, share_pct: float | None) -> PolicyResult:
    if claim.value is None:
        return _abstain(AbstainReason.AMBIGUOUS, "no stated share to compare against")
    if share_pct is None:
        return _abstain(AbstainReason.NO_DATA, "the whole is empty or zero", claim.value)
    return _half_ulp(claim.value, share_pct)


def check_growth(claim: Growth, pct_change: float | None) -> PolicyResult:
    """Direction first, magnitude second. There is no path to the magnitude check
    that does not pass through the direction check (spike c25)."""
    if claim.value is None:
        return _abstain(AbstainReason.AMBIGUOUS, "no stated growth magnitude")
    if pct_change is None:
        return _abstain(
            AbstainReason.NO_DATA, "baseline or current slice is empty or zero", claim.value
        )
    if not _sign_matches(claim.direction, pct_change):
        return PolicyResult(
            verdict="FAIL",
            policy="direction",
            detail=f"claim says {claim.direction}; computed change is {pct_change:+.4f}%",
            claimed_value=claim.value,
            computed_value=pct_change,
        )
    return _half_ulp(claim.value, abs(pct_change), signed_computed=pct_change)


def check_comparison(
    claim: Comparison,
    current: float | None,
    baseline: float | None,
    polarity: Polarity | None,
) -> PolicyResult:
    if claim.direction == "unchanged":
        # TODO(V2): a tolerance-band policy ("stable" = within X%) is a possible
        # interpretation; until one is configured, "unchanged" has no threshold.
        return _abstain(AbstainReason.AMBIGUOUS, "'unchanged' has no threshold", claim.value)
    if current is None or baseline is None:
        return _abstain(AbstainReason.NO_DATA, "current or baseline slice is empty", claim.value)
    if claim.direction in ("higher", "lower"):
        expected: Literal["increase", "decrease"] = (
            "increase" if claim.direction == "higher" else "decrease"
        )
    else:
        if polarity is None:
            return _abstain(
                AbstainReason.SCHEMA_GAP,
                f"'{claim.direction}' needs the metric's polarity in the config",
                claim.value,
            )
        improved = claim.direction == "better"
        higher_is_better = polarity == "higher_is_better"
        expected = "increase" if improved == higher_is_better else "decrease"
    diff = current - baseline
    if not _sign_matches(expected, diff):
        return PolicyResult(
            verdict="FAIL",
            policy="direction",
            detail=(
                f"claim says {claim.direction}; current {current} vs baseline {baseline}"
                f" (change {diff:+})"
            ),
            claimed_value=claim.value,
            computed_value=diff,
        )
    if claim.value is None:
        return PolicyResult(
            verdict="PASS",
            policy="direction",
            detail=(
                f"current {current} vs baseline {baseline} (change {diff:+}) is {claim.direction}"
            ),
            computed_value=diff,
        )
    return _half_ulp(claim.value, abs(diff), signed_computed=diff)


def check_ranking(claim: Ranking, subject_key: str, rows: tuple[RankRow, ...]) -> PolicyResult:
    if claim.displaced is not None:  # abstention G10; the compiler decides this first
        return _abstain(
            AbstainReason.UNSUPPORTED_CLAIM_TYPE,
            f"'displaced {claim.displaced!r}' asserts an overtaking, a rank change between"
            " two periods; rank-change verification is not supported",
            float(claim.rank),
        )
    subject = next((r for r in rows if r.key == subject_key), None)
    if subject is None:
        return _abstain(
            AbstainReason.NO_DATA,
            f"subject {subject_key!r} is not among the groups",
            float(claim.rank),
        )
    ok = subject.rank == claim.rank
    top = ", ".join(f"{r.key}={r.value}" for r in rows[:3])
    return PolicyResult(
        verdict="PASS" if ok else "FAIL",
        policy="rank",
        detail=f"{subject_key} ranks {subject.rank} (value {subject.value}); top: {top}",
        claimed_value=float(claim.rank),
        computed_value=float(subject.rank),
        delta=float(subject.rank - claim.rank),
    )


def _sign_matches(direction: Literal["increase", "decrease"], signed: float) -> bool:
    if signed == 0:
        return False
    return (signed > 0) == (direction == "increase")
