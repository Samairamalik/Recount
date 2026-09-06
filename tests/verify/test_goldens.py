"""End-to-end goldens: every one of the 57 hand-labeled fixture claims goes through the
real compiler and the engine (verify_claim) and must produce its expected_verdict
and, for abstentions, its expected_reason. The fixture's true_value is the ground
truth for the computed number. No claim is excluded and no plan is hand-built."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from recount.claims import Claim, ClaimAdapter, Comparison, Growth, Ranking
from recount.config import entity_index, load_config, norm
from recount.io import load_dataset
from recount.verify import Verdict, verify_claim

CFG = load_config(Path("tests/fixtures/olist_metrics.yml"))
DS = load_dataset(Path("examples/olist/orders.parquet"), CFG)
LABELS: dict[str, Any] = json.loads(Path("tests/fixtures/labeled_claims.json").read_text())
RECORDS: list[dict[str, Any]] = LABELS["claims"]
BY_ID = {r["claim"]["id"]: r for r in RECORDS}


def _claim(record: dict[str, Any]) -> Claim:
    return ClaimAdapter.validate_python(record["claim"])


def _verdict(cid: str) -> Verdict:
    return verify_claim(DS, _claim(BY_ID[cid]), CFG)


def _true_rank(claim: Ranking, true: list[list[Any]]) -> int:
    key: Any
    if claim.group_by == "quarter":
        assert claim.period is not None
        key = int(claim.period[-1])
    else:
        assert claim.subject is not None
        key = entity_index(CFG)[norm(claim.subject)][1]
    return [row[0] for row in true].index(key) + 1


def test_golden_set_is_the_whole_fixture() -> None:
    assert len(RECORDS) == 57
    assert Counter(r["expected_verdict"] for r in RECORDS) == {
        "PASS": 45,
        "FAIL": 6,
        "UNVERIFIABLE": 6,  # c1 c5 c7 c11 c12 c30
    }
    assert Counter(r.get("expected_reason") for r in RECORDS if "expected_reason" in r) == {
        "schema_gap": 2,  # c1 (M2), c30 (E4)
        "ambiguous": 3,  # c5 (D1), c7 (V5), c12 (V3)
        "unsupported_claim_type": 1,  # c11 (G10)
    }


@pytest.mark.parametrize("record", RECORDS, ids=[r["claim"]["id"] for r in RECORDS])
def test_golden(record: dict[str, Any]) -> None:
    claim = _claim(record)
    v = verify_claim(DS, claim, CFG)
    assert v.verdict == record["expected_verdict"], v.detail
    if v.verdict == "UNVERIFIABLE":
        assert v.abstain_reason == record["expected_reason"], v.detail
        assert v.sql == "" and v.params == {} and v.row_counts == {}  # compiler, not engine
        return
    true = record["true_value"]
    assert v.computed_value is not None
    if isinstance(claim, Ranking):
        assert v.computed_value == _true_rank(claim, true)
    elif isinstance(claim, Comparison):
        (cur, base), *_ = true
        assert abs(v.computed_value - (cur - base)) <= 1e-3
    elif isinstance(claim, Growth):
        assert abs(abs(v.computed_value) - true) <= 5e-5  # fixture stores the magnitude
    else:
        assert abs(v.computed_value - true) <= 5e-5  # fixture rounds to 4 dp


def test_compiler_abstentions_execute_no_sql() -> None:
    for cid in ("c1", "c5", "c7", "c11", "c12", "c30"):
        v = _verdict(cid)
        assert v.policy == "abstain" and v.sql == "" and v.computed_value is None, cid


EXPECTED_POLICY = {
    "wrong_figure": "half_ulp",
    "rounding_drift": "half_ulp",
    "swapped_entity": "half_ulp",
    "flipped_direction": "direction",
    "wrong_ranking": "rank",
}


def test_every_corruption_fails_for_the_right_reason() -> None:
    manifest = LABELS["corruption_manifest"]["corruptions"]
    assert len(manifest) == 6
    for c in manifest:
        v = _verdict(c["id"])
        assert v.verdict == "FAIL", c
        assert v.policy == EXPECTED_POLICY[c["class"]], c
    # rounding_drift: 41.52 stated, 41.4654 true, bound 0.005 -> delta just beyond
    drift = _verdict("c27")
    assert drift.delta is not None and abs(drift.delta + 0.0546) < 1e-4
    # flipped_direction: magnitude is exactly right, sign is inverted, never reaches half_ulp
    flip = _verdict("c25")
    assert flip.computed_value is not None and flip.computed_value > 0
    assert flip.delta is None


def test_c11_overtaking_is_carried_by_displaced_not_by_the_span() -> None:
    """SP was #1 in Q1, so a plain rank check PASSes. The fixture expects UNVERIFIABLE
    because 'took the lead' asserts an overtaking; that reading reaches the verdict
    only through the typed `displaced` field (abstention G10), never the span."""
    claim = _claim(BY_ID["c11"])
    assert isinstance(claim, Ranking) and claim.displaced == "unspecified"
    assert verify_claim(DS, claim, CFG).verdict == "UNVERIFIABLE"
    stripped = claim.model_copy(update={"displaced": None})
    assert verify_claim(DS, stripped, CFG).verdict == "PASS"


@pytest.mark.parametrize("cid", ["c15", "c36", "c33", "c23", "c1"])
def test_verdicts_are_byte_identical_across_runs(cid: str) -> None:
    assert _verdict(cid).model_dump_json() == _verdict(cid).model_dump_json()
