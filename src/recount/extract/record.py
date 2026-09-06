"""Record a live extraction so tests can replay it without a key.

    python -m recount.extract.record spike/report.md tests/fixtures/extract/report.json

One live call (plus at most one retry) per artifact. The recording is bound to the
model, the prompt, the artifact and the wire schema; MockClient refuses a stale one.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from recount.extract.client import GeminiClient, RecordingClient
from recount.extract.extractor import extract_claims


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    client = RecordingClient(GeminiClient())
    extraction = extract_claims(args.artifact.read_text(), client)
    client.save(args.out)
    print(
        f"{args.out}: {len(extraction.claims)} claims accepted,"
        f" {len(extraction.rejected)} rejected,"
        f" {len(extraction.unextracted_numeric)} numeric tokens unextracted"
    )


if __name__ == "__main__":
    main()
