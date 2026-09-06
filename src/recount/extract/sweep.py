"""Numeric sweep (deterministic): every number in the artifact that no accepted claim's
span covers is reported as unextracted, so a missed claim is a visible gap, never a
silent one.

Recognised tokens: optional currency prefix (R$, $, €, £, ₹), Western (1,447,714.17)
and Indian (1,41,834) digit grouping, decimals, a % sign, K/M/B/bn/mn suffixes. Bare
four-digit integers in 1900-2099 with no prefix, suffix, separator or decimal are
years, not quantities, and are skipped. Numbers written as words ("two-fifths",
"two weeks") are out of scope: the sweep is a token scanner, not a reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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


@dataclass(frozen=True)
class NumericToken:
    text: str  # the token as written, e.g. "R$1,447,714.17" or "12.4%"
    start: int  # character offsets in the artifact, half-open
    end: int
    context: str  # the token plus the following word, e.g. "9.3 days"


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
        tokens.append(NumericToken(m[0], m.start(), m.end(), context))
    return tuple(tokens)


def span_intervals(artifact: str, spans: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    """Every occurrence of every span; a span may occur more than once."""
    out: list[tuple[int, int]] = []
    for span in spans:
        i = artifact.find(span)
        while i >= 0:
            out.append((i, i + len(span)))
            i = artifact.find(span, i + 1)
    return tuple(out)


def sweep(artifact: str, spans: tuple[str, ...]) -> tuple[NumericToken, ...]:
    """Numeric tokens not inside any occurrence of any accepted span."""
    covered = span_intervals(artifact, spans)
    return tuple(
        t
        for t in numeric_tokens(artifact)
        if not any(a <= t.start and t.end <= b for a, b in covered)
    )
