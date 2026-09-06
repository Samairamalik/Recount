"""Stage 0 spike: extract -> crude compile -> DuckDB verify -> verdict table. Throwaway.

One Gemini call per artifact (never per claim). The dataset never enters the prompt: the
model sees only report text. Extraction is cached to spike/extraction_raw.json; delete it
to force a fresh call.
"""
import json
import re
from decimal import Decimal
from pathlib import Path

import duckdb
import yaml
from google import genai
from google.genai import types
from pydantic import BaseModel

MODEL = "gemini-3.6-flash"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "spike/extraction_raw.json"

CFG = yaml.safe_load((ROOT / "spike/metrics.yml").read_text())
REPORT = (ROOT / "spike/report.md").read_text()
LABELS = json.loads((ROOT / "spike/labels.json").read_text())

# ---------------------------------------------------------------- extraction


class XClaim(BaseModel):
    id: str
    type: str
    span: str
    metric: str
    value: float | None = None
    unit: str | None = None
    period: str | None = None
    baseline_period: str | None = None
    subject: str | None = None
    confidence: str = "high"


def extract() -> list[dict]:
    if CACHE.exists():
        print(f"[extract] reusing {CACHE.name} (delete it to re-call the API)")
        return json.loads(CACHE.read_text())
    prompt = (ROOT / "spike/extraction_prompt.draft.md").read_text() + "\n" + REPORT
    key = re.search(r"GEMINI_API_KEY=(\S+)", (ROOT / ".env").read_text()).group(1)
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=list[XClaim],
        ),
    )
    out = [c.model_dump() for c in resp.parsed]
    CACHE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"[extract] {len(out)} claims from one call to {MODEL}")
    return out


# ------------------------------------------------------------------ compile

POINT_SQL = {
    "revenue": "SELECT ROUND(SUM(revenue), 2) FROM o WHERE ($q = 0 OR QUARTER(order_date) = $q) AND ($st = '' OR state = $st)",
    "orders": "SELECT COUNT(*) FROM o WHERE ($q = 0 OR QUARTER(order_date) = $q) AND ($st = '' OR state = $st)",
    "avg_order_value": "SELECT AVG(revenue) FROM o WHERE ($q = 0 OR QUARTER(order_date) = $q) AND ($st = '' OR state = $st)",
    "avg_delivery_days": "SELECT AVG(delivery_days) FROM o WHERE ($q = 0 OR QUARTER(order_date) = $q) AND ($st = '' OR state = $st)",
    "order_share_pct": "SELECT 100.0 * COUNT(*) FILTER (WHERE state = $st) / COUNT(*) FROM o WHERE ($q = 0 OR QUARTER(order_date) = $q)",
}
GROWTH_SQL = {
    "revenue": "SELECT 100.0 * (SUM(CASE WHEN QUARTER(order_date) = $q THEN revenue ELSE 0 END) - SUM(CASE WHEN QUARTER(order_date) = $b THEN revenue ELSE 0 END)) / SUM(CASE WHEN QUARTER(order_date) = $b THEN revenue ELSE 0 END) FROM o",
    "orders": "SELECT 100.0 * (SUM(CASE WHEN QUARTER(order_date) = $q THEN 1 ELSE 0 END) - SUM(CASE WHEN QUARTER(order_date) = $b THEN 1 ELSE 0 END)) / SUM(CASE WHEN QUARTER(order_date) = $b THEN 1 ELSE 0 END) FROM o",
}

QUARTER_WORDS = {1: ("q1", "first quarter", "first-quarter"), 2: ("q2", "second quarter", "second-quarter"),
                 3: ("q3", "third quarter", "third-quarter"), 4: ("q4", "fourth quarter", "fourth-quarter")}


def resolve_metric(text: str) -> str | None:
    t = (text or "").lower().strip()
    best = None
    for key, aliases in CFG["metric_aliases"].items():
        for a in aliases:
            if a in t and (best is None or len(a) > best[1]):
                best = (key, len(a))
    return best[0] if best else None


def resolve_quarter(text: str | None) -> int | None:
    """0 = full year (no filter). None = could not resolve."""
    t = (text or "").lower()
    if not t:
        return None
    for q, words in QUARTER_WORDS.items():
        if any(w in t for w in words):
            return q
    if "2017" in t or "year" in t or "annual" in t:
        return 0
    return None


def resolve_entity(claim: dict) -> str:
    """'' = no entity filter."""
    hay = " ".join(filter(None, [claim.get("subject"), claim.get("span")]))
    for name, code in CFG["entity_aliases"].items():
        if name.lower() in hay.lower():
            return code
    return ""


