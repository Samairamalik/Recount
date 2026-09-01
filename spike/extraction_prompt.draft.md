# Extraction prompt — ROUGH DRAFT for the spike only
# The real prompt (Stage 4) must be designed against your hand labels. Rewrite it then.

You extract checkable claims from a business report. You do NOT judge whether claims are true.
Output ONLY a JSON array. Each element:
- "id": "c1", "c2", ...
- "type": one of "point_value" | "growth" | "comparison" | "ranking" | "share"
- "span": the exact substring of the report containing the claim (copy verbatim, no edits)
- "metric": the quantity referenced, in the report's own words (e.g. "revenue", "average delivery time")
- "value": the stated number, or null if none is stated
- "unit": "percent" | "currency" | "count" | "days" | null
- "period": the time period referenced, as written (e.g. "Q3 2017"), or null
- "baseline_period": for growth/comparison, the comparison period as written, or null
- "subject" / "displaced" / "rank" / "group_by": for ranking claims
- "confidence": "high" | "low" (low if the sentence is vague or ambiguous — still extract it)

Extract every numeric or comparative assertion, including vague ones. Do not invent claims.
Report follows:
---
