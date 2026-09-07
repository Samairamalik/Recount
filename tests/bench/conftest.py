"""Shared fixtures for the benchmark tests, all keyless.

`OracleClient` stands in for the extractor and the judge: it replays the Stage 4 clean
recording and, for a variant, rewrites the recorded claim that covers the corrupted span
so it states the corruption exactly. That is "perfect extraction": what the deterministic
side does with a corruption it has been handed. It is a plumbing and upper-bound
fixture, never a substitute for the recorded live run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from recount.bench.corrupt import Suite, Variant, generate
from recount.config import SemanticConfig, load_config

FIXTURES = Path("tests/fixtures")
CLEAN = Path("spike/report_clean.md")
DATASET = Path("examples/olist/orders.parquet")
CLEAN_RECORDING = FIXTURES / "extract" / "report_clean.json"


@pytest.fixture(scope="session")
def cfg() -> SemanticConfig:
    """The frozen suite config (bench/suite_config.yml, the Stage 5 vocabulary): the suite's
    pools read config aliases, so generation must never follow the live config
    (docs/benchmark.md changelog 7). Entities are identical, so scoring uses it too."""
    return load_config(Path("bench/suite_config.yml"))


@pytest.fixture(scope="session")
def clean_text() -> str:
    return CLEAN.read_text()


@pytest.fixture(scope="session")
def suite(labels: dict[str, Any], cfg: SemanticConfig, clean_text: str) -> Suite:
    return generate(clean_text, labels["claims"], cfg, DATASET)


def _diff_window(a: str, b: str) -> tuple[int, int, int]:
    """Minimal changed region of `a` when rewritten to `b`: (start, end, delta)."""
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(len(a), len(b)) - p and a[-1 - s] == b[-1 - s]:
        s += 1
    return p, len(a) - s, len(b) - len(a)


class OracleClient:
    """Perfect extraction from the clean recording; a judge that always localizes."""

    model = "oracle"

    def __init__(self, suite: Suite, clean_text: str) -> None:
        self._clean = clean_text
        self._by_text = {v.artifact: v for v in suite.variants}
        self._items: list[dict[str, Any]] = json.loads(
            json.loads(CLEAN_RECORDING.read_text())["responses"][0]
        )

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        if "faithful" in schema.get("properties", {}):
            report = artifact.split("\n\n# Data summary\n\n", 1)[0].removeprefix("# Report\n\n")
            v = self._by_text.get(report)
            if v is None:
                return json.dumps({"faithful": True, "problems": []})
            return json.dumps(
                {"faithful": False, "problems": [{"span": v.corrupted_span, "reason": "oracle"}]}
            )
        v = self._by_text.get(artifact)
        if v is None:
            return json.dumps(self._items)
        return json.dumps(self._rewrite(v))

    def _rewrite(self, v: Variant) -> list[dict[str, Any]]:
        i = self._clean.index(v.original_span)
        p, q, delta = _diff_window(v.original_span, v.corrupted_span)
        a, b = i + p, i + q  # changed region in clean coordinates
        out: list[dict[str, Any]] = []
        for item in self._items:
            s = self._clean.find(item["span"])
            e = s + len(item["span"])
            if e <= a or s >= b:  # untouched claim
                out.append(item)
                continue
            if not (s <= a and e >= b):  # partial overlap: the oracle cannot rewrite it
                continue
            new = dict(item)
            # A span inside the rewritten span becomes the whole corrupted span, which is
            # unique in the artifact by construction (B7); swapped_entity reuses a number
            # that occurs elsewhere, so a bare "5,240 orders" would be a duplicate span.
            shifted = v.artifact[s : e + delta]
            inside = s >= i and e <= i + len(v.original_span)
            new["span"] = (
                shifted if v.artifact.count(shifted) == 1 or not inside else v.corrupted_span
            )
            c = v.corrupted
            if v.cls == "flipped_direction":
                if new.get("direction") is not None:
                    new["direction"] = c["direction"][0]
            elif v.cls == "wrong_ranking":
                if new.get("rank") is not None:
                    new["rank"] = c["rank"]
                    if "subject" in c:
                        new["subject"] = c["subject"]
            elif new.get("value") == v.original.get("value"):
                new["value"] = c["value"]
                if v.cls == "fabricated_metric":
                    new["metric"] = c["metric"]
            out.append(new)
        return out


@pytest.fixture
def oracle(suite: Suite, clean_text: str) -> OracleClient:
    return OracleClient(suite, clean_text)
