"""The run record: what `recount verify --json` writes and every other reporter reads.

An audit record (docs/design.md): input hashes, tool and extractor-model versions, summary
counts, every accepted claim next to its verdict, every rejected wire object, every
unextracted numeric token, and per-stage timings. Nothing else is persisted: no dataset
contents (a hash only), no API keys, no request payloads.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recount import __version__
from recount.claims import Claim
from recount.extract import Extraction
from recount.verify import Verdict


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class RunRecord:
    artifact: str
    artifact_path: str
    dataset_path: str
    config_path: str
    claims: tuple[Claim, ...]
    verdicts: tuple[Verdict, ...]
    extraction: Extraction
    timings_s: dict[str, float]
    strict: bool

    @property
    def counts(self) -> dict[str, int]:
        labels = [v.verdict for v in self.verdicts]
        return {
            "PASS": labels.count("PASS"),
            "FAIL": labels.count("FAIL"),
            "UNVERIFIABLE": labels.count("UNVERIFIABLE"),
            "rejected": len(self.extraction.rejected),
            "unextracted_numeric": len(self.extraction.unextracted_numeric),
        }

    def exit_code(self) -> int:
        """Exit-code contract (docs/cli.md): 0 = no FAIL, 1 = any FAIL; --strict also fails on
        UNVERIFIABLE or on an unextracted numeric token. 2 is reserved for system errors
        (raised, not here)."""
        c = self.counts
        if c["FAIL"]:
            return 1
        if self.strict and (c["UNVERIFIABLE"] or c["unextracted_numeric"]):
            return 1
        return 0


def run_record(
    rec: RunRecord, *, dataset_sha256: str | None = None, config_sha256: str | None = None
) -> dict[str, Any]:
    """Serializable run record. Hashes of the dataset and config are computed from the
    files when not given (tests pass them in)."""
    return {
        "recount_version": __version__,
        "extractor_model": rec.extraction.model,
        "artifact_path": rec.artifact_path,
        "artifact_sha256": sha256_text(rec.artifact),
        "dataset_path": rec.dataset_path,
        "dataset_sha256": dataset_sha256 or sha256_file(Path(rec.dataset_path)),
        "config_path": rec.config_path,
        "config_sha256": config_sha256 or sha256_file(Path(rec.config_path)),
        "strict": rec.strict,
        "exit_code": rec.exit_code(),
        "summary": rec.counts,
        "timings_s": rec.timings_s,
        "claims": [c.model_dump(mode="json") for c in rec.claims],
        "verdicts": [v.model_dump(mode="json") for v in rec.verdicts],
        "rejected": [
            {"reason": r.reason, "detail": r.detail, "raw": r.raw} for r in rec.extraction.rejected
        ],
        "unextracted_numeric": [
            {"text": t.text, "start": t.start, "end": t.end, "context": t.context}
            for t in rec.extraction.unextracted_numeric
        ],
    }
