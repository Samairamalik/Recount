"""Extraction (probabilistic zone). The only package that may import an LLM client."""

from recount.extract.client import (
    MODEL,
    ClaimsFileClient,
    ExtractError,
    ExtractorClient,
    GeminiClient,
    MockClient,
    RecordingClient,
    fingerprint,
    resolve_api_key,
)
from recount.extract.extractor import (
    WIRE_SCHEMA,
    Extraction,
    Rejected,
    extract_claims,
    wire_schema,
)
from recount.extract.prompt import PROMPT
from recount.extract.sweep import (
    Coverage,
    NumericToken,
    coverage,
    numeric_tokens,
    span_intervals,
    sweep,
)

__all__ = [
    "MODEL",
    "Coverage",
    "PROMPT",
    "WIRE_SCHEMA",
    "ClaimsFileClient",
    "ExtractError",
    "Extraction",
    "ExtractorClient",
    "GeminiClient",
    "MockClient",
    "NumericToken",
    "RecordingClient",
    "Rejected",
    "coverage",
    "extract_claims",
    "fingerprint",
    "numeric_tokens",
    "resolve_api_key",
    "span_intervals",
    "sweep",
    "wire_schema",
]
