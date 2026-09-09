"""Extractor: schema derivation pinned to the Claim models, the retry, and every
rejection path. Reject, never repair: no test here expects a claim to be fixed up."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from recount.claims import Comparison, Growth, PointValue, Ranking, Share
from recount.extract import (
    PROMPT,
    WIRE_SCHEMA,
    ExtractError,
    extract_claims,
)
from recount.extract.extractor import WIRE_REQUIRED

ARTIFACT = "In 2017 revenue was 1,234.50 across 20 orders, and delivery improved."


class Scripted:
    model = "scripted"

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        self.calls.append((prompt, artifact, schema))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


def _pv(**over: Any) -> dict[str, Any]:
    base = {
        "id": "c1",
        "type": "point_value",
        "span": "revenue was 1,234.50",
        "metric": "revenue",
        "value": 1234.5,
        "period": "2017",
        "confidence": "high",
    }
    return {**base, **over}


# ---------------------------------------------------------------- wire schema


def test_wire_schema_is_the_union_of_the_claim_models() -> None:
    props = WIRE_SCHEMA["items"]["properties"]
    expected = set()
    for cls in (PointValue, Growth, Comparison, Ranking, Share):
        expected |= set(cls.model_fields)
    assert set(props) == expected
    # every key is required since Stage 5 (changelog 1): a model must write null, never omit
    assert WIRE_SCHEMA["items"]["required"] == list(props)
    assert set(WIRE_REQUIRED) < set(props)
    assert props["type"]["enum"] == ["point_value", "growth", "comparison", "ranking", "share"]


def test_wire_schema_direction_admits_growth_and_comparison_vocabularies() -> None:
    """Iteration 1 of the eval took `direction` from Growth alone, so the model could
    never emit a comparison direction and every comparison was rejected (docs/eval.md)."""
    direction = WIRE_SCHEMA["items"]["properties"]["direction"]
    enum = next(o for o in direction["anyOf"] if "enum" in o)["enum"]
    assert set(enum) == {"increase", "decrease", "higher", "lower", "better", "worse", "unchanged"}


def test_wire_schema_optional_fields_are_nullable_and_unbounded() -> None:
    props = WIRE_SCHEMA["items"]["properties"]
    for name, prop in props.items():
        if name in WIRE_REQUIRED:
            continue
        assert any(o.get("type") == "null" for o in prop["anyOf"]), name
    assert "minimum" not in json.dumps(props)  # ge=0 / rank>=1 live in Pydantic, not the wire


# ------------------------------------------------------------- call and retry


def test_one_call_happy_path() -> None:
    client = Scripted([_pv()])
    ex = extract_claims(ARTIFACT, client)
    assert len(client.calls) == 1
    prompt, artifact, schema = client.calls[0]
    assert prompt == PROMPT and artifact == ARTIFACT and schema == WIRE_SCHEMA
    assert [c.span for c in ex.claims] == ["revenue was 1,234.50"]
    assert ex.rejected == ()
    assert ex.model == "scripted"
    assert [t.context for t in ex.unextracted_numeric] == ["20 orders"]


def test_retries_once_on_invalid_json_then_succeeds() -> None:
    client = Scripted("not json {", [_pv()])
    ex = extract_claims(ARTIFACT, client)
    assert len(client.calls) == 2 and len(ex.claims) == 1


_slept: list[float] = []


def test_retries_once_on_transport_error_then_succeeds() -> None:
    client = Scripted(RuntimeError("503"), [_pv()])
    assert len(extract_claims(ARTIFACT, client, sleep=_slept.append).claims) == 1
    assert _slept == [1.0]  # backed off once before the retry that worked
    _slept.clear()


def test_f7_a_transient_upstream_failure_backs_off_and_is_named_as_such() -> None:
    """Acceptance F-7: two runs died on a transient 503. Failing closed is right; giving up
    after one immediate retry made a CI gate brittle. Four attempts, exponential backoff,
    and an error that says the upstream was unavailable rather than that extraction was
    invalid — the two need different responses from whoever reads the log."""
    client = Scripted(*[RuntimeError("503 UNAVAILABLE")] * 4)
    slept: list[float] = []
    with pytest.raises(ExtractError, match="upstream unavailable after 4 attempts"):
        extract_claims(ARTIFACT, client, sleep=slept.append)
    assert len(client.calls) == 4 and slept == [1.0, 4.0, 16.0]


@pytest.mark.parametrize("error", ["429 RESOURCE_EXHAUSTED", "500 INTERNAL", "connection reset"])
def test_transient_markers_are_retried_to_the_end(error: str) -> None:
    client = Scripted(RuntimeError(error), RuntimeError(error), [_pv()])
    assert len(extract_claims(ARTIFACT, client, sleep=lambda _: None).claims) == 1
    assert len(client.calls) == 3


def test_a_content_failure_is_not_backed_off() -> None:
    """An unusable response at temperature 0 usually repeats: one immediate retry, then the
    same "failed twice" as before. Waiting longer buys nothing and stalls CI."""
    slept: list[float] = []
    with pytest.raises(ExtractError, match="failed twice"):
        extract_claims(ARTIFACT, Scripted("garbage 1", "garbage 2"), sleep=slept.append)
    assert slept == []


def test_invalid_twice_raises_and_dumps_raw(tmp_path: Path) -> None:
    client = Scripted("garbage 1", "garbage 2")
    dump = tmp_path / "raw.txt"
    with pytest.raises(ExtractError, match="failed twice") as info:
        extract_claims(ARTIFACT, client, raw_dump=dump)
    assert info.value.raw == "garbage 2"
    assert dump.read_text() == "garbage 2"
    assert len(client.calls) == 2


def test_not_an_array_twice_raises() -> None:
    with pytest.raises(ExtractError, match="not an array"):
        extract_claims(ARTIFACT, Scripted({"claims": []}, {"claims": []}))


def test_client_extract_error_is_not_retried() -> None:
    client = Scripted(ExtractError("stale recording"))
    with pytest.raises(ExtractError, match="stale"):
        extract_claims(ARTIFACT, client)
    assert len(client.calls) == 1


# ---------------------------------------------------------------- rejections


def _reasons(ex: Any) -> list[str]:
    return [r.reason for r in ex.rejected]


def test_rejects_non_objects_and_unknown_types() -> None:
    ex = extract_claims(ARTIFACT, Scripted(["text", _pv(type="trend")]))
    assert ex.claims == ()
    assert _reasons(ex) == ["not_an_object", "unknown_type"]


def test_rejects_a_non_null_field_the_type_does_not_declare() -> None:
    ex = extract_claims(ARTIFACT, Scripted([_pv(direction="increase")]))
    assert _reasons(ex) == ["foreign_field"]
    assert "direction" in ex.rejected[0].detail


def test_null_wire_fields_are_the_envelope_not_a_claim_field() -> None:
    """The flat wire schema makes every field present; nulls in fields the type does
    not declare are the envelope, not content, and are not a foreign_field."""
    ex = extract_claims(ARTIFACT, Scripted([_pv(direction=None, rank=None, scope=None)]))
    assert ex.rejected == () and len(ex.claims) == 1


@pytest.mark.parametrize(
    "item",
    [
        _pv(type="growth", value=-5, direction="decrease"),  # ge=0: sign lives in direction
        _pv(type="growth", value=5),  # direction required, no default
        _pv(type="share", value=10.0),  # share needs a subject
        _pv(type="ranking", value=None, rank=0, group_by="state", subject="SP"),  # rank >= 1
        _pv(confidence="medium"),
        _pv(span=""),
    ],
)
def test_rejects_claims_the_models_refuse(item: dict[str, Any]) -> None:
    ex = extract_claims(ARTIFACT, Scripted([item]))
    assert ex.claims == () and _reasons(ex) == ["invalid_claim"]


def test_rejects_span_not_verbatim() -> None:
    ex = extract_claims(ARTIFACT, Scripted([_pv(span="revenue was 1234.50")]))  # comma dropped
    assert _reasons(ex) == ["span_not_verbatim"]
    ex = extract_claims(ARTIFACT, Scripted([_pv(span="Revenue was 1,234.50")]))  # case
    assert _reasons(ex) == ["span_not_verbatim"]


def test_rejects_every_claim_sharing_a_span() -> None:
    ex = extract_claims(
        ARTIFACT, Scripted([_pv(id="c1"), _pv(id="c2"), _pv(id="c3", span="20 orders", value=20)])
    )
    assert [c.id for c in ex.claims] == ["c3"]
    assert _reasons(ex) == ["duplicate_span", "duplicate_span"]


def test_rejects_every_claim_sharing_an_id() -> None:
    ex = extract_claims(
        ARTIFACT, Scripted([_pv(id="c1"), _pv(id="c1", span="20 orders", value=20)])
    )
    assert ex.claims == () and _reasons(ex) == ["duplicate_id", "duplicate_id"]


LEVELS = "Delivery improved, bringing the average delivery time down to 12.55 days in Q2."


def _cmp(span: str, value: float | None, **over: Any) -> dict[str, Any]:
    base = {
        "id": "c1", "type": "comparison", "span": span, "metric": "average delivery time",
        "value": value, "direction": "lower", "period": "2017-Q2", "baseline_period": "2017-Q1",
        "confidence": "high",
    }  # fmt: skip
    return {**base, **over}


def test_f4_rejects_a_comparison_whose_value_is_a_level() -> None:
    """Stage 6, F-4: 'down to 12.55 days' states the level; Comparison.value is the difference."""
    ex = extract_claims(LEVELS, Scripted([_cmp("down to 12.55 days", 12.55)]))
    assert _reasons(ex) == ["value_not_a_difference"]
    assert "level, not a difference" in ex.rejected[0].detail
    assert [t.context for t in ex.unextracted_numeric] == ["12.55 days"]  # falls to the sweep


@pytest.mark.parametrize(
    ("artifact", "span", "value"),
    [
        ("Delivery time fell by 2.3 days in Q2.", "fell by 2.3 days", 2.3),
        ("Delivery time fell by about 2.3 days in Q2.", "fell by about 2.3 days", 2.3),
        ("Delivery took 2.3 days less than in Q1.", "2.3 days less than in Q1", 2.3),
        ("Delivery was 2.3 days faster.", "2.3 days faster", 2.3),
        (LEVELS, "Delivery improved", None),  # direction-only: nothing to check
    ],
)
def test_f4_keeps_a_value_written_as_a_difference(artifact: str, span: str, value: Any) -> None:
    ex = extract_claims(artifact, Scripted([_cmp(span, value)]))
    assert ex.rejected == () and len(ex.claims) == 1


def test_f4_rejects_a_growth_whose_value_is_not_a_percentage() -> None:
    level = _cmp("down to 12.55 days", 12.55, type="growth", direction="decrease")
    ex = extract_claims(LEVELS, Scripted([level]))
    assert _reasons(ex) == ["value_not_a_difference"]
    assert "not written as a percentage" in ex.rejected[0].detail
    pct = _cmp("grew 12.4%", 12.4, type="growth", direction="increase")
    assert extract_claims("Revenue grew 12.4% in Q2.", Scripted([pct])).rejected == ()
    words = _cmp("grew 12.4 percent", 12.4, type="growth", direction="increase")
    assert extract_claims("Revenue grew 12.4 percent.", Scripted([words])).rejected == ()


def test_rejected_claims_leave_their_numbers_to_the_sweep() -> None:
    ex = extract_claims(ARTIFACT, Scripted([_pv(span="revenue was 1234.50")]))
    assert [t.text for t in ex.unextracted_numeric] == ["1,234.50", "20"]
