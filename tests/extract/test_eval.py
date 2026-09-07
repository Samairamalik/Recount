"""The extraction mini-eval: the matching policy on a miniature, then the recorded runs
against the 57 labels. The recorded numbers are the ones docs/eval.md reports; if they
drift, the doc is stale and this test says so. Both recordings were re-made in Stage 5
after the wire schema made every key required (docs/benchmark.md §6, changelog 1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from recount.claims import ClaimAdapter
from recount.config import load_config
from recount.extract import Extraction, MockClient, extract_claims
from recount.extract.eval import EvalReport, evaluate
from recount.io import load_dataset

CFG = load_config(Path("tests/fixtures/olist_metrics.yml"))
RECORDING = Path("tests/fixtures/extract/report.json")
LITE_RECORDING = Path("tests/fixtures/extract/report.flash-lite.json")  # the benchmark model


def _claim(**fields: Any) -> Any:
    return ClaimAdapter.validate_python({"confidence": "high", **fields})


def _label(**fields: Any) -> dict[str, Any]:
    return {"claim": {"confidence": "high", **fields}, "expected_verdict": "PASS"}


MINI = "Revenue grew 8% to 1,200 across 900 orders in 2017, with 5 states served."
MINI_LABELS = [
    _label(id="l1", type="growth", span="Revenue grew 8%", metric="revenue", value=8,
           direction="increase", period="2017", baseline_period="2016"),
    _label(id="l2", type="point_value", span="to 1,200", metric="revenue", value=1200,
           period="2017"),
    _label(id="l3", type="point_value", span="across 900 orders", metric="orders", value=900,
           period="2017"),
    _label(id="l4", type="point_value", span="with 5 states served", metric="state_count", value=5,
           period="2017"),
]  # fmt: skip


def _mini_extraction(*claims: Any, artifact: str = MINI) -> Extraction:
    from recount.extract import coverage, sweep

    return Extraction(
        claims=tuple(claims),
        rejected=(),
        unextracted_numeric=sweep(artifact, coverage(claims)),
        raw="",
        model="test",
    )


def test_matching_policy_merged_missed_spurious() -> None:
    merged_span = _claim(  # one span covering l1 and l2: matches l1 (larger overlap), l2 is merged
        id="x1", type="growth", span="Revenue grew 8% to 1,200", metric="total revenue",
        value=8.0, direction="increase", period="2017", baseline_period="2016",
    )  # fmt: skip
    ok = _claim(id="x2", type="point_value", span="900 orders", metric="order volume", value=900,
                period="2017")  # fmt: skip
    extra = _claim(id="x3", type="point_value", span="in 2017", metric="revenue", value=None,
                   period="2017")  # fmt: skip
    rep = evaluate(MINI, MINI_LABELS, _mini_extraction(merged_span, ok, extra), CFG)

    assert [(m.label_id, m.claim_id) for m in rep.matched] == [("l1", "x1"), ("l3", "x2")]
    assert rep.merged == ("l2",)
    assert rep.missed == ("l4",)
    assert rep.spurious == ("x3",)
    assert rep.precision == 2 / 3 and rep.recall == 2 / 4
    assert rep.span_validity == 1.0 and rep.overlapping_claims == 0
    # aliases resolve through the config, so "total revenue" binds as "revenue"
    assert rep.binding_accuracy("metric") == (2, 2)
    assert rep.binding_accuracy("direction") == (1, 1)
    assert rep.binding_accuracy("value") == (2, 2)
    # l4's number is uncovered, so the sweep reports it; l2's number sits inside x1's span
    assert rep.sweep_flagged == ("l4",) and rep.sweep_silent == ()
    assert rep.verdicts == ()  # no dataset given


def test_misbinding_is_counted_per_field() -> None:
    wrong = _claim(id="x1", type="point_value", span="across 900 orders", metric="revenue",
                   value=900, period="2017-Q1")  # fmt: skip
    rep = evaluate(MINI, MINI_LABELS, _mini_extraction(wrong), CFG)
    bad = {f.field for f in rep.fields if not f.ok}
    assert bad == {"metric", "period"}
    assert rep.binding_accuracy("value") == (1, 1) and rep.binding_accuracy("type") == (1, 1)


def test_unresolvable_on_both_sides_is_the_same_abstention() -> None:
    """Label metric 'state_count' is not in the config; neither is 'states'. The compiler
    abstains schema_gap on both, so the binding counts as equal only when both are unresolved
    to the same token, never when one resolves and the other does not."""
    same = _claim(id="x1", type="point_value", span="with 5 states served", metric="state_count",
                  value=5, period="2017")  # fmt: skip
    other = _claim(id="x1", type="point_value", span="with 5 states served", metric="states",
                   value=5, period="2017")  # fmt: skip
    assert evaluate(MINI, MINI_LABELS, _mini_extraction(same), CFG).binding_accuracy("metric") == (
        1,
        1,
    )
    assert evaluate(MINI, MINI_LABELS, _mini_extraction(other), CFG).binding_accuracy("metric") == (
        0,
        1,
    )


def test_label_span_missing_from_artifact_is_a_fixture_error() -> None:
    with pytest.raises(ValueError, match="l1: span not in artifact"):
        evaluate("nothing here", MINI_LABELS[:1], _mini_extraction(artifact="nothing here"), CFG)


# ------------------------------------------------- the recorded Stage 4 eval


@pytest.fixture(scope="module")
def recorded(labels: dict[str, Any]) -> EvalReport:
    artifact = Path(labels["report"]).read_text()
    extraction = extract_claims(artifact, MockClient(RECORDING))
    dataset = load_dataset(Path("examples/olist/orders.parquet"), CFG)
    return evaluate(artifact, labels["claims"], extraction, CFG, dataset)


def test_recorded_span_validity_is_total_by_construction(labels: dict[str, Any]) -> None:
    artifact = Path(labels["report"]).read_text()
    extraction = extract_claims(artifact, MockClient(RECORDING))
    assert all(c.span in artifact for c in extraction.claims)
    assert extraction.rejected == ()
    assert len(extraction.claims) == 63


def test_recorded_numbers_match_docs_eval_md(recorded: EvalReport) -> None:
    s = recorded.summary()
    assert (s["labels"], s["claims"], s["matched"], s["merged"], s["missed"], s["spurious"]) == (
        57, 63, 55, 0, 2, 8
    )  # fmt: skip
    assert s["recall"] == 0.9649 and s["precision"] == 0.873
    assert s["span_validity"] == 1.0
    assert recorded.missed == ("c1", "c30")
    assert s["binding"]["metric"] == (55, 55)
    assert s["binding"]["period"] == (55, 55)
    assert s["binding"]["subject"] == (28, 28)
    assert s["binding"]["direction"] == (10, 10)
    assert s["binding"]["type"] == (53, 55)
    assert s["binding"]["value"] == (47, 50)
    # Stage 6 (abstention M3): matched claims whose span names no config wording for the
    # metric now abstain metric_echo_failed; the extractor recording is unchanged. Was
    # {"agree": 54, "other": 1} in Stage 5, {44, 11} at changelog 5, {46, 9} once changelog 7
    # aliased "days for delivery" (docs/eval.md, Stage 6 addendum).
    assert s["verdicts"] == {"agree": 46, "false_accept": 0, "false_flag": 0, "other": 9}


def test_recorded_sweep_catches_the_numeric_miss(recorded: EvalReport) -> None:
    assert recorded.sweep_flagged == ("c1",) and recorded.sweep_silent == ()


def test_recorded_flash_lite_numbers_match_docs_eval_md(labels: dict[str, Any]) -> None:
    """The benchmark's extraction model (docs/eval.md, Stage 5 addendum): the honesty
    gate was recall >= 0.85 and precision 1.0."""
    artifact = Path(labels["report"]).read_text()
    extraction = extract_claims(artifact, MockClient(LITE_RECORDING))
    assert extraction.model == "gemini-3.1-flash-lite"
    assert len(extraction.claims) == 51
    assert sorted(r.reason for r in extraction.rejected) == ["foreign_field"] * 4
    dataset = load_dataset(Path("examples/olist/orders.parquet"), CFG)
    rep = evaluate(artifact, labels["claims"], extraction, CFG, dataset)
    s = rep.summary()
    assert (s["matched"], s["merged"], s["missed"], s["spurious"]) == (51, 1, 5, 0)
    assert s["recall"] == 0.8947 and s["precision"] == 1.0 and s["span_validity"] == 1.0
    assert rep.missed == ("c1", "c18", "c24", "c29", "c30") and rep.merged == ("c28",)
    assert s["binding"]["subject"] == (28, 28) and s["binding"]["metric"] == (45, 51)
    # Stage 5: {"agree": 47, "other": 4}; Stage 6 M3 abstains three more (docs/eval.md).
    assert s["verdicts"] == {"agree": 44, "false_accept": 0, "false_flag": 0, "other": 7}
    assert rep.sweep_flagged == ("c1", "c18", "c24", "c29") and rep.sweep_silent == ()


def test_iteration_1_recording_is_kept_only_as_numbers() -> None:
    """The pre-fix recording is not a fixture; its numbers live in docs/eval.md."""
    doc = Path("docs/eval.md").read_text()
    assert "0.9123" in doc and "0.9649" in doc
    assert json.loads(RECORDING.read_text())["model"] == "gemini-3.6-flash"
