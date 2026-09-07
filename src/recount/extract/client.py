"""Extractor clients (probabilistic zone: the only module that imports an LLM client).

`ExtractorClient` is the seam: it turns (prompt, artifact, response schema) into raw
text and nothing else. `GeminiClient` is the live implementation; `MockClient` replays
a recording and refuses to replay a stale one, so CI never needs a key and a prompt
edit can never silently reuse an old response. `RecordingClient` wraps a live client
to produce those recordings.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from google import genai
from google.genai import types

MODEL = "gemini-3.6-flash"  # the spike's working model; pinned
ENV_KEY = "GEMINI_API_KEY"


class ExtractError(Exception):
    """Extraction could not produce claims: no key, transport failure, or invalid output
    twice. `raw` carries the model's last output, if any, for post-mortem."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class ExtractorClient(Protocol):
    model: str

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        """One call. The artifact is appended to the prompt; returns the raw response text."""
        ...


def resolve_api_key(env: Mapping[str, str] = os.environ, dotenv: Path = Path(".env")) -> str:
    """GEMINI_API_KEY from the environment, else from a KEY=value line in `.env`."""
    key = env.get(ENV_KEY, "")
    if not key and dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == ENV_KEY:
                key = value.strip().strip("\"'")
    if not key:
        raise ExtractError(f"{ENV_KEY} is not set (environment or {dotenv})")
    return key


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key or resolve_api_key())

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt + "\n---\n" + artifact,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        return response.text or ""


def fingerprint(model: str, prompt: str, artifact: str, schema: dict[str, Any]) -> dict[str, str]:
    """What a recording is valid for. Any change to any of the four invalidates it."""

    def sha(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    return {
        "model": model,
        "prompt_sha256": sha(prompt),
        "artifact_sha256": sha(artifact),
        "schema_sha256": sha(json.dumps(schema, sort_keys=True)),
    }


class MockClient:
    """Replays a recording made by `RecordingClient`, one response per call, in order."""

    def __init__(self, recording: Path) -> None:
        self.path = recording
        data = json.loads(recording.read_text())
        self.model: str = data["model"]
        self._expected: dict[str, str] = {k: data[k] for k in fingerprint("", "", "", {})}
        self._responses: list[str] = list(data["responses"])

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        actual = fingerprint(self.model, prompt, artifact, schema)
        stale = [k for k, v in actual.items() if self._expected[k] != v]
        if stale:
            raise ExtractError(
                f"recording {self.path} is stale ({', '.join(stale)} changed);"
                " re-record it with `python -m recount.extract.record`"
            )
        if not self._responses:
            raise ExtractError(f"recording {self.path} has no response left for this call")
        return self._responses.pop(0)


class ClaimsFileClient:
    """The fully offline path (FR-015): `--claims claims.json` is "the response". The file
    goes through the same validation and post-checks as a live response, so a hand-written
    claim whose span is not verbatim in the artifact is rejected like any other."""

    model = "claims-file"

    def __init__(self, path: Path) -> None:
        self.path = path

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        return self.path.read_text()


class RecordingClient:
    """Delegates to a live client and keeps every raw response; `save()` writes the recording."""

    def __init__(self, inner: ExtractorClient) -> None:
        self._inner = inner
        self.model = inner.model
        self._fingerprint: dict[str, str] | None = None
        self._responses: list[str] = []

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        fp = fingerprint(self.model, prompt, artifact, schema)
        if self._fingerprint not in (None, fp):
            raise ExtractError(
                "one recording covers one (prompt, artifact, schema); start a new one"
            )
        self._fingerprint = fp
        text = self._inner.complete(prompt, artifact, schema)
        self._responses.append(text)
        return text

    def save(self, path: Path) -> None:
        if self._fingerprint is None:
            raise ExtractError("nothing recorded")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**self._fingerprint, "responses": self._responses}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
