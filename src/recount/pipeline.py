"""End-to-end: raw report -> extract -> compile -> verify, in one call.

This module sits on the deterministic side of the wall: it imports the extractor's
public seam (`recount.extract`), never an LLM client. Which client runs is the caller's
choice, so the whole pipeline replays offline from a recording. `verify_text` is the
one orchestration the CLI, the promptfoo assertion and the Action share: it picks the
client (claims file, recording, or live), times the stages, and never lets one crashed
claim discard the others.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from recount.config import SemanticConfig, load_config
from recount.extract import (
    ClaimsFileClient,
    Extraction,
    ExtractorClient,
    MockClient,
    extract_claims,
)
from recount.io import Dataset, load_dataset
from recount.report.json_out import RunRecord
from recount.verify import Verdict, VerifyError, verify_claim


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


class PartialFailure(Exception):
    """One or more claims crashed the engine (a system error); the record still carries
    every other verdict. The CLI emits the partial results and exits 2."""

    def __init__(self, record: RunRecord, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.record = record
        self.errors = errors


def _error_verdict(claim_id: str, error: Exception) -> Verdict:
    return Verdict(
        claim_id=claim_id,
        verdict="UNVERIFIABLE",
        claimed_value=None,
        computed_value=None,
        delta=None,
        policy="error",
        detail=f"{type(error).__name__}: {error}",
        sql="",
        params={},
        row_counts={},
        abstain_reason=None,
    )


def pick_client(
    artifact: str,
    *,
    claims: Path | None = None,
    recording: Path | None = None,
    recordings: Path | None = None,
    model: str | None = None,
) -> ExtractorClient:
    """Offline first: a claims file (FR-015), a recording, a recordings directory keyed
    like the benchmark's (sha256 of the artifact, 16 hex chars); else the live client,
    imported only here so a keyless run never touches the provider module."""
    if claims is not None:
        return ClaimsFileClient(claims)
    if recording is not None:
        return MockClient(recording)
    if recordings is not None:
        key = hashlib.sha256(artifact.encode()).hexdigest()[:16]
        path = recordings / f"{key}.json"
        if not path.is_file():
            raise FileNotFoundError(f"no recording for this artifact: {path}")
        return MockClient(path)
    from recount.extract import GeminiClient

    return GeminiClient() if model is None else GeminiClient(model=model)


def verify_text(
    artifact: str,
    *,
    data: Path,
    config: Path,
    strict: bool = False,
    claims: Path | None = None,
    recording: Path | None = None,
    recordings: Path | None = None,
    model: str | None = None,
    raw_dump: Path | None = None,
    artifact_path: str = "<text>",
) -> RunRecord:
    """Load, extract, verify; return the run record. Raises LoadError / ValidationError /
    ExtractError / FileNotFoundError for system errors before any verdict exists, and
    PartialFailure (carrying the record) when a claim crashed the engine."""
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    cfg = load_config(config)
    ds = load_dataset(data, cfg)
    timings["load"] = round(time.perf_counter() - t0, 4)

    t1 = time.perf_counter()
    client = pick_client(artifact, claims=claims, recording=recording, recordings=recordings,
                         model=model)  # fmt: skip
    extraction = extract_claims(artifact, client, raw_dump=raw_dump)
    timings["extract"] = round(time.perf_counter() - t1, 4)

    t2 = time.perf_counter()
    verdicts: list[Verdict] = []
    errors: list[str] = []
    for claim in extraction.claims:
        try:
            verdicts.append(verify_claim(ds, claim, cfg))
        except (VerifyError, Exception) as e:  # partial results are always emitted (§1.12)
            errors.append(f"{claim.id}: {type(e).__name__}: {e}")
            verdicts.append(_error_verdict(claim.id, e))
    timings["verify"] = round(time.perf_counter() - t2, 4)

    record = RunRecord(
        artifact=artifact,
        artifact_path=artifact_path,
        dataset_path=str(data),
        config_path=str(config),
        claims=extraction.claims,
        verdicts=tuple(verdicts),
        extraction=extraction,
        timings_s=timings,
        strict=strict,
    )
    if errors:
        raise PartialFailure(record, errors)
    return record
