import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE_DATA = Path("examples/olist/orders.parquet")
EXAMPLE_CONFIG = Path("examples/olist/metrics.yml")
EXAMPLE_REPORT = Path("examples/olist/report.md")
RECORDINGS = Path("bench/recordings/extract")


@pytest.fixture(scope="session")
def labels() -> dict[str, Any]:
    return json.loads((FIXTURES / "labeled_claims.json").read_text())


@pytest.fixture(scope="session")
def corrupted_report(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The demo corruption (benchmark variant s1-wrong_figure-c31: Sao Paulo's revenue
    2,428,002.62 rewritten as 4,228,002.62) as a file, keyless through its recording."""
    from recount.bench.corrupt import generate
    from recount.config import load_config

    claims = json.loads((FIXTURES / "labeled_claims.json").read_text())["claims"]
    frozen = load_config(Path("bench/suite_config.yml"))
    suite = generate(EXAMPLE_REPORT.read_text(), claims, frozen, EXAMPLE_DATA, (1,))
    v = next(x for x in suite.variants if x.variant_id == "s1-wrong_figure-c31")
    assert v.corrupted_span == "generating 4,228,002.62 in revenue"
    path = tmp_path_factory.mktemp("demo") / "report.md"
    path.write_text(v.artifact)
    return path
