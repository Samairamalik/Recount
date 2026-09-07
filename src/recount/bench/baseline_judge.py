"""LLM-as-judge baseline (eval-only AI zone; docs/benchmark.md J1–J6).

The judge is asked, per artifact, whether the report is faithful to a deterministic
aggregate summary of the data (`bench/summary.py`). It runs on the identical suite the
verifier runs on, through the same `ExtractorClient` seam, so it is recorded and replayed
the same way. Its output never touches a Recount verdict; it exists so the comparison
is fair (same model, same artifacts, the answer key in hand).

CLAUDE.md §0: this module is the sole place a dataset-derived summary enters a prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from recount.extract import ExtractError, ExtractorClient

JUDGE_PROMPT = """\
You are auditing an analytical report against a summary of the dataset it describes.
The summary contains every aggregate the report could legitimately be based on: totals,
quarterly figures with quarter-over-quarter changes, and per-group figures with shares
and ranks. Treat the summary as the ground truth.

A report is faithful only if every numeric value, percentage, growth or decline,
comparison, share and ranking it states is supported by the summary. A number is
supported if it is a correct rounding of the summary's value at the precision the
report states. A direction word (grew, declined, improved, worsened) must match the sign
of the change. A rank or "second place" must match the summary's rank column. A metric
the summary does not contain cannot be supported.

Return JSON: {"faithful": true|false, "problems": [{"span": ..., "reason": ...}]}.
Each problem's "span" must be copied verbatim from the report (the shortest substring
that contains the unsupported assertion). If everything is supported, return
faithful=true and an empty list.
"""

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "faithful": {"type": "boolean"},
        "problems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"span": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["span", "reason"],
            },
        },
    },
    "required": ["faithful", "problems"],
}


@dataclass(frozen=True)
class Problem:
    span: str
    reason: str
    verbatim: bool  # span is a substring of the report; only verbatim spans can be located


@dataclass(frozen=True)
class Judgement:
    faithful: bool
    problems: tuple[Problem, ...]
    raw: str
    model: str


def judge_input(report: str, summary: str) -> str:
    """What the judge sees after the prompt: the report, then the summary (J2)."""
    return "# Report\n\n" + report + "\n\n# Data summary\n\n" + summary


def judge(report: str, summary: str, client: ExtractorClient) -> Judgement:
    """One call, one retry on malformed output, like the extractor."""
    text = judge_input(report, summary)
    raw, error = "", "no response"
    for attempt in range(2):
        try:
            raw = client.complete(JUDGE_PROMPT, text, JUDGE_SCHEMA)
            data = json.loads(raw)
        except ExtractError:
            raise
        except Exception as e:  # provider/transport error or invalid JSON
            error = f"{type(e).__name__}: {e}"
            if attempt == 0:
                continue
            break
        if isinstance(data, dict) and isinstance(data.get("faithful"), bool):
            problems = tuple(
                Problem(
                    str(p.get("span", "")),
                    str(p.get("reason", "")),
                    str(p.get("span", "")) in report,
                )
                for p in data.get("problems", [])
                if isinstance(p, dict)
            )
            return Judgement(bool(data["faithful"]), problems, raw, client.model)
        error = "response is not an object with a boolean 'faithful'"
    raise ExtractError(f"judge failed twice; last error: {error}", raw=raw)
