import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def labels() -> dict[str, Any]:
    return json.loads((FIXTURES / "labeled_claims.json").read_text())
