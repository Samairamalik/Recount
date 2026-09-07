"""Static annotated HTML report (Jinja2, no external assets, no JS framework).

The report is the artifact as written, with claim spans wrapped by verdict colour and
every unextracted numeric token in grey. Clicking a span opens the evidence drawer:
claimed vs computed, the delta against the tolerance, the SQL with its parameters
(display-substituted, marked as such), row counts; an UNVERIFIABLE claim shows its
reason and a ready-to-paste YAML stub when one would resolve it. `j`/`k` walk claims.
Deterministic: the same run record renders the same bytes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from recount.claims import Claim, Ranking
from recount.report.json_out import RunRecord
from recount.verify import Verdict
from recount.verify.policies import half_ulp_tolerance, stated_decimals

_ENV = Environment(
    loader=PackageLoader("recount.report", "templates"), autoescape=select_autoescape(["j2"])
)


@dataclass(frozen=True)
class Segment:
    text: str
    kind: str  # "text" | "PASS" | "FAIL" | "UNVERIFIABLE" | "unextracted"
    claim_id: str | None = None


def segments(rec: RunRecord) -> list[Segment]:
    """The artifact cut into plain text and highlighted intervals. Each claim's span is
    located at its first occurrence; overlaps (which the extractor forbids) keep the
    earlier claim; unextracted tokens come with their offsets."""
    marks: list[tuple[int, int, str, str | None]] = []
    for claim, v in zip(rec.claims, rec.verdicts, strict=True):
        i = rec.artifact.find(claim.span)
        if i >= 0:
            marks.append((i, i + len(claim.span), v.verdict, claim.id))
    for t in rec.extraction.unextracted_numeric:
        marks.append((t.start, t.end, "unextracted", None))
    marks.sort()
    out: list[Segment] = []
    pos = 0
    for a, b, kind, cid in marks:
        if a < pos:
            continue
        if a > pos:
            out.append(Segment(rec.artifact[pos:a], "text"))
        out.append(Segment(rec.artifact[a:b], kind, cid))
        pos = b
    if pos < len(rec.artifact):
        out.append(Segment(rec.artifact[pos:], "text"))
    return out


_QUOTED = re.compile(r"'([^']*)'")


def yaml_stub(claim: Claim, v: Verdict) -> str | None:
    """A config change that would resolve a schema_gap, as YAML to paste. Derived from the
    abstention detail the compiler wrote (docs/abstention.md M2, M3, E4, G3, G5, G9, D2).
    Anything else (ambiguous, unsupported, no_data) has no config fix and gets None."""
    if v.abstain_reason != "schema_gap":
        return None
    d = v.detail
    quoted = _QUOTED.findall(d)
    if d.startswith("unknown metric"):
        return (
            f"metrics:\n  {_key(claim.metric)}:\n    agg: sum        # sum | count | avg | share\n"
            f"    column: <numeric column>\n    aliases: [{_yaml_str(claim.metric)}]\n"
            "    # polarity: higher_is_better   # needed for better/worse and rankings"
        )
    if d.startswith("metric_echo_failed") and len(quoted) >= 1:
        name = quoted[0]
        return (
            f"metrics:\n  {name}:\n    aliases: [..., <the span's wording for {name}>]\n"
            f"    # only if the span {_yaml_str(claim.span)} really means {name}"
        )
    if d.startswith("unknown entity") and claim.subject:
        stub = f"entities:\n  <dimension>:\n    aliases:\n      {_yaml_str(claim.subject)}"
        return stub + ": <stored value>"
    if "is not a" in d and "alias" in d and isinstance(claim, Ranking) and claim.subject:
        return (
            f"entities:\n  {_key(claim.group_by)}:\n    aliases:\n"
            f"      {_yaml_str(claim.subject)}: <stored value>"
        )
    if d.startswith("group_by"):
        return f"entities:\n  {_key(claim.group_by if isinstance(claim, Ranking) else 'dim')}:\n    column: <column>\n    aliases: {{}}"  # noqa: E501
    if "polarity" in d and quoted:
        m = re.search(r"metrics\.([A-Za-z0-9_]+)\.polarity", d)
        name = m[1] if m else _key(claim.metric)
        return f"metrics:\n  {name}:\n    polarity: higher_is_better   # or lower_is_better"
    return None


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "metric"


def _yaml_str(text: str) -> str:
    return json.dumps(text)


def _display_sql(v: Verdict) -> str:
    """The executed SQL with `$param` replaced by its bound value, for reading only. The
    engine never runs this text; the drawer says so."""
    sql = v.sql
    for name, value in sorted(v.params.items(), key=lambda kv: -len(kv[0])):
        shown = (
            f"'{value}'" if isinstance(value, str) or hasattr(value, "isoformat") else str(value)
        )
        sql = sql.replace(f"${name}", shown)
    return sql


def _tolerance(claim: Claim, v: Verdict) -> str | None:
    if v.policy != "half_ulp" or v.claimed_value is None:
        return None
    tol = half_ulp_tolerance(v.claimed_value, stated_decimals(v.claimed_value, claim.span))
    return f"±{tol}"


def _claim_view(claim: Claim, v: Verdict) -> dict[str, Any]:
    fields = {
        k: val
        for k, val in claim.model_dump(mode="json").items()
        if k not in ("id", "span", "type") and val is not None
    }
    return {
        "id": claim.id,
        "type": claim.type,
        "span": claim.span,
        "fields": fields,
        "verdict": v.verdict,
        "claimed": v.claimed_value,
        "computed": v.computed_value,
        "delta": v.delta,
        "tolerance": _tolerance(claim, v),
        "policy": v.policy,
        "detail": v.detail,
        "reason": None if v.abstain_reason is None else str(v.abstain_reason),
        "sql": v.sql,
        "sql_display": _display_sql(v),
        "params": {k: str(val) for k, val in v.params.items()},
        "row_counts": v.row_counts,
        "yaml_stub": yaml_stub(claim, v),
    }


def render_html(rec: RunRecord, record: dict[str, Any]) -> str:
    claims = [_claim_view(c, v) for c, v in zip(rec.claims, rec.verdicts, strict=True)]
    fails = [c for c in claims if c["verdict"] == "FAIL"]
    template = _ENV.get_template("report.html.j2")
    return template.render(
        title=f"Recount · {record['artifact_path']}",
        record=record,
        counts=rec.counts,
        exit_code=rec.exit_code(),
        segments=segments(rec),
        claims=claims,
        fails=fails,
        # raw JSON inside <script type="application/json">: only "</" must be neutralised,
        # the drawer's JS escapes each field when it renders (no double escaping)
        claims_json=json.dumps({c["id"]: c for c in claims}).replace("</", "<\\/"),
        unextracted=[t.context for t in rec.extraction.unextracted_numeric],
        rejected=[(r.reason, r.detail) for r in rec.extraction.rejected],
    )
