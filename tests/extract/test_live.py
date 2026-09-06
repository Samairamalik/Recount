"""The one live test. Skipped unless RECOUNT_LIVE=1; CI never sets it and never has a key."""

from __future__ import annotations

import os

import pytest

from recount.extract import GeminiClient, extract_claims

pytestmark = pytest.mark.skipif(
    os.environ.get("RECOUNT_LIVE") != "1", reason="set RECOUNT_LIVE=1 to call the provider"
)

TINY = (
    "# 2019 widget review\n\nThe North region sold 4,120 units in the first quarter, "
    "up 12.5% quarter-over-quarter, and led all regions."
)


def test_live_extraction_accepts_the_derived_schema() -> None:
    ex = extract_claims(TINY, GeminiClient())
    assert ex.model == "gemini-3.6-flash"
    assert ex.claims, ex.rejected
    assert all(c.span in TINY for c in ex.claims)
    assert {c.type for c in ex.claims} >= {"point_value", "growth"}
