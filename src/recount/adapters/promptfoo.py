"""promptfoo `recount-verify` assertion (FR-012).

    assert:
      - type: python
        value: file://recount_verify.py      # `from recount.adapters.promptfoo import get_assert`

`output` is the generated report; the dataset and config come from test vars
(`recount_data`, `recount_config`), with optional `recount_strict` (bool),
`recount_claims` (pre-extracted claims JSON, fully offline) and `recount_recording`
(a recorded extraction to replay, keyless). Without either, extraction is live and needs
GEMINI_API_KEY. The GradingResult carries the summary line as `reason`, the pass/fail
per the exit-code contract (0 passes, 1 fails), and `namedScores` with the counts, so a
promptfoo table reads like the CLI table.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from recount.pipeline import verify_text
from recount.report import summary_line


def get_assert(output: str, context: dict[str, Any]) -> dict[str, Any]:
    v = context.get("vars", {})
    try:
        rec = verify_text(
            output,
            data=Path(str(v["recount_data"])),
            config=Path(str(v["recount_config"])),
            strict=bool(v.get("recount_strict", False)),
            claims=Path(str(v["recount_claims"])) if v.get("recount_claims") else None,
            recording=Path(str(v["recount_recording"])) if v.get("recount_recording") else None,
        )
    except KeyError as e:
        return {"pass": False, "score": 0.0, "reason": f"recount-verify: missing test var {e}"}
    except Exception as e:  # system error: exit-2 territory, never a silent pass
        return {"pass": False, "score": 0.0, "reason": f"recount-verify: {type(e).__name__}: {e}"}
    c = rec.counts
    checked = c["PASS"] + c["FAIL"]
    return {
        "pass": rec.exit_code() == 0,
        "score": (c["PASS"] / checked) if checked else 0.0,
        "reason": summary_line(rec)
        + "".join(
            f"\nFAIL {claim.id}: {claim.span!r} — {verdict.detail}"
            for claim, verdict in zip(rec.claims, rec.verdicts, strict=True)
            if verdict.verdict == "FAIL"
        ),
        "namedScores": {
            "recount_pass": float(c["PASS"]),
            "recount_fail": float(c["FAIL"]),
            "recount_unverifiable": float(c["UNVERIFIABLE"]),
            "recount_unextracted": float(c["unextracted_numeric"]),
        },
    }
