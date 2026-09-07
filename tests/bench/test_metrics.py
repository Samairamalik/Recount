"""Outcome classification (M1–M2), judge scoring (M10) and the class rows (M11) on
hand-built claims and verdicts."""

from __future__ import annotations

from typing import Any

from recount.bench.baseline_judge import Judgement, Problem
from recount.bench.corrupt import Variant
from recount.bench.metrics import class_rows, hit_claim, judge_score, percentiles, score
from recount.claims import ClaimAdapter
from recount.config import SemanticConfig
from recount.extract import Extraction, sweep
from recount.verify import Verdict

CLEAN = "Sao Paulo generated 2,428,002.62 in revenue across 17,071 orders in 2017."


def _variant(
    cls: str, original: str, corrupted: str, o: dict[str, Any], c: dict[str, Any]
) -> Variant:
    artifact = CLEAN.replace(original, corrupted, 1)
    return Variant(
        variant_id=f"t-{cls}",
        seed=1,
        cls=cls,
        claim_id="x",
        original_span=original,
        corrupted_span=corrupted,
        original=o,
        corrupted=c,
        true_value=2428002.62,
        expected="FAIL",
        artifact=artifact,
        artifact_sha256="0" * 64,
    )


def _claim(**fields: Any) -> Any:
    return ClaimAdapter.validate_python({"confidence": "high", "period": "2017", **fields})


def _verdict(cid: str, label: str, reason: str | None = None) -> Verdict:
    return Verdict(
        claim_id=cid,
        verdict=label,
        claimed_value=None,
        computed_value=1.0,
        delta=None,  # type: ignore[arg-type]
        policy="t",
        detail="",
        sql="",
        params={},
        row_counts={},
        abstain_reason=reason,  # type: ignore[arg-type]
    )


def _extraction(artifact: str, *claims: Any) -> Extraction:
    return Extraction(
        claims=tuple(claims),
        rejected=(),
        unextracted_numeric=sweep(artifact, tuple(c.span for c in claims)),
        raw="",
        model="t",
    )


WF = _variant(
    "wrong_figure",
    "generated 2,428,002.62 in revenue",
    "generated 4,228,002.62 in revenue",
    {"value": 2428002.62},
    {"value": 4228002.62},
)


def test_hit_claim_needs_overlap_and_the_corrupted_value(cfg: SemanticConfig) -> None:
    hit = _claim(
        id="a",
        type="point_value",
        span="generated 4,228,002.62 in revenue",
        metric="revenue",
        value=4228002.62,
        subject="Sao Paulo",
    )
    other = _claim(
        id="b",
        type="point_value",
        span="across 17,071 orders",
        metric="orders",
        value=17071,
        subject="Sao Paulo",
    )
    stale = _claim(
        id="c", type="point_value", span="in revenue", metric="revenue", value=2428002.62
    )
    assert hit_claim(WF, WF.artifact, (other, stale, hit), cfg) is hit
    assert hit_claim(WF, WF.artifact, (other, stale), cfg) is None


def test_outcomes(cfg: SemanticConfig) -> None:
    hit = _claim(
        id="a",
        type="point_value",
        span="4,228,002.62 in revenue",
        metric="revenue",
        value=4228002.62,
        subject="Sao Paulo",
    )
    other = _claim(
        id="b",
        type="point_value",
        span="across 17,071 orders",
        metric="orders",
        value=17071,
        subject="Sao Paulo",
    )
    ex = _extraction(WF.artifact, hit, other)
    assert score(WF, ex, (_verdict("a", "FAIL"), _verdict("b", "PASS")), cfg).outcome == "detected"
    s = score(WF, ex, (_verdict("a", "PASS"), _verdict("b", "FAIL")), cfg)
    assert s.outcome == "false_accept" and s.collateral == ("b",)
    s = score(WF, ex, (_verdict("a", "UNVERIFIABLE", "ambiguous"), _verdict("b", "PASS")), cfg)
    assert s.outcome == "abstained" and s.hit_reason == "ambiguous"
    # not extracted: the corrupted number is uncovered, so the sweep flags it
    s = score(WF, _extraction(WF.artifact, other), (_verdict("b", "PASS"),), cfg)
    assert s.outcome == "unextracted_sweep_flagged"
    # covered by a claim that does not carry the corruption, and not in the sweep either
    wide = _claim(
        id="w",
        type="point_value",
        span="generated 4,228,002.62 in revenue",
        metric="revenue",
        value=2428002.62,
    )
    s = score(WF, _extraction(WF.artifact, wide), (_verdict("w", "PASS"),), cfg)
    assert s.outcome == "unextracted_sweep_silent"


def test_fabricated_metric_abstention_is_its_own_outcome(cfg: SemanticConfig) -> None:
    fm = _variant(
        "fabricated_metric",
        "generated 2,428,002.62 in revenue",
        "generated 2,428,002.62 in net profit",
        {"metric": "revenue", "value": 2428002.62},
        {"metric": "net profit", "value": 2428002.62},
    )
    hit = _claim(
        id="a",
        type="point_value",
        span="2,428,002.62 in net profit",
        metric="net profit",
        value=2428002.62,
    )
    ex = _extraction(fm.artifact, hit)
    assert (
        score(fm, ex, (_verdict("a", "UNVERIFIABLE", "schema_gap"),), cfg).outcome
        == "detected_by_abstention"
    )
    assert score(fm, ex, (_verdict("a", "UNVERIFIABLE", "ambiguous"),), cfg).outcome == "abstained"
    assert score(fm, ex, (_verdict("a", "PASS"),), cfg).outcome == "false_accept"