def compile_claim(c: dict) -> tuple[str | None, dict, str | None]:
    """-> (sql, params, abstain_reason)"""
    if c["type"] not in ("point_value", "growth"):
        return None, {}, f"unsupported_claim_type:{c['type']}"
    if c["span"] not in REPORT:
        return None, {}, "span_not_found"
    if c.get("value") is None:
        return None, {}, "no_stated_value"
    metric = resolve_metric(c.get("metric", "")) or resolve_metric(c.get("span", ""))
    if metric is None:
        return None, {}, "unknown_metric"
    q = resolve_quarter(c.get("period"))
    if q is None:
        return None, {}, "unknown_period"
    st = resolve_entity(c)

    if c["type"] == "point_value":
        if metric == "order_share_pct" and st == "":
            return None, {}, "share_needs_entity"
        return POINT_SQL[metric], {"q": q, "st": st}, None

    if metric not in GROWTH_SQL:
        return None, {}, f"unsupported_metric_for_growth:{metric}"
    b = resolve_quarter(c.get("baseline_period"))
    if b is None:
        b = q - 1 if q and q > 1 else None
    if not b:
        return None, {}, "missing_baseline"
    return GROWTH_SQL[metric], {"q": q, "b": b}, None


# ------------------------------------------------------------------- verify

def tolerance(stated: float) -> float:
    exp = Decimal(str(stated)).as_tuple().exponent
    return 0.0 if exp >= 0 else 0.5 * (10 ** exp)


def main() -> None:
    con = duckdb.connect()
    con.register("o", con.read_parquet(str(ROOT / CFG["dataset"])))
    claims = extract()

    by_span = {lab["span"]: lab for lab in LABELS["claims"]}

    rows = []
    for c in claims:
        sql, params, reason = compile_claim(c)
        if reason:
            rows.append({**c, "verdict": "ABSTAIN", "reason": reason, "true": None})
            continue
        true = con.execute(sql, params).fetchone()[0]
        true = float(true) if true is not None else None
        ok = true is not None and abs(c["value"] - true) <= tolerance(c["value"])
        rows.append({**c, "verdict": "PASS" if ok else "FAIL", "reason": "", "true": true})

    # ---- print verdict table
    print(f"\n{'span':<54} {'type':<12} {'stated':>12} {'computed':>12}  verdict / abstain reason")
    print("-" * 132)
    for r in rows:
        sp = r["span"] if len(r["span"]) <= 54 else r["span"][:51] + "..."
        st = "—" if r["value"] is None else f"{r['value']:g}"
        tv = "—" if r["true"] is None else f"{r['true']:.4f}"
        tail = r["reason"] if r["verdict"] == "ABSTAIN" else ""
        print(f"{sp:<54} {r['type']:<12} {st:>12} {tv:>12}  {r['verdict']:<8} {tail}")

    # ---- score against the answer key
    matched, invented = {}, []
    for r in rows:
        lab = by_span.get(r["span"])
        if lab is None:
            for span, cand in by_span.items():
                if r["span"] in span or span in r["span"]:
                    lab = cand
                    break
        if lab is None:
            invented.append(r)
        else:
            matched.setdefault(lab["id"], []).append(r)

    missed = [lab for lab in LABELS["claims"] if lab["id"] not in matched]
    norm = {"ABSTAIN": "UNVERIFIABLE"}
    correct = false_accept = false_flag = other_wrong = 0
    for lid, rs in matched.items():
        lab = by_span[[l["span"] for l in LABELS["claims"] if l["id"] == lid][0]]
        got = norm.get(rs[0]["verdict"], rs[0]["verdict"])
        exp = lab["expected_verdict"]
        if got == exp:
            correct += 1
        elif got == "PASS" and exp == "FAIL":
            false_accept += 1
        elif got == "FAIL" and exp in ("PASS", "UNVERIFIABLE"):
            false_flag += 1
        else:
            other_wrong += 1

    numeric = [l for l in LABELS["claims"] if l["value"] is not None]
    numeric_ids = {l["id"] for l in numeric}
    verified_numeric = sum(
        1 for lid, rs in matched.items()
        if lid in numeric_ids and rs[0]["verdict"] in ("PASS", "FAIL")
    )
    compiled = sum(1 for r in rows if r["verdict"] != "ABSTAIN")

    print("\n" + "=" * 60)
    print(f"extracted                 {len(rows)}")
    print(f"hand labels               {len(LABELS['claims'])}")
    print(f"matched labels            {len(matched)}  (coverage {100*len(matched)/len(LABELS['claims']):.1f}%)")
    print(f"missed labels             {len(missed)}")
    print(f"invented / unmatched      {len(invented)}")
    print(f"compiled                  {compiled}  abstained {len(rows)-compiled}")
    print(f"verdicts correct          {correct} / {len(matched)}")
    print(f"false accepts             {false_accept}")
    print(f"false flags               {false_flag}")
    print(f"other mismatches          {other_wrong}")
    print(f"numeric labels            {len(numeric)}")
    print(f"compile-and-verify rate   {100*verified_numeric/len(numeric):.1f}%  ({verified_numeric}/{len(numeric)})")
    from collections import Counter
    print("\nabstain reasons:", dict(Counter(r["reason"] for r in rows if r["verdict"] == "ABSTAIN")))
    print("missed label ids:", [m["id"] for m in missed])

    (ROOT / "spike/verdicts.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
