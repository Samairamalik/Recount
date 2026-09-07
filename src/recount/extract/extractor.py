"""The extractor: one structured call per artifact, then deterministic rejection.

The response schema is derived from the Stage 1 Claim models at import time (single
source of truth; tests/extract/test_extractor.py pins the derivation). Every returned
object is re-validated through `ClaimAdapter`, then post-checked. Post-checks REJECT,
never repair: a claim whose span is not a verbatim substring of the artifact, a claim
whose span (or id) another claim also uses, a claim carrying a non-null field its type
does not declare. Rejected claims are kept as records for the report; they never reach
a verdict. Claims are never invented and never patched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import ValidationError

from recount.claims import Claim, ClaimAdapter, Comparison, Growth, PointValue, Ranking, Share
from recount.extract.client import ExtractError, ExtractorClient
from recount.extract.prompt import PROMPT
from recount.extract.sweep import NumericToken, sweep

CLAIM_CLASSES: tuple[type[Claim], ...] = (PointValue, Growth, Comparison, Ranking, Share)
_BY_TYPE: dict[str, type[Claim]] = {
    get_args(cls.model_fields["type"].annotation)[0]: cls for cls in CLAIM_CLASSES
}
# Never-null on the wire: the model must always name these. Everything else is nullable
# on the wire; Pydantic re-validation enforces each type's own requirements afterwards.
# Since Stage 5 (docs/benchmark.md §6, changelog 1) EVERY key is *required*: a model that
# drops optional keys instead of writing null (gemini-3.1-flash-lite omitted `subject`
# on 55/55 objects and `value`/`direction`/`period` by type) must now emit an explicit
# null, which Pydantic then rejects where the type needs a value. Post-validation unchanged.
WIRE_REQUIRED = ("id", "type", "span", "metric", "confidence")


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    options = schema.get("anyOf", [schema])
    if any(o.get("type") == "null" for o in options):
        return schema
    return {"anyOf": [schema, {"type": "null"}]}


def _stripped(prop: dict[str, Any]) -> dict[str, Any]:
    """Drop title/default and numeric bounds (`ge=0`, `rank >= 1`); Pydantic re-validation
    enforces the bounds per type afterwards."""
    prop = {k: v for k, v in prop.items() if k not in ("title", "default")}
    for option in prop.get("anyOf", [prop]):
        option.pop("minimum", None)
    return prop


def _merge(name: str, variants: list[dict[str, Any]]) -> dict[str, Any]:
    """One wire schema for a field declared by several Claim classes: identical schemas
    merge trivially; enums merge as their union (Growth's `direction` is increase/decrease,
    Comparison's is higher/lower/...; the wire must admit both). Anything else is a
    drift between the models that the derivation cannot express: fail at import."""
    first = variants[0]
    if all(v == first for v in variants):
        return first
    if all(set(v) == {"enum", "type"} and v["type"] == "string" for v in variants):
        values = [x for v in variants for x in v["enum"]]
        return {"type": "string", "enum": list(dict.fromkeys(values))}
    raise ValueError(f"field {name!r} has incompatible schemas across Claim classes: {variants}")


def wire_schema() -> dict[str, Any]:
    """Flat JSON schema: the union of the five Claim models' fields.

    Flat because a discriminated union of five objects is not reliably accepted by
    the provider's schema subset. A field declared by several classes gets the merge
    of their schemas (see `_merge`); `type` becomes an enum of the five literals.
    """
    variants: dict[str, list[dict[str, Any]]] = {}
    for cls in CLAIM_CLASSES:
        for name, prop in cls.model_json_schema()["properties"].items():
            if name != "type":
                variants.setdefault(name, []).append(_stripped(prop))
    properties = {
        name: (merged if name in WIRE_REQUIRED else _nullable(merged))
        for name, vs in variants.items()
        for merged in [_merge(name, vs)]
    }
    properties["type"] = {"type": "string", "enum": list(_BY_TYPE)}
    return {
        "type": "array",
        "items": {"type": "object", "properties": properties, "required": list(properties)},
    }


WIRE_SCHEMA = wire_schema()

RejectReason = Literal[
    "not_an_object",
    "unknown_type",
    "foreign_field",
    "invalid_claim",
    "span_not_verbatim",
    "duplicate_span",
    "duplicate_id",
]


@dataclass(frozen=True)
class Rejected:
    raw: Any  # the wire object as returned
    reason: RejectReason
    detail: str


@dataclass(frozen=True)
class Extraction:
    claims: tuple[Claim, ...]
    rejected: tuple[Rejected, ...]
    unextracted_numeric: tuple[NumericToken, ...]
    raw: str  # the response text the claims came from
    model: str


def _call(client: ExtractorClient, artifact: str) -> tuple[list[Any], str]:
    """One call, one retry. At temperature 0 the retry is expected to help only with
    transport errors and empty responses; a content-level failure (invalid JSON, not
    an array) will usually repeat and ends in ExtractError by design."""
    raw = ""
    error = "no response"
    for attempt in range(2):
        try:
            raw = client.complete(PROMPT, artifact, WIRE_SCHEMA)
            data = json.loads(raw)
        except ExtractError:
            raise
        except Exception as e:  # provider/transport error or invalid JSON
            error = f"{type(e).__name__}: {e}"
            if attempt == 0:
                continue
            break
        if isinstance(data, list):
            return data, raw
        error = f"response is {type(data).__name__}, not an array"
    raise ExtractError(f"extraction failed twice; last error: {error}", raw=raw)


def _validate(item: Any) -> Claim | Rejected:
    if not isinstance(item, dict):
        return Rejected(item, "not_an_object", f"expected an object, got {type(item).__name__}")
    cls = _BY_TYPE.get(str(item.get("type")))
    if cls is None:
        return Rejected(item, "unknown_type", f"type {item.get('type')!r}")
    foreign = sorted(k for k, v in item.items() if k not in cls.model_fields and v is not None)
    if foreign:
        return Rejected(item, "foreign_field", f"{cls.__name__} does not declare {foreign}")
    projected = {k: v for k, v in item.items() if k in cls.model_fields}
    try:
        return ClaimAdapter.validate_python(projected)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        return Rejected(item, "invalid_claim", problems)


def extract_claims(
    artifact: str, client: ExtractorClient, *, raw_dump: Path | None = None
) -> Extraction:
    try:
        items, raw = _call(client, artifact)
    except ExtractError as e:
        if raw_dump is not None and e.raw:
            raw_dump.parent.mkdir(parents=True, exist_ok=True)
            raw_dump.write_text(e.raw)
        raise

    accepted: list[Claim] = []
    rejected: list[Rejected] = []
    for item in items:
        got = _validate(item)
        if isinstance(got, Rejected):
            rejected.append(got)
        elif got.span not in artifact:
            rejected.append(Rejected(item, "span_not_verbatim", f"span {got.span!r}"))
        else:
            accepted.append(got)

    # Duplicates: the same span or id on two claims. Neither can be trusted, so both go.
    dupe_checks: tuple[tuple[str, RejectReason], ...] = (
        ("span", "duplicate_span"),
        ("id", "duplicate_id"),
    )
    for field, reason in dupe_checks:
        seen = [getattr(c, field) for c in accepted]
        dupes = {v for v in seen if seen.count(v) > 1}
        for c in [c for c in accepted if getattr(c, field) in dupes]:
            accepted.remove(c)
            rejected.append(Rejected(c.model_dump(), reason, f"{field} {getattr(c, field)!r}"))

    return Extraction(
        claims=tuple(accepted),
        rejected=tuple(rejected),
        unextracted_numeric=sweep(artifact, tuple(c.span for c in accepted)),
        raw=raw,
        model=client.model,
    )