def test_direction_and_ranking_hits(cfg: SemanticConfig) -> None:
    text = (
        "Revenue increased by 10% in 2017-Q2. Rio de Janeiro secured the second position overall."
    )
    fd = Variant(
        variant_id="t-fd",
        seed=1,
        cls="flipped_direction",
        claim_id="g",
        original_span="Revenue increased by 10%",
        corrupted_span="Revenue declined by 10%",
        original={"word": "increased", "direction": "increase"},
        corrupted={"word": "declined", "direction": ["decrease"]},
        true_value=10.0,
        expected="FAIL",
        artifact=text.replace("increased", "declined"),
        artifact_sha256="1" * 64,
    )
    g = _claim(
        id="g",
        type="growth",
        span="Revenue declined by 10%",
        metric="revenue",
        value=10,
        direction="decrease",
        period="2017-Q2",
        baseline_period="2017-Q1",
    )
    wrong = _claim(
        id="h",
        type="growth",
        span="Revenue declined by 10%",
        metric="revenue",
        value=10,
        direction="increase",
        period="2017-Q2",
        baseline_period="2017-Q1",
    )
    assert hit_claim(fd, fd.artifact, (wrong,), cfg) is None
    assert hit_claim(fd, fd.artifact, (g,), cfg) is g
    s = score(fd, _extraction(fd.artifact, wrong), (_verdict("h", "PASS"),), cfg)
    assert s.outcome == "unextracted"  # the corruption is a word, not a number: nothing to sweep

    wr = Variant(
        variant_id="t-wr",
        seed=1,
        cls="wrong_ranking",
        claim_id="r",
        original_span="Rio de Janeiro secured the second position overall",
        corrupted_span="Rio de Janeiro secured the fourth position overall",
        original={"rank": 2},
        corrupted={"rank": 4},
        true_value=None,
        expected="FAIL",
        artifact=text.replace("second", "fourth"),
        artifact_sha256="2" * 64,
    )
    r = _claim(
        id="r",
        type="ranking",
        span="Rio de Janeiro secured the fourth position overall",
        metric="orders",
        subject="Rio de Janeiro",
        rank=4,
        group_by="state",
    )
    assert hit_claim(wr, wr.artifact, (r,), cfg) is r
    s = score(wr, _extraction(wr.artifact), (), cfg)
    assert s.outcome == "unextracted"  # nothing numeric to sweep

    ent = Variant(
        variant_id="t-we",
        seed=1,
        cls="wrong_ranking",
        claim_id="r",
        original_span="Rio de Janeiro secured the second position overall",
        corrupted_span="Parana secured the second position overall",
        original={"subject": "Rio de Janeiro", "rank": 2},
        corrupted={"subject": "Parana", "rank": 2},
        true_value=None,
        expected="FAIL",
        artifact=text.replace("Rio de Janeiro", "Parana"),
        artifact_sha256="3" * 64,
    )
    pr = _claim(
        id="p",
        type="ranking",
        span="Parana secured the second position overall",
        metric="orders",
        subject="PR",
        rank=2,
        group_by="state",
    )  # alias resolves to the same state
    assert hit_claim(ent, ent.artifact, (pr,), cfg) is pr


def test_judge_score_localization_and_false_flags() -> None:
    j = Judgement(
        faithful=False,
        problems=(
            Problem("4,228,002.62 in revenue", "wrong", True),
            Problem("across 17,071 orders", "wrong", True),
            Problem("not in the text", "?", False),
        ),
        raw="",
        model="t",
    )
    localized, flags = judge_score(WF.artifact, WF.corrupted_span, j)
    assert localized is True and flags == 2
    assert judge_score(CLEAN, None, j) == (None, 3)


def test_class_rows_and_percentiles(cfg: SemanticConfig) -> None:
    hit = _claim(
        id="a",
        type="point_value",
        span="4,228,002.62 in revenue",
        metric="revenue",
        value=4228002.62,
        subject="Sao Paulo",
    )
    ex = _extraction(WF.artifact, hit)
    j_bad = Judgement(True, (), "", "t")
    a = score(WF, ex, (_verdict("a", "FAIL"),), cfg, judgement=j_bad)
    b = score(
        WF,
        ex,
        (_verdict("a", "PASS"),),
        cfg,
        judgement=Judgement(False, (Problem(WF.corrupted_span, "", True),), "", "t"),
    )
    rows = class_rows([a, b], [WF, WF])
    r = rows["wrong_figure"]
    assert (r["n"], r["distinct_claims"], r["detected"], r["false_accept"]) == (2, 1, 1, 1)
    assert r["detection_rate"] == 0.5 and r["false_accept_rate"] == 0.5 and r["coverage"] == 1.0
    assert (r["judge_detected"], r["judge_false_accept"], r["judge_localized"]) == (1, 1, 1)
    assert rows["exact_match"]["n"] == 2 and rows["overall"]["n"] == 2
    assert percentiles([]) == {"p50": None, "p95": None, "n": 0}
    assert percentiles([1.0, 2.0, 3.0, 4.0, 5.0]) == {"p50": 3.0, "p95": 4.8, "n": 5}
