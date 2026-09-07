"""Numeric sweep (deterministic): every number in the artifact that no accepted claim
verifies is reported as unextracted, so a missed claim is a visible gap, never a
silent one.

Token-to-field coverage (Stage 6, docs/benchmark.md changelog 4): a numeric token inside an
accepted span is covered only if it equals one of that claim's bound values (`value`, or
`rank`); a second number a span merely encloses ("expanded by 41.47% to peak at 17,280
orders" extracted as one growth claim) is flagged, because nothing verifies it.

Recognised tokens: optional currency prefix (R$, $, €, £, ₹), Western (1,447,714.17)
and Indian (1,41,834) digit grouping, decimals, a % sign, K/M/B/bn/mn suffixes. Bare
four-digit integers in 1900-2099 with no prefix, suffix, separator or decimal are
years, not quantities, and are skipped. Numbers written as words ("two-fifths",
"two weeks") are out of scope: the sweep is a token scanner, not a reader.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from recount.claims import Claim

_TOKEN = re.compile(
    r"""
    (?<![\w.,])                                   # not glued to a word, "Q3", or "1.2.3"
    (?P<prefix>R\$|US\$|\$|€|£|₹)?
    (?P<number>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?     # grouped: 43,428 / 1,41,834 / 2,747,559.5
             |\d+(?:\.\d+)?)                      # plain: 12.4 / 43428
    (?P<suffix>%|[KMB]\b|bn\b|mn\b)?
    (?!\w)
    """,
    re.VERBOSE,
)
_NEXT_WORD = re.compile(r"\s+([A-Za-z]+)")
_SCALE = {"K": 1e3, "M": 1e6, "B": 1e9, "bn": 1e9, "mn": 1e6}

Coverage = tuple[str, tuple[float, ...]]  # (accepted span, the values its claim binds)


@dataclass(frozen=True)
class NumericToken:
    text: str  # the token as written, e.g. "R$1,447,714.17" or "12.4%"
    start: int  # character offsets in the artifact, half-open
    end: int
    context: str  # the token plus the following word, e.g. "9.3 days"
    value: float  # the token as a number: "1.2M" -> 1200000.0, "12.4%" -> 12.4


def numeric_tokens(artifact: str) -> tuple[NumericToken, ...]:
    tokens: list[NumericToken] = []
    for m in _TOKEN.finditer(artifact):
        number = m["number"]
        if (
            m["prefix"] is None
            and m["suffix"] is None
            and number.isdigit()
            and len(number) == 4
            and 1900 <= int(number) <= 2099
        ):
            continue  # a year
        after = _NEXT_WORD.match(artifact, m.end())
        context = m[0] + (" " + after[1] if after else "")
        value = float(number.replace(",", "")) * _SCALE.get(m["suffix"] or "", 1.0)
        tokens.append(NumericToken(m[0], m.start(), m.end(), context, value))
    return tuple(tokens)


def coverage(claims: Iterable[Claim]) -> tuple[Coverage, ...]:
    """What each accepted claim covers: its span and the numbers it binds."""
    out: list[Coverage] = []
    for c in claims:
        bound = [float(v) for v in (getattr(c, "value", None), getattr(c, "rank", None))
                 if v is not None]  # fmt: skip
        out.append((c.span, tuple(bound)))
    return tuple(out)


def span_intervals(artifact: str, spans: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    """Every occurrence of every span; a span may occur more than once."""
    out: list[tuple[int, int]] = []
    for span in spans:
        i = artifact.find(span)
        while i >= 0:
            out.append((i, i + len(span)))
            i = artifact.find(span, i + 1)
    return tuple(out)


def sweep(artifact: str, covered: Iterable[Coverage]) -> tuple[NumericToken, ...]:
    """Numeric tokens that no accepted claim verifies: outside every span occurrence, or
    inside one without equalling a value that claim binds."""
    fields = [
        (a, b, values) for span, values in covered for a, b in span_intervals(artifact, (span,))
    ]
    return tuple(
        t
        for t in numeric_tokens(artifact)
        if not any(
            a <= t.start and t.end <= b and any(math.isclose(t.value, v) for v in values)
            for a, b, values in fields
        )
    )
