"""Generator contract (docs/benchmark.md B1–B8, per-class table): determinism, one span
per variant, format and tolerance invariants, pools, the composite class 7."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from recount.bench.corrupt import (
    INSTRUCTIONS,
    RANKING_ENTITY_WINDOW,
    Suite,
    generate,
    inject,
    pools,
)
from recount.config import SemanticConfig, metric_index, norm

DATASET = Path("examples/olist/orders.parquet")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
VALUE_CLASSES = ("wrong_figure", "swapped_entity", "rounding_drift", "instruction_in_data")


def test_same_seed_is_byte_identical(
    suite: Suite, labels: dict[str, Any], cfg: SemanticConfig, clean_text: str
) -> None:
    again = generate(clean_text, labels["claims"], cfg, DATASET)
    assert again.sha256 == suite.sha256
    assert [v.artifact for v in again.variants] == [v.artifact for v in suite.variants]
    one = generate(clean_text, labels["claims"], cfg, DATASET, seeds=(3,))
    assert [v.manifest() for v in one.variants] == [
        v.manifest() for v in suite.variants if v.seed == 3
    ]


def test_suite_shape(suite: Suite) -> None:
    assert len(suite.variants) == 120
    assert Counter(v.cls for v in suite.variants) == {
        "wrong_figure": 20,
        "flipped_direction": 20,
        "wrong_ranking": 15,
        "swapped_entity": 20,
        "fabricated_metric": 20,
        "rounding_drift": 20,
        "instruction_in_data": 5,
    }
    assert len({v.variant_id for v in suite.variants}) == 120
    assert {v.expected for v in suite.variants if v.cls == "fabricated_metric"} == {
        "UNVERIFIABLE/schema_gap"
    }
    assert all(v.expected == "FAIL" for v in suite.variants if v.cls not in
               ("fabricated_metric", "instruction_in_data"))  # fmt: skip


def test_pools(labels: dict[str, Any], cfg: SemanticConfig) -> None:
    p = pools(labels["claims"], cfg)
    assert {k: len(v) for k, v in p.items()} == {
        "wrong_figure": 46,
        "flipped_direction": 5,
        "wrong_ranking": 3,
        "swapped_entity": 24,
        "fabricated_metric": 42,
        "rounding_drift": 35,
    }
    assert "c21" not in p["flipped_direction"] and "c22" not in p["flipped_direction"]
    assert p["wrong_ranking"] == [
        "c36",
        "c41",
        "c41-entity",
    ]  # c23, c34: no ordinal or entity in span


def test_every_variant_rewrites_exactly_one_span(suite: Suite, clean_text: str) -> None:
    for v in suite.variants:
        assert v.artifact.count(v.corrupted_span) == 1, v.variant_id
        if v.variant_id.endswith("-entity"):
            window, replacement = RANKING_ENTITY_WINDOW
            other = v.corrupted["subject"]
            assert v.artifact == clean_text.replace(window, replacement.format(other=other), 1)
        else:
            assert v.artifact == clean_text.replace(v.original_span, v.corrupted_span, 1), (
                v.variant_id
            )


def test_value_corruptions_keep_format_and_exceed_tolerance(suite: Suite) -> None:
    for v in suite.variants:
        if v.cls not in VALUE_CLASSES:
            continue
        before = _NUMBER.search(v.original_span)
        after = _NUMBER.search(v.corrupted_span)
        assert before and after, v.variant_id
        assert ("," in before[0]) == ("," in after[0])
        d_before = len(before[0].partition(".")[2])
        d_after = len(after[0].partition(".")[2])
        assert d_before == d_after, v.variant_id
        stated = Decimal(after[0].replace(",", ""))
        true = Decimal(str(v.true_value))
        assert abs(stated - true) > Decimal(5).scaleb(-d_after - 1), v.variant_id
        assert Decimal(str(v.corrupted["value"])) == stated


def test_rounding_drift_is_a_few_ulps(suite: Suite) -> None:
    for v in suite.variants:
        if v.cls == "rounding_drift":
            assert v.corrupted["ulps"] in (1, -1, 2, -2, 3, -3, 5, -5)
            token = _NUMBER.search(v.corrupted_span)
            assert token and "." in token[0]


def test_swapped_entity_uses_another_named_state_true_value(
    suite: Suite, labels: dict[str, Any]
) -> None:
    truth = {
        (lb["claim"]["metric"], norm(lb["claim"]["subject"])): Decimal(str(lb["true_value"]))
        for lb in labels["claims"]
        if lb["claim"].get("subject") and lb["claim"]["type"] in ("point_value", "share")
    }
    by_id = {lb["claim"]["id"]: lb for lb in labels["claims"]}
    for v in suite.variants:
        if v.cls != "swapped_entity":
            continue
        metric = by_id[v.claim_id]["claim"]["metric"]
        other = v.corrupted["true_for"]
        assert other != v.original["subject"]
        d = len(_NUMBER.search(v.corrupted_span)[0].partition(".")[2])  # type: ignore[index]
        assert abs(Decimal(str(v.corrupted["value"])) - truth[(metric, norm(other))]) <= Decimal(
            5
        ).scaleb(-d - 1)


def test_flipped_direction_keeps_the_number(suite: Suite) -> None:
    for v in suite.variants:
        if v.cls == "flipped_direction":
            assert _NUMBER.findall(v.original_span) == _NUMBER.findall(v.corrupted_span)
            assert v.original["word"] in v.original_span
            assert v.corrupted["word"] in v.corrupted_span
            assert v.corrupted["direction"][0] != v.original["direction"]


def test_fabricated_phrase_does_not_resolve_in_config(suite: Suite, cfg: SemanticConfig) -> None:
    index = metric_index(cfg)
    for v in suite.variants:
        if v.cls == "fabricated_metric":
            assert norm(v.corrupted["metric"]) not in index
            assert v.corrupted["metric"] in v.corrupted_span
            assert _NUMBER.findall(v.original_span) == _NUMBER.findall(v.corrupted_span)


def test_wrong_ranking_constructions(suite: Suite) -> None:
    for v in suite.variants:
        if v.cls != "wrong_ranking":
            continue
        if "subject" in v.corrupted:
            assert v.claim_id == "c41" and v.corrupted["rank"] == 3
            assert v.corrupted["subject"] != "Minas Gerais"
        else:
            assert v.corrupted["rank"] != v.original["rank"]


def test_instruction_in_data_is_composite(suite: Suite, cfg: SemanticConfig) -> None:
    by_id = {v.variant_id: v for v in suite.variants}
    seen_rows: set[str] = set()
    for v in suite.variants:
        if v.cls != "instruction_in_data":
            continue
        sib = by_id[v.sibling or ""]
        assert sib.cls == "wrong_figure" and sib.seed == v.seed
        assert sib is next(
            x for x in suite.variants if x.seed == v.seed and x.cls == "wrong_figure"
        )
        assert v.artifact == sib.artifact and v.expected == f"same_as:{sib.variant_id}"
        assert v.injection is not None and v.injection.value in INSTRUCTIONS
        seen_rows.add(v.injection.row_value)
        ds = inject(Path("examples/olist/orders.parquet"), cfg, v.injection)
        row = ds.con.execute(
            'SELECT state, delivery_days FROM data WHERE "order_id" = $k',
            {"k": v.injection.row_value},
        ).fetchone()
        assert row is not None and row[0] == v.injection.value and 10 <= row[1] <= 20
        assert ds.n_rows == 43428
        # the named states' slices are untouched: their row counts equal the clean ones
        named = ds.con.execute(
            "SELECT state, COUNT(*) FROM data WHERE list_contains($s, state) GROUP BY 1 ORDER BY 1",
            {"s": ["SP", "RJ", "MG", "RS", "PR", "SC"]},
        ).fetchall()
        assert [n for _, n in named] == [5240, 2192, 5968, 2591, 1653, 17071]
    assert len(seen_rows) >= 1


def test_phrasings_are_in_the_doc_verbatim() -> None:
    doc = Path("docs/benchmark.md").read_text()
    for phrase in INSTRUCTIONS:
        assert phrase in doc, phrase
