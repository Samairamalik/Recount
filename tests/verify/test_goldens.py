"""Golden tests: every fixture claim the engine can plan verifies to its hand label,
with the fixture's true_value as ground truth for the computed number."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from _fixture_plans import plan_for, state_code

from recount.claims import Claim, ClaimAdapter, Comparison, Growth, Ranking
from recount.config import load_config
from recount.io import load_dataset
from recount.verify import verify

CFG = load_config(Path("tests/fixtures/olist_metrics.yml"))
DS = load_dataset(Path("examples/olist/orders.parquet"), CFG)
LABELS: dict[str, Any] = json.loads(Path("tests/fixtures/labeled_claims.json").read_text())
RECORDS: list[dict[str, Any]] = LABELS["claims"]

# Claims the test scaffolding cannot turn into a plan, and why. Each is the Stage 3
# compiler's job (abstain schema_gap / ambiguous), not the engine's.
UNPLANNABLE = {
    "c1": "metric 'state_count' is not in the config (COUNT DISTINCT): schema_gap",
    "c5": "'unchanged' comparison with no baseline period",
    "c7": "comparison against a constant ('two weeks'), not a baseline period",
    "c30": "'Southeast and South regions' is not an entity alias: schema_gap",
}
# Plannable, but its label is an abstention only the compiler can produce (see d1).
COMPILER_ONLY = {"c11": "no pre-Q1 baseline exists; 'took the lead' is ambiguous"}

GOLDEN = [r for r in RECORDS if r["claim"]["id"] not in UNPLANNABLE | COMPILER_ONLY]


def _claim(record: dict[str, Any]) -> Claim:
    return ClaimAdapter.validate_python(record["claim"])


def _true_rank(claim: Ranking, true: list[list[Any]]) -> int:
    key: Any
    if claim.group_by == "quarter":
        assert claim.period is not None
        key = int(claim.period[-1])
    else:
        assert claim.subject is not None
        key = state_code(CFG, claim.subject)
    return [row[0] for row in true].index(key) + 1


def test_golden_set_covers_the_fixture() -> None:
    assert len(GOLDEN) == 52
    assert Counter(r["expected_verdict"] for r in GOLDEN) == {
        "PASS": 45,
        "FAIL": 6,
        "UNVERIFIABLE": 1,  # c12, "nearly doubled": no stated magnitude
    }


@pytest.mark.parametrize("record", GOLDEN, ids=[r["claim"]["id"] for r in GOLDEN])
def test_golden(record: dict[str, Any]) -> None:
    claim = _claim(record)
    v = verify(DS, claim, plan_for(claim, CFG))
    assert v.verdict == record["expected_verdict"], v.detail
    if v.verdict == "UNVERIFIABLE":
        assert v.abstain_reason == record["expected_reason"]
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


EXPECTED_POLICY = {
    "wrong_figure": "half_ulp",
    "rounding_drift": "half_ulp",
    "swapped_entity": "half_ulp",
    "flipped_direction": "direction",
    "wrong_ranking": "rank",
}


def test_every_corruption_fails_for_the_right_reason() -> None:
    by_id = {r["claim"]["id"]: r for r in RECORDS}
    manifest = LABELS["corruption_manifest"]["corruptions"]
    assert len(manifest) == 6
    for c in manifest:
        claim = _claim(by_id[c["id"]])
        v = verify(DS, claim, plan_for(claim, CFG))
        assert v.verdict == "FAIL", c
        assert v.policy == EXPECTED_POLICY[c["class"]], c
    # rounding_drift: 41.52 stated, 41.4654 true, bound 0.005 -> delta just beyond
    drift = verify(DS, _claim(by_id["c27"]), plan_for(_claim(by_id["c27"]), CFG))
    assert drift.delta is not None and abs(drift.delta + 0.0546) < 1e-4
    # flipped_direction: magnitude is exactly right, sign is inverted, never reaches half_ulp
    flip = verify(DS, _claim(by_id["c25"]), plan_for(_claim(by_id["c25"]), CFG))
    assert flip.computed_value is not None and flip.computed_value > 0
    assert flip.delta is None


def test_c11_abstention_is_the_compilers_job_not_the_engines() -> None:
    """Given a plan, the engine PASSes c11 (SP was #1 in Q1). The fixture expects
    UNVERIFIABLE because no baseline exists for 'took the lead'; producing that
    abstention is the Stage 3 compiler's responsibility."""
    record = next(r for r in RECORDS if r["claim"]["id"] == "c11")
    claim = _claim(record)
    assert record["expected_verdict"] == "UNVERIFIABLE"
    assert verify(DS, claim, plan_for(claim, CFG)).verdict == "PASS"


@pytest.mark.parametrize("cid", ["c15", "c36", "c33"])
def test_verdicts_are_byte_identical_across_runs(cid: str) -> None:
    record = next(r for r in RECORDS if r["claim"]["id"] == cid)
    claim = _claim(record)
    first = verify(DS, claim, plan_for(claim, CFG)).model_dump_json()
    second = verify(DS, claim, plan_for(claim, CFG)).model_dump_json()
    assert first == second
