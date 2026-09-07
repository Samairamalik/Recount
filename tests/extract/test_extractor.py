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


def test_retries_once_on_transport_error_then_succeeds() -> None:
    client = Scripted(RuntimeError("503"), [_pv()])
    assert len(extract_claims(ARTIFACT, client).claims) == 1


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


def test_rejected_claims_leave_their_numbers_to_the_sweep() -> None:
    ex = extract_claims(ARTIFACT, Scripted([_pv(span="revenue was 1234.50")]))
    assert [t.text for t in ex.unextracted_numeric] == ["1,234.50", "20"]
