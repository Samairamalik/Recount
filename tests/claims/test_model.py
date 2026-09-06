"""Round-trip every hand-labeled claim through the Claim schema, and pin its guardrails."""

import json
from collections import Counter
from typing import Any

import pytest
from pydantic import ValidationError

from recount.claims import AbstainReason, ClaimAdapter, Growth, Ranking

with open("tests/fixtures/labeled_claims.json") as f:
    _RECORDS: list[dict[str, Any]] = json.load(f)["claims"]


@pytest.mark.parametrize("record", _RECORDS, ids=[r["claim"]["id"] for r in _RECORDS])
def test_claim_round_trips(record: dict[str, Any]) -> None:
    raw = record["claim"]
    claim = ClaimAdapter.validate_python(raw)
    dumped = claim.model_dump()
    # nothing the label stated was altered or lost
    assert {k: dumped[k] for k in raw} == raw
    # JSON -> model -> JSON -> model is stable
    again = ClaimAdapter.validate_json(json.dumps(dumped))
    assert again == claim
    assert again.model_dump() == dumped


def test_fixture_is_the_full_spike_label_set(labels: dict[str, Any]) -> None:
    claims = [r["claim"] for r in labels["claims"]]
    assert len(claims) == 57
    assert Counter(c["type"] for c in claims) == {
        "point_value": 35,
        "growth": 7,
        "share": 6,
        "ranking": 5,
        "comparison": 4,
    }
    assert Counter(r["expected_verdict"] for r in labels["claims"]) == {
        "PASS": 45,
        "FAIL": 6,
        "UNVERIFIABLE": 6,  # c1 relabelled schema_gap in Stage 3 (abstention F1)
    }


def test_unverifiable_labels_carry_an_abstain_reason(labels: dict[str, Any]) -> None:
    for r in labels["claims"]:
        if r["expected_verdict"] == "UNVERIFIABLE":
            assert AbstainReason(r["expected_reason"])
        else:
            assert "expected_reason" not in r


def test_corruption_taxonomy_is_frozen(labels: dict[str, Any]) -> None:
    manifest = labels["corruption_manifest"]
    assert manifest["taxonomy"] == [
        "wrong_figure",
        "flipped_direction",
        "wrong_ranking",
        "swapped_entity",
        "fabricated_metric",
        "rounding_drift",
        "instruction_in_data",
    ]
    by_id = {r["claim"]["id"]: r for r in labels["claims"]}
    assert len(manifest["corruptions"]) == 6
    for c in manifest["corruptions"]:
        assert c["class"] in manifest["taxonomy"]
        assert by_id[c["id"]]["expected_verdict"] == "FAIL"
    variants = {c["id"]: c.get("variant") for c in manifest["corruptions"]}
    assert variants["c19"] == "revenue" and variants["c45"] == "delivery"


def _claim(id_: str, labels: dict[str, Any]) -> dict[str, Any]:
    return dict(next(r["claim"] for r in labels["claims"] if r["claim"]["id"] == id_))


def test_unknown_type_is_rejected(labels: dict[str, Any]) -> None:
    raw = _claim("c3", labels) | {"type": "trend"}
    with pytest.raises(ValidationError):
        ClaimAdapter.validate_python(raw)


def test_label_only_fields_are_rejected(labels: dict[str, Any]) -> None:
    raw = _claim("c3", labels) | {"true_value": 6921535.24}
    with pytest.raises(ValidationError):
        ClaimAdapter.validate_python(raw)


def test_growth_direction_is_required(labels: dict[str, Any]) -> None:
    raw = _claim("c25", labels)
    del raw["direction"]
    with pytest.raises(ValidationError):
        ClaimAdapter.validate_python(raw)


def test_growth_value_is_a_magnitude(labels: dict[str, Any]) -> None:
    raw = _claim("c25", labels) | {"value": -43.61}
    with pytest.raises(ValidationError):
        ClaimAdapter.validate_python(raw)


def test_direction_only_and_superlative_claims_need_no_value(labels: dict[str, Any]) -> None:
    improved = ClaimAdapter.validate_python(_claim("c17", labels))
    assert improved.type == "comparison" and improved.value is None
    peak = ClaimAdapter.validate_python(_claim("c23", labels))
    assert isinstance(peak, Ranking) and peak.rank == 1 and peak.group_by == "quarter"


def test_share_requires_subject(labels: dict[str, Any]) -> None:
    raw = _claim("c33", labels)
    del raw["subject"]
    with pytest.raises(ValidationError):
        ClaimAdapter.validate_python(raw)


def test_claims_are_frozen(labels: dict[str, Any]) -> None:
    claim = ClaimAdapter.validate_python(_claim("c25", labels))
    assert isinstance(claim, Growth)
    with pytest.raises(ValidationError):
        claim.direction = "increase"  # type: ignore[misc]


def test_comparison_value_is_a_magnitude(labels: dict[str, Any]) -> None:
    raw = _claim("c17", labels) | {"value": -0.5}
    with pytest.raises(ValidationError):
        ClaimAdapter.validate_python(raw)


def test_ranking_scope_and_displaced_round_trip(labels: dict[str, Any]) -> None:
    peak = ClaimAdapter.validate_python(_claim("c23", labels))
    assert isinstance(peak, Ranking) and peak.scope == "2017"
    lead = ClaimAdapter.validate_python(_claim("c11", labels))
    assert isinstance(lead, Ranking) and lead.displaced == "unspecified" and lead.scope is None
