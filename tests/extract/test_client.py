"""Clients: key resolution, recording round-trip, stale-recording refusal. No network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from recount.extract import (
    MODEL,
    ExtractError,
    GeminiClient,
    MockClient,
    RecordingClient,
    fingerprint,
    resolve_api_key,
)

SCHEMA: dict[str, Any] = {"type": "array"}


class FakeInner:
    model = "fake"

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        self.calls += 1
        return self.responses.pop(0)


def test_key_from_environment_wins(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=from-file\n")
    assert resolve_api_key({"GEMINI_API_KEY": "from-env"}, dotenv) == "from-env"


def test_key_from_dotenv_strips_quotes(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("# comment\nOTHER=1\nGEMINI_API_KEY = 'from-file'\n")
    assert resolve_api_key({}, dotenv) == "from-file"


def test_missing_key_is_an_extract_error(tmp_path: Path) -> None:
    with pytest.raises(ExtractError, match="GEMINI_API_KEY"):
        resolve_api_key({}, tmp_path / ".env")


def test_gemini_client_pins_the_spike_model_and_temperature_zero() -> None:
    client = GeminiClient(api_key="not-a-real-key")  # construction never touches the network
    assert client.model == MODEL == "gemini-3.6-flash"
    src = Path("src/recount/extract/client.py").read_text()
    assert "temperature=0.0" in src and "response_json_schema=schema" in src


def test_recording_round_trips_through_mock(tmp_path: Path) -> None:
    inner = FakeInner("first", "second")
    rec = RecordingClient(inner)
    assert rec.complete("p", "a", SCHEMA) == "first"
    assert rec.complete("p", "a", SCHEMA) == "second"
    path = tmp_path / "rec.json"
    rec.save(path)

    data = json.loads(path.read_text())
    assert data["responses"] == ["first", "second"]
    assert {k: data[k] for k in fingerprint("", "", "", {})} == fingerprint(
        "fake", "p", "a", SCHEMA
    )

    mock = MockClient(path)
    assert mock.model == "fake"
    assert mock.complete("p", "a", SCHEMA) == "first"
    assert mock.complete("p", "a", SCHEMA) == "second"
    with pytest.raises(ExtractError, match="no response left"):
        mock.complete("p", "a", SCHEMA)


@pytest.mark.parametrize(
    ("prompt", "artifact", "schema", "changed"),
    [
        ("p2", "a", SCHEMA, "prompt_sha256"),
        ("p", "a2", SCHEMA, "artifact_sha256"),
        ("p", "a", {"type": "object"}, "schema_sha256"),
    ],
)
def test_mock_refuses_a_stale_recording(
    tmp_path: Path, prompt: str, artifact: str, schema: dict[str, Any], changed: str
) -> None:
    rec = RecordingClient(FakeInner("x"))
    rec.complete("p", "a", SCHEMA)
    path = tmp_path / "rec.json"
    rec.save(path)
    with pytest.raises(ExtractError, match=changed):
        MockClient(path).complete(prompt, artifact, schema)


def test_one_recording_covers_one_input() -> None:
    rec = RecordingClient(FakeInner("x", "y"))
    rec.complete("p", "a", SCHEMA)
    with pytest.raises(ExtractError, match="one recording"):
        rec.complete("p", "other artifact", SCHEMA)


def test_saving_nothing_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ExtractError, match="nothing recorded"):
        RecordingClient(FakeInner()).save(tmp_path / "x.json")
