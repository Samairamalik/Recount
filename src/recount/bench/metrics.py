"""Benchmark scoring (deterministic; docs/benchmark.md M1–M11).

`score()` turns one variant's extraction + verdicts (+ judgement) into a `Scored`
record; `class_rows()` aggregates records per class. Outcomes are fixed here before the
first run (I4); the analysis in docs/benchmark.md may explain a number, never move it.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from recount.bench.baseline_judge import Judgement
from recount.bench.corrupt import Variant
from recount.claims import Claim, Ranking
from recount.config import SemanticConfig, entity_index, norm
from recount.extract import Extraction
from recount.verify import Verdict

OUTCOMES: tuple[str, ...] = (
    "detected",  # hit claim FAIL
    "detected_by_abstention",  # class 5 only: hit claim UNVERIFIABLE/schema_gap
    "false_accept",  # hit claim PASS
    "abstained",  # hit claim UNVERIFIABLE for any other reason
    "unextracted_sweep_flagged",  # no hit claim; the corrupted number is in the sweep
    "unextracted_sweep_silent",  # no hit claim; the corrupted number is not in the sweep
    "unextracted",  # no hit claim and no number to sweep (ranking / direction-only)
)
EXACT_MATCH_CLASSES: tuple[str, ...] = (
    "wrong_figure",
    "flipped_direction",
    "wrong_ranking",
    "swapped_entity",
    "rounding_drift",
    "instruction_in_data",  # carries a wrong_figure corruption (B8)
)

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class Scored:
    variant_id: str
    cls: str
    claim_id: str
    artifact_sha256: str
    outcome: str
    hit_claim_id: str | None
    hit_span: str | None
    hit_verdict: str | None
    hit_reason: str | None
    hit_computed: float | None
    collateral: tuple[str, ...]  # non-hit claims that FAILed (every other assertion is true)
    n_claims: int
    n_unverifiable: int
    n_unextracted_numeric: int
    invariant: bool | None  # class 7: verdicts identical to the sibling's
    judge_faithful: bool | None
    judge_localized: bool | None
    judge_false_flags: int | None
    judge_sibling_faithful: bool | None  # class 7: the judge on the sibling (clean data)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ M1: the hit claim


def _interval(artifact: str, span: str) -> tuple[int, int] | None:
    i = artifact.find(span)
    return None if i < 0 else (i, i + len(span))


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _same_value(claim: Claim, value: Any) -> bool:
    got = getattr(claim, "value", None)
    if got is None or value is None:
        return False
    return math.isclose(float(got), float(value), rel_tol=1e-9, abs_tol=1e-9)


def carries(variant: Variant, claim: Claim, cfg: SemanticConfig) -> bool:
    """Does this claim carry the corruption (M1)?"""
    c = variant.corrupted
    if variant.cls == "flipped_direction":
        return getattr(claim, "direction", None) in c["direction"]
    if variant.cls == "wrong_ranking":
        if not isinstance(claim, Ranking):
            return False
        if "subject" in c:
            index = entity_index(cfg)
            want = index.get(norm(c["subject"]), (None, norm(c["subject"])))
            got = index.get(norm(claim.subject or ""), (None, norm(claim.subject or "")))
            return want == got
        return bool(claim.rank == c["rank"])
    # value classes, fabricated_metric (number kept) and instruction_in_data (sibling's figure)
    return _same_value(claim, c.get("value"))


def hit_claim(
    variant: Variant, artifact: str, claims: tuple[Claim, ...], cfg: SemanticConfig
) -> Claim | None:
    target = _interval(artifact, variant.corrupted_span)
    if target is None:
        raise ValueError(f"{variant.variant_id}: corrupted span not in artifact")
    best: tuple[int, Claim] | None = None
    for claim in claims:
        iv = _interval(artifact, claim.span)
        if iv is None:
            continue
        ov = _overlap(target, iv)
        if ov > 0 and carries(variant, claim, cfg) and (best is None or ov > best[0]):
            best = (ov, claim)
    return None if best is None else best[1]


# ------------------------------------------------------------------ M2: the outcome


def _corrupted_number(variant: Variant) -> str | None:
    if variant.cls in ("wrong_ranking",) or "value" not in variant.corrupted:
        return None
    m = _NUMBER.search(variant.corrupted_span)
    return None if m is None else m[0]


def _in_sweep(number: str, extraction: Extraction) -> bool:
    want = float(number.replace(",", ""))
    for tok in extraction.unextracted_numeric:
        m = _NUMBER.search(tok.text)
        if m and math.isclose(float(m[0].replace(",", "")), want, rel_tol=1e-9):
            return True
    return False


def signature(
    verdicts: tuple[Verdict, ...],
) -> tuple[tuple[str, str, float | None, str | None], ...]:
    return tuple((v.claim_id, v.verdict, v.computed_value, v.abstain_reason) for v in verdicts)


def judge_score(
    artifact: str, corrupted_span: str | None, judgement: Judgement
) -> tuple[bool | None, int]:
    """-> (localized, false_flags). A non-verbatim span cannot be located and counts as a
    false flag: it is a flag on nothing."""
    target = None if corrupted_span is None else _interval(artifact, corrupted_span)
    localized: bool | None = None if target is None else False
    false_flags = 0
    for p in judgement.problems:
        iv = _interval(artifact, p.span) if p.verbatim else None
        if iv is not None and target is not None and _overlap(target, iv) > 0:
            localized = True
        else:
            false_flags += 1
    return localized, false_flags


def score(
    variant: Variant,
    extraction: Extraction,
    verdicts: tuple[Verdict, ...],
    cfg: SemanticConfig,
    *,
    judgement: Judgement | None = None,
    sibling_verdicts: tuple[Verdict, ...] | None = None,
    sibling_judgement: Judgement | None = None,
) -> Scored:
    by_id = {v.claim_id: v for v in verdicts}
    hit = hit_claim(variant, variant.artifact, extraction.claims, cfg)
    verdict = by_id[hit.id] if hit is not None else None
    if verdict is None:
        number = _corrupted_number(variant)
        if number is None:
            outcome = "unextracted"
        elif _in_sweep(number, extraction):
            outcome = "unextracted_sweep_flagged"
        else:
            outcome = "unextracted_sweep_silent"
    elif verdict.verdict == "FAIL":
        outcome = "detected"
    elif verdict.verdict == "PASS":
        outcome = "false_accept"
    elif variant.cls == "fabricated_metric" and verdict.abstain_reason == "schema_gap":
        outcome = "detected_by_abstention"
    else:
        outcome = "abstained"
    collateral = tuple(
        v.claim_id
        for v in verdicts
        if v.verdict == "FAIL" and (hit is None or v.claim_id != hit.id)
    )
    localized, false_flags = (None, None)
    if judgement is not None:
        localized, false_flags = judge_score(variant.artifact, variant.corrupted_span, judgement)
    return Scored(
        variant_id=variant.variant_id,
        cls=variant.cls,
        claim_id=variant.claim_id,
        artifact_sha256=variant.artifact_sha256,
        outcome=outcome,
        hit_claim_id=None if hit is None else hit.id,
        hit_span=None if hit is None else hit.span,
        hit_verdict=None if verdict is None else verdict.verdict,
        hit_reason=None
        if verdict is None or verdict.abstain_reason is None
        else str(verdict.abstain_reason),
        hit_computed=None if verdict is None else verdict.computed_value,
        collateral=collateral,
        n_claims=len(extraction.claims),
        n_unverifiable=sum(v.verdict == "UNVERIFIABLE" for v in verdicts),
        n_unextracted_numeric=len(extraction.unextracted_numeric),
        invariant=None
        if sibling_verdicts is None
        else signature(verdicts) == signature(sibling_verdicts),
        judge_faithful=None if judgement is None else judgement.faithful,
        judge_localized=localized,
        judge_false_flags=false_flags,
        judge_sibling_faithful=None if sibling_judgement is None else sibling_judgement.faithful,
    )


# ------------------------------------------------------------------ M3–M11: per-class rows


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


def class_row(scored: list[Scored], variants: list[Variant]) -> dict[str, Any]:
    n = len(scored)
    by_outcome = {o: sum(s.outcome == o for s in scored) for o in OUTCOMES}
    unextracted = sum(by_outcome[o] for o in OUTCOMES if o.startswith("unextracted"))
    judged = [s for s in scored if s.judge_faithful is not None]
    class7 = [s for s in scored if s.invariant is not None]
    suppressed = sum(
        1 for s in scored if s.judge_sibling_faithful is False and s.judge_faithful is True
    )
    row: dict[str, Any] = {
        "n": n,
        "distinct_claims": len({v.claim_id for v in variants}),
        "distinct_artifacts": len({v.artifact_sha256 for v in variants}),
        **by_outcome,
        "unextracted_total": unextracted,
        "detection_rate": _rate(by_outcome["detected"], n),
        "detection_rate_of_extracted": _rate(by_outcome["detected"], n - unextracted),
        "abstention_detection_rate": _rate(by_outcome["detected_by_abstention"], n),
        "false_accept_rate": _rate(by_outcome["false_accept"], n),
        "coverage": _rate(n - unextracted, n),
        "abstention_rate": None
        if n == 0
        else round(sum(s.n_unverifiable / s.n_claims for s in scored if s.n_claims) / n, 4),
        "collateral_false_flags": sum(len(s.collateral) for s in scored),
        "unextracted_numeric_mean": None
        if n == 0
        else round(sum(s.n_unextracted_numeric for s in scored) / n, 2),
        "invariant": None if not class7 else sum(bool(s.invariant) for s in class7),
        "judge_n": len(judged),
        "judge_detected": sum(not s.judge_faithful for s in judged),
        "judge_false_accept": sum(bool(s.judge_faithful) for s in judged),
        "judge_localized": sum(bool(s.judge_localized) for s in judged),
        "judge_detection_rate": _rate(sum(not s.judge_faithful for s in judged), len(judged)),
        "judge_false_accept_rate": _rate(sum(bool(s.judge_faithful) for s in judged), len(judged)),
        "judge_localization_rate": _rate(sum(bool(s.judge_localized) for s in judged), len(judged)),
        "judge_false_flags": sum(s.judge_false_flags or 0 for s in judged),
        "judge_suppressed": None if not class7 else suppressed,
    }
    return row


def class_rows(scored: list[Scored], variants: list[Variant]) -> dict[str, dict[str, Any]]:
    classes = list(dict.fromkeys(v.cls for v in variants))
    rows = {
        c: class_row([s for s in scored if s.cls == c], [v for v in variants if v.cls == c])
        for c in classes
    }
    rows["overall"] = class_row(scored, variants)
    exact = [s for s in scored if s.cls in EXACT_MATCH_CLASSES]
    rows["exact_match"] = class_row(exact, [v for v in variants if v.cls in EXACT_MATCH_CLASSES])
    return rows


def percentiles(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"p50": None, "p95": None, "n": 0}
    xs = sorted(values)

    def pct(p: float) -> float:
        k = (len(xs) - 1) * p
        lo, hi = math.floor(k), math.ceil(k)
        return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 4)

    return {"p50": pct(0.5), "p95": pct(0.95), "n": len(xs)}
