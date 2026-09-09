"""Rankings end to end on the Olist parquet: which end rank 1 counts from (acceptance F-3), and
the minimum support a group needs to be in the universe at all (acceptance F-4).

Both findings come from the v0.1.0 acceptance run on 6.8M rows of unseen Chicago taxi
data (docs/design.md, "Acceptance testing on unseen data"). Olist reproduces both:
`avg_delivery_days` is a lower_is_better metric a report can write from either end, and
27 states include a tail as thin as 28 orders. Every claim below is true of the data;
before Stage 8 the ones marked so returned a confident FAIL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from recount.claims import AbstainReason, Ranking
from recount.config import Metric, SemanticConfig, load_config
from recount.io import load_dataset
from recount.verify import verify_claim

CFG = load_config(Path("tests/fixtures/olist_metrics.yml"))
DS = load_dataset(Path("examples/olist/orders.parquet"), CFG)

# Quarterly average delivery days in 2017: Q3 11.4061 (lowest) ... Q4 14.2817 (highest).
FASTEST, SLOWEST = "2017-Q3", "2017-Q4"


def rank(**kw: Any) -> Ranking:
    base: dict[str, Any] = {
        "type": "ranking", "id": "t", "confidence": "high",
        "span": "average delivery time", "metric": "average delivery time",
        "group_by": "quarter", "rank": 1, "scope": "2017",
    }  # fmt: skip
    return Ranking(**(base | kw))


def test_f3_both_ends_of_one_metric_are_verifiable_in_one_report() -> None:
    """The report's own superlative decides, not the config. `avg_delivery_days` is
    lower_is_better, so before Stage 8 rank 1 was always the fastest quarter and
    "the slowest quarter was Q4" — true — FAILed with `2017-10-01 ranks 4`."""
    assert CFG.metrics["avg_delivery_days"].polarity == "lower_is_better"
    slowest = verify_claim(DS, rank(period=SLOWEST, rank_from="highest"), CFG)
    fastest = verify_claim(DS, rank(period=FASTEST, rank_from="lowest"), CFG)
    assert (slowest.verdict, fastest.verdict) == ("PASS", "PASS")
    assert "DESC" in slowest.sql and "ASC" in fastest.sql
    # and the same sentences pointed at the wrong quarter still FAIL
    assert verify_claim(DS, rank(period=FASTEST, rank_from="highest"), CFG).verdict == "FAIL"
    assert verify_claim(DS, rank(period=SLOWEST, rank_from="lowest"), CFG).verdict == "FAIL"


def test_quality_wording_still_resolves_through_polarity() -> None:
    """ "best"/"worst" is the Comparison better/worse split: the sentence names a quality,
    so the end comes from the config, which is the one question polarity answers."""
    assert verify_claim(DS, rank(period=FASTEST, rank_from="best"), CFG).verdict == "PASS"
    assert verify_claim(DS, rank(period=SLOWEST, rank_from="worst"), CFG).verdict == "PASS"
    assert verify_claim(DS, rank(period=FASTEST, rank_from="worst"), CFG).verdict == "FAIL"


def test_g12_a_ranking_without_a_direction_abstains() -> None:
    v = verify_claim(DS, rank(period=FASTEST, rank_from=None), CFG)
    assert v.verdict == "UNVERIFIABLE" and v.abstain_reason == AbstainReason.AMBIGUOUS
    assert "no rank direction" in v.detail
    assert v.sql == "" and v.row_counts == {}


# ---------------------------------------------------- acceptance F-4, min_rows


def _with_min_rows(n: int | None) -> SemanticConfig:
    """The fixture config names the six states the Olist report writes about; the tail
    this finding is about needs two more in the vocabulary."""
    aov: Metric = CFG.metrics["avg_order_value"]
    state = CFG.entities["state"]
    return CFG.model_copy(
        update={
            "metrics": dict(CFG.metrics)
            | {"avg_order_value": aov.model_copy(update={"min_rows": n})},
            "entities": dict(CFG.entities)
            | {
                "state": state.model_copy(
                    update={"aliases": dict(state.aliases) | {"Ceara": "CE", "Amapa": "AP"}}
                )
            },
        }
    )


def state_rank(subject: str, rank_: int) -> Ranking:
    return Ranking(
        type="ranking", id="t", confidence="high",
        span="average order value", metric="average order value",
        group_by="state", subject=subject, rank=rank_, rank_from="highest", period="2017",
    )  # fmt: skip


def test_f4_a_28_order_state_wins_the_average_ranking_without_min_rows() -> None:
    """The long tail is the normal case on real data: AP (28 orders, 257.52) outranks
    every large state, so "CE had the highest average order value" — true of every state
    that carries a business — FAILs against a universe nobody meant."""
    v = verify_claim(DS, state_rank("CE", 1), _with_min_rows(None))
    assert v.verdict == "FAIL" and v.row_counts == {"n_rows": 43428, "n_groups": 27}
    assert "top: AP=257.519" in v.detail  # the tail, unrounded: this metric pins no round


def test_f4_min_rows_restricts_the_universe_and_says_by_how_much() -> None:
    v = verify_claim(DS, state_rank("CE", 1), _with_min_rows(500))
    assert v.verdict == "PASS"
    assert v.row_counts == {"n_rows": 43428, "n_groups": 12, "n_groups_excluded": 15}
    assert v.params["min_rows"] == 500  # bound, never rendered into the SQL text


def test_f4_a_subject_below_min_rows_abstains_and_is_never_failed() -> None:
    """The ruling (docs/design.md): FAIL asserts "this number is wrong"; below the
    threshold all we know is that the claim is not adjudicable at the support the config
    declares. AP really does hold the highest average — on 28 orders."""
    v = verify_claim(DS, state_rank("Amapa", 1), _with_min_rows(500))
    assert v.verdict == "UNVERIFIABLE" and v.abstain_reason == AbstainReason.NO_DATA
    assert "'AP' has 28 row(s), below min_rows 500" in v.detail
    assert verify_claim(DS, state_rank("Amapa", 1), _with_min_rows(None)).verdict == "PASS"


@pytest.mark.parametrize(("n", "excluded"), [(1, 0), (28, 1)])
def test_min_rows_at_or_below_a_groups_size_keeps_it(n: int, excluded: int) -> None:
    """The threshold is inclusive: a group with exactly min_rows rows still ranks. At 28,
    AP is in and only the single state below 28 orders falls out."""
    v = verify_claim(DS, state_rank("Amapa", 1), _with_min_rows(n))
    assert v.verdict == "PASS" and v.row_counts["n_groups_excluded"] == excluded
