"""The runner end to end with the oracle client (perfect extraction): record, replay,
determinism, the missing-recording error, and the deterministic side's upper bound —
what the verifier does with every corruption once it has been handed to it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from recount.bench.runner import (
    BenchError,
    Paths,
    ThrottledClient,
    plan_calls,
    render_table,
    run_bench,
    write_readme,
)
from recount.extract import ExtractError

FIXTURE_PATHS = Paths()


def _paths(tmp: Path) -> Paths:
    return Paths(recordings=tmp / "rec")


def _stable(results: dict[str, Any]) -> dict[str, Any]:
    out = dict(results)
    for k in ("live_calls", "replays"):
        del out[k]
    return out


def test_record_then_replay_is_identical(tmp_path: Path, oracle: Any) -> None:
    paths = _paths(tmp_path)
    live = run_bench(paths, seeds=(2,), live=oracle, rpm=1e9)
    # 25 artifacts, 24 distinct: the class-7 variant replays its sibling's fresh recording
    assert live["n_artifacts"] == 25 and live["replays"] == 1
    plan = plan_calls(FIXTURE_PATHS, (2,))
    assert live["live_calls"] == plan["extract_calls"] + plan["judge_calls"]
    replay = run_bench(paths, seeds=(2,), previous=live)
    assert replay["live_calls"] == 0 and replay["replays"] > 0
    assert _stable(replay) == _stable(live)
    assert replay["latency"]["extraction_s"]["n"] == live["n_distinct_artifacts"]
    # every recording carries the latency of the call that produced it
    for f in (paths.recordings / "extract").glob("*.json"):
        assert json.loads(f.read_text())["latency_s"]


def test_missing_recording_is_an_error_not_a_skip(tmp_path: Path) -> None:
    with pytest.raises(BenchError, match="no extract recording for clean"):
        run_bench(_paths(tmp_path), seeds=(1,))


def test_oracle_upper_bound(tmp_path: Path, oracle: Any) -> None:
    """With perfect extraction every fabricated metric abstains schema_gap, class 7 is
    invariant, and every value, direction, ordinal and entity corruption is FAIL *unless
    its span names no config wording for the metric* (Stage 6, abstention M3 / fixture
    amendment F5): those abstain metric_echo_failed even when handed the corruption, which
    is the echo gate's cost with perfect extraction. Before changelog 2 three
    rounding_drift variants written with trailing zeros ("6.00%", "12.10 days", "5.00%")
    PASSed (F-1); before changelog 5 the echo rows below were all n/n. Any change here is
    a verifier change."""
    r = run_bench(_paths(tmp_path), live=oracle, rpm=1e9)
    rows = r["classes"]
    echo_gap = {  # variants drawn on c17 / c40 / c53 (F5) per class
        "wrong_figure": 1, "flipped_direction": 4, "swapped_entity": 1, "rounding_drift": 2,
        "instruction_in_data": 1,
    }  # fmt: skip
    for cls, gap in echo_gap.items():
        assert rows[cls]["detected"] == rows[cls]["n"] - gap, (cls, rows[cls])
        assert rows[cls]["abstained"] == gap and rows[cls]["false_accept"] == 0, (cls, rows[cls])
    assert rows["fabricated_metric"]["detected_by_abstention"] == rows["fabricated_metric"]["n"]
    wr = rows["wrong_ranking"]  # c36 / c41 spans name no measure: all abstain under M3
    assert (wr["detected"], wr["abstained"], wr["unextracted"], wr["false_accept"]) == (0, 15, 0, 0)
    assert rows["exact_match"]["false_accept"] == 0
    assert rows["instruction_in_data"]["invariant"] == 5
    assert rows["overall"]["collateral_false_flags"] == 0
    assert rows["overall"]["unextracted_total"] == 0
    assert r["clean"]["FAIL"] == 0 and r["clean"]["PASS"] == 41  # 56 before M3
    assert r["clean"]["judge"] == {"faithful": True, "false_flags": 0}
    assert rows["overall"]["judge_localized"] == rows["overall"]["n"]


def test_plan_counts_distinct_requests() -> None:
    plan = plan_calls(FIXTURE_PATHS, (1,))
    assert plan["artifacts"] == 25
    assert plan["extract_calls"] <= 25 and plan["judge_calls"] <= 25
    assert plan["judge_calls"] == plan["extract_calls"] + 1  # class 7: same artifact, new summary


def test_readme_table_written_between_markers(tmp_path: Path, oracle: Any) -> None:
    r = run_bench(_paths(tmp_path), seeds=(1,), live=oracle, rpm=1e9)
    table = render_table(r)
    assert "| wrong_figure |" in table and "| **overall** |" in table
    readme = tmp_path / "README.md"
    readme.write_text("# x\n<!-- BENCH:START -->\nold\n<!-- BENCH:END -->\ntail\n")
    write_readme(readme, table)
    text = readme.read_text()
    assert "old" not in text and table in text and text.endswith("<!-- BENCH:END -->\ntail\n")


class _Flaky:
    model = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        self.calls += 1
        if self.calls < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return "[]"


def test_throttle_backs_off_on_rate_limits() -> None:
    slept: list[float] = []
    inner = _Flaky()
    client = ThrottledClient(inner, 6.0, sleep=slept.append)
    assert client.complete("p", "a", {}) == "[]"
    assert inner.calls == 3 and [x for x in slept if x >= 30] == [30.0, 60.0]
    assert len(client.latencies) == 1

    class _Broken:
        model = "b"

        def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
            raise ExtractError("no key")

    with pytest.raises(ExtractError):
        ThrottledClient(_Broken(), 0.0, sleep=slept.append).complete("p", "a", {})
