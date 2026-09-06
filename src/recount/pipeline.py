"""End-to-end: raw report -> extract -> compile -> verify, in one call.

This module sits on the deterministic side of the wall: it imports the extractor's
public seam (`recount.extract`), never an LLM client. Which client runs is the caller's
choice, so the whole pipeline replays offline from a recording.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from recount.config import SemanticConfig
from recount.extract import Extraction, ExtractorClient, extract_claims
from recount.io import Dataset
from recount.verify import Verdict, verify_claim


@dataclass(frozen=True)
class RunResult:
    extraction: Extraction
    verdicts: tuple[Verdict, ...]  # one per accepted claim, in claim order


def run(
    artifact: str,
    cfg: SemanticConfig,
    dataset: Dataset,
    client: ExtractorClient,
    *,
    raw_dump: Path | None = None,
) -> RunResult:
    extraction = extract_claims(artifact, client, raw_dump=raw_dump)
    verdicts = tuple(verify_claim(dataset, claim, cfg) for claim in extraction.claims)
    return RunResult(extraction=extraction, verdicts=verdicts)
