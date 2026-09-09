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
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import ValidationError

from recount.claims import Claim, ClaimAdapter, Comparison, Growth, PointValue, Ranking, Share
from recount.extract.client import ExtractError, ExtractorClient
from recount.extract.prompt import PROMPT
from recount.extract.sweep import NumericToken, coverage, sweep

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
    "value_not_a_difference",
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


# An upstream failure that is worth waiting out: 5xx, rate limits, transport. Matched on
# the exception's text because the provider SDK raises several classes for these
# (acceptance F-7: two consecutive runs died on a transient 503, which is correct
# fail-closed behaviour and a brittle CI gate). A content failure is not in here on purpose.
TRANSIENT = ("500", "502", "503", "504", "UNAVAILABLE", "INTERNAL", "429", "RESOURCE_EXHAUSTED",
             "DEADLINE_EXCEEDED", "timeout", "Timeout", "connection")  # fmt: skip
# Delays before attempts 2, 3 and 4 of a transient failure; four attempts, ~21 s of waiting.
BACKOFF_S: tuple[float, ...] = (1.0, 4.0, 16.0)


def _transient(error: str) -> bool:
    return any(marker in error for marker in TRANSIENT)


def _call(
    client: ExtractorClient, artifact: str, sleep: Callable[[float], None] = time.sleep
) -> tuple[list[Any], str]:
    """One call, with retries. A transient upstream failure (5xx, rate limit, transport) is
    retried with exponential backoff and reported as `upstream unavailable` if it never
    clears. A content-level failure (invalid JSON, not an array) is retried once and then
    raises: at temperature 0 it usually repeats, so waiting longer buys nothing."""
    raw = ""
    error = "no response"
    upstream = False
    attempt = 0
    while True:
        try:
            raw = client.complete(PROMPT, artifact, WIRE_SCHEMA)
            data = json.loads(raw)
        except ExtractError:
            raise
        except Exception as e:  # provider/transport error or invalid JSON
            error = f"{type(e).__name__}: {e}"
            upstream = _transient(error)
        else:
            if isinstance(data, list):
                return data, raw
            error = f"response is {type(data).__name__}, not an array"
            upstream = False
        budget = BACKOFF_S if upstream else BACKOFF_S[:1]
        if attempt >= len(budget):
            break
        if upstream:  # a content failure is retried immediately, as before
            sleep(budget[attempt])
        attempt += 1
    if upstream:  # acceptance F-7: distinct from an unusable response, so CI can tell them apart
        raise ExtractError(
            f"upstream unavailable after {attempt + 1} attempts; last error: {error}", raw=raw
        )
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


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_BY_BEFORE = re.compile(r"\bby\s+(?:[a-z]+\s+)?$", re.IGNORECASE)
_THAN_AFTER = re.compile(
    r"(?:\s+[a-z]+){0,2}\s+(?:more|less|higher|lower|faster|slower|fewer|greater|smaller"
    r"|longer|shorter|better|worse)\b",
    re.IGNORECASE,
)


_PERCENT_AFTER = re.compile(r"\s*(?:%|percent\b|pct\b|percentage points?\b)", re.IGNORECASE)


def _value_not_a_difference(claim: Comparison | Growth) -> str | None:
    """F-4 (docs/benchmark.md changelog 3). `Comparison.value` is the stated *difference*
    and `Growth.value` the stated *percentage*; the model also types a level as either
    ("to stretch to 14.28 days" as a comparison with value 14.28, or as growth of 14.28%)
    and the engine then fails 14.28 against a difference of 2.88 or a change of 25.2%.
    Fail closed: keep a stated value only when the span writes it as a difference
    ("by 2.3 days", "2.3 days lower than") or, for growth, as a percentage ("41.47%");
    otherwise reject, and the number falls to the sweep."""
    if claim.value is None:
        return None
    target = Decimal(str(claim.value))
    for m in _NUMBER.finditer(claim.span):
        try:
            if Decimal(m[0].replace(",", "")) != target:
                continue
        except InvalidOperation:
            continue
        before, after = claim.span[: m.start()], claim.span[m.end() :]
        if isinstance(claim, Growth):
            if _PERCENT_AFTER.match(after):
                return None
            return f"growth value {m[0]} is not written as a percentage: {claim.span!r}"
        if _BY_BEFORE.search(before) or _THAN_AFTER.match(after):
            return None
        return f"value {m[0]} is written as a level, not a difference: {claim.span!r}"
    return f"value {claim.value} does not appear in {claim.span!r}"


def extract_claims(
    artifact: str,
    client: ExtractorClient,
    *,
    raw_dump: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Extraction:
    try:
        items, raw = _call(client, artifact, sleep)
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
        elif isinstance(got, Comparison | Growth) and (why := _value_not_a_difference(got)):
            rejected.append(Rejected(item, "value_not_a_difference", why))
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
        unextracted_numeric=sweep(artifact, coverage(accepted)),
        raw=raw,
        model=client.model,
    )
