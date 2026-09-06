"""Extraction mini-eval (deterministic): score an Extraction against the hand labels.

Matching policy (spike dilemma d7, fixed here so recall is reproducible): every label
span and every accepted claim span is located at its first occurrence in the artifact;
label-claim pairs whose character intervals overlap are matched one-to-one, largest
overlap first, ties broken by document order. A label left unmatched whose span
overlaps a claim that another label took is `merged` (one span covering two
assertions); any other unmatched label is `missed`; an unmatched claim is `spurious`.

Binding accuracy compares the label's canonical fields with the extracted claim's
as-written fields after the same normalisation the compiler applies: metrics and
subjects through the config vocabulary, periods through the period parser. A field
the compiler would resolve identically on both sides counts as correct, because the
verdict would be identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from recount.claims import Claim, Comparison, Growth, Ranking
from recount.compile import PeriodError, parse_period
from recount.config import SemanticConfig, entity_index, metric_index, norm
from recount.extract.extractor import Extraction
from recount.io import Dataset
from recount.verify import verify_claim

FIELDS = (
    "type",
    "metric",
    "period",
    "subject",
    "direction",
    "value",
    "baseline_period",
    "rank",
    "group_by",
    "displaced",
    "scope",
)


@dataclass(frozen=True)
class Match:
    label_id: str
    claim_id: str
    overlap: int


@dataclass(frozen=True)
class FieldCheck:
    label_id: str
    claim_id: str
    field: str
    expected: Any
    got: Any
    ok: bool


@dataclass(frozen=True)
class VerdictCheck:
    label_id: str
    claim_id: str
    expected: str
    got: str
    reason: str | None


@dataclass(frozen=True)
class EvalReport:
    n_labels: int
    n_claims: int
    matched: tuple[Match, ...]
    merged: tuple[str, ...]  # label ids
    missed: tuple[str, ...]  # label ids
    spurious: tuple[str, ...]  # claim ids
    fields: tuple[FieldCheck, ...]
    # Accepted claims whose span is verbatim in the artifact: 1.0 by construction.
    span_validity: float
    # Accepted claim pairs whose spans overlap: a diagnostic, not a rejection.
    overlapping_claims: int
    sweep_flagged: tuple[str, ...]  # missed numeric labels whose number the sweep reported
    sweep_silent: tuple[str, ...]  # missed numeric labels the sweep did not report
    verdicts: tuple[VerdictCheck, ...]

    @property
    def precision(self) -> float:
        return len(self.matched) / self.n_claims if self.n_claims else 0.0

    @property
    def recall(self) -> float:
        return len(self.matched) / self.n_labels

    def binding_accuracy(self, field: str) -> tuple[int, int]:
        checks = [f for f in self.fields if f.field == field]
        return sum(f.ok for f in checks), len(checks)

    def verdict_counts(self) -> dict[str, int]:
        counts = {"agree": 0, "false_accept": 0, "false_flag": 0, "other": 0}
        for v in self.verdicts:
            if v.got == v.expected:
                counts["agree"] += 1
            elif v.got == "PASS" and v.expected == "FAIL":
                counts["false_accept"] += 1
            elif v.got == "FAIL" and v.expected != "FAIL":
                counts["false_flag"] += 1
            else:
                counts["other"] += 1
        return counts

    def summary(self) -> dict[str, Any]:
        return {
            "labels": self.n_labels,
            "claims": self.n_claims,
            "matched": len(self.matched),
            "merged": len(self.merged),
            "missed": len(self.missed),
            "spurious": len(self.spurious),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "span_validity": self.span_validity,
            "binding": {f: self.binding_accuracy(f) for f in FIELDS},
            "sweep_flagged": len(self.sweep_flagged),
            "sweep_silent": len(self.sweep_silent),
            "verdicts": self.verdict_counts(),
        }


def _interval(artifact: str, span: str, owner: str) -> tuple[int, int]:
    i = artifact.find(span)
    if i < 0:
        raise ValueError(f"{owner}: span not in artifact: {span!r}")
    return i, i + len(span)


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _resolve_metric(cfg: SemanticConfig, text: str) -> str:
    return metric_index(cfg).get(norm(text), f"unresolved:{norm(text)}")


def _resolve_subject(cfg: SemanticConfig, text: str | None) -> str | None:
    if text is None:
        return None
    hit = entity_index(cfg).get(norm(text))
    return f"{hit[0]}={hit[1]}" if hit else f"unresolved:{norm(text)}"


def _resolve_period(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        p = parse_period(text)
    except PeriodError:
        return f"unparseable:{norm(text)}"
    return f"{p.start}..{p.end}"


def _normalised(cfg: SemanticConfig, field: str, value: Any) -> Any:
    if field == "metric":
        return _resolve_metric(cfg, value)
    if field == "subject":
        return _resolve_subject(cfg, value)
    if field in ("period", "baseline_period", "scope"):
        return _resolve_period(value)
    if field in ("group_by", "displaced") and isinstance(value, str):
        return norm(value)
    return value


def _field_checks(
    cfg: SemanticConfig, label: dict[str, Any], claim: Claim, m: Match
) -> list[FieldCheck]:
    got_fields = claim.model_dump()
    out: list[FieldCheck] = []
    for field in FIELDS:
        if field not in label:  # the label's type does not declare it
            continue
        expected, got = label[field], got_fields.get(field)
        ok = _normalised(cfg, field, expected) == _normalised(cfg, field, got)
        out.append(FieldCheck(m.label_id, m.claim_id, field, expected, got, ok))
    return out


def evaluate(
    artifact: str,
    labels: list[dict[str, Any]],
    extraction: Extraction,
    cfg: SemanticConfig,
    dataset: Dataset | None = None,
) -> EvalReport:
    """`labels` are the fixture records ({"claim": {...}, "expected_verdict": ...})."""
    label_claims = [r["claim"] for r in labels]
    label_at = {c["id"]: _interval(artifact, c["span"], c["id"]) for c in label_claims}
    claims = extraction.claims
    claim_at = {c.id: _interval(artifact, c.span, c.id) for c in claims}

    span_validity = sum(c.span in artifact for c in claims) / len(claims) if claims else 1.0

    pairs = [
        (-_overlap(label_at[lc["id"]], claim_at[c.id]), li, ci, lc["id"], c.id)
        for li, lc in enumerate(label_claims)
        for ci, c in enumerate(claims)
        if _overlap(label_at[lc["id"]], claim_at[c.id]) > 0
    ]
    matched: list[Match] = []
    taken_labels: set[str] = set()
    taken_claims: set[str] = set()
    for neg, _, _, lid, cid in sorted(pairs):
        if lid in taken_labels or cid in taken_claims:
            continue
        matched.append(Match(lid, cid, -neg))
        taken_labels.add(lid)
        taken_claims.add(cid)

    merged: list[str] = []
    missed: list[str] = []
    for lc in label_claims:
        if lc["id"] in taken_labels:
            continue
        overlaps_taken = any(
            _overlap(label_at[lc["id"]], claim_at[cid]) > 0 for cid in taken_claims
        )
        (merged if overlaps_taken else missed).append(lc["id"])
    spurious = [c.id for c in claims if c.id not in taken_claims]

    by_label = {c["id"]: c for c in label_claims}
    by_claim = {c.id: c for c in claims}
    fields = [
        f
        for m in matched
        for f in _field_checks(cfg, by_label[m.label_id], by_claim[m.claim_id], m)
    ]

    intervals = list(claim_at.values())
    overlapping = sum(
        _overlap(a, b) > 0 for i, a in enumerate(intervals) for b in intervals[i + 1 :]
    )

    flagged: list[str] = []
    silent: list[str] = []
    for lid in missed:
        if by_label[lid].get("value") is None:
            continue
        a, b = label_at[lid]
        hit = any(a <= t.start and t.end <= b for t in extraction.unextracted_numeric)
        (flagged if hit else silent).append(lid)

    verdicts: list[VerdictCheck] = []
    if dataset is not None:
        expected_by_id = {r["claim"]["id"]: r for r in labels}
        for m in matched:
            v = verify_claim(dataset, by_claim[m.claim_id], cfg)
            rec = expected_by_id[m.label_id]
            verdicts.append(
                VerdictCheck(
                    m.label_id,
                    m.claim_id,
                    rec["expected_verdict"],
                    v.verdict,
                    v.abstain_reason.value if v.abstain_reason else None,
                )
            )

    return EvalReport(
        n_labels=len(label_claims),
        n_claims=len(claims),
        matched=tuple(matched),
        merged=tuple(merged),
        missed=tuple(missed),
        spurious=tuple(spurious),
        fields=tuple(fields),
        span_validity=span_validity,
        overlapping_claims=overlapping,
        sweep_flagged=tuple(flagged),
        sweep_silent=tuple(silent),
        verdicts=tuple(verdicts),
    )


def describe(claim: Claim) -> str:
    """One line for the failure-mode table."""
    d = claim.model_dump()
    head = (
        f"{d['type']} metric={d['metric']!r} period={d['period']!r}"
        f" subject={d['subject']!r} value={d.get('value')}"
    )
    if isinstance(claim, Growth | Comparison):
        return f"{head} {claim.direction} vs {claim.baseline_period}"
    if isinstance(claim, Ranking):
        return (
            f"{head} rank {claim.rank} by {claim.group_by}"
            f" scope={claim.scope} displaced={claim.displaced}"
        )
    return head
