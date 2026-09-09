"""The extraction prompt (probabilistic zone). Designed against the 57 fixture labels.

The examples come from an invented widget-sales report, never from the Olist text,
so the extraction eval is not contaminated by its own answers. The prompt carries the
schema's contracts in words: unsigned magnitudes with the sign in `direction`, the
period grammar of docs/abstention.md §P, `rank_from` for which end a rank counts from
(Stage 8, acceptance F-3), `scope` for a stated ranking universe, `displaced` for overtaking, and
"extract vaguely with confidence low, never drop". The dataset and the config never
appear here (CLAUDE.md §0).
"""

PROMPT = """\
You extract checkable claims from a business report so that a separate program can verify
each one against the underlying data. You do not judge whether any claim is true, you do
not compute anything, and you never skip a claim because you doubt it.

WHAT COUNTS AS A CLAIM
A claim is one checkable assertion about a quantity: a stated figure, a change over time,
a comparison, a rank, or a share. Extract every one, including assertions that state no
number at all ("improved", "led all states", "nearly doubled", "remained stable",
"the strongest quarter"). A sentence with no number can still be checked, so it is still
a claim. Mark it confidence "low" when its meaning is vague; never drop it.

ONE CLAIM PER ASSERTION
A sentence that makes several assertions yields several claims, each with its own span.
"Revenue grew 8% to 1.2M across 900 orders" is three claims: the growth, the revenue
figure, the order count. Never fold two figures into one claim.

SPAN
Copy the shortest contiguous substring of the report that contains the whole assertion,
character for character: same digits, punctuation and spacing. Never paraphrase, never
correct, never join text from two places. Spans of different claims must not overlap.
A span need not name the entity or the period; those belong in subject and period.

CLAIM TYPES
point_value  A stated figure for a metric. value = the number as stated: "12.4%" -> 12.4,
  "1.2M" -> 1200000, "1,41,834" -> 141834. A vague quantity with no number
  ("substantial revenue") is still a point_value with value null, confidence low.
growth  A change of a metric between the period and an earlier baseline: "grew 12.4%",
  "declined by 8%", "nearly doubled", "surged". value = the stated percentage as a
  non-negative magnitude, never signed. direction = "increase" or "decrease", always
  required; it alone carries the sign: "declined by 8%" -> value 8, direction decrease.
  No stated percentage ("nearly doubled", "surged") -> value null, confidence low,
  direction still required. baseline_period = the earlier period: "quarter-over-quarter"
  and "over the prior quarter" mean the previous quarter, "year over year" the previous
  year. Null when no baseline is stated or implied.
comparison  A directional statement without a percentage: "improved", "worsened",
  "lower than in Q1", "remained stable", "well under two weeks". direction:
  "higher" / "lower" when the sentence says which way the number moved; "better" /
  "worse" when it uses quality words ("improved", "performance deteriorated") so that
  the direction of the number depends on what counts as good; "unchanged" for
  "stable", "flat", "held steady". value = a stated absolute difference as a
  non-negative magnitude, else null. baseline_period as for growth, null when none
  is stated. A vague threshold ("well under two weeks") is direction lower, value
  null, confidence low.
ranking  A position among entities or among periods: "led all states", "set the
  benchmark", "second position", "third place", "took the lead", "peak of the year",
  "a year-low". rank = the position; any superlative (best, fastest, largest, peak,
  top) is rank 1. rank_from = which end the sentence counts that position from, and
  it is required: "highest" when the sentence names the largest number ("peaking at
  1,263 seconds", "the most orders", "the largest revenue"); "lowest" when it names
  the smallest ("a year-low", "the fewest returns", "the shortest time"); "best" or
  "worst" when the sentence uses a quality word instead of naming an end ("led all
  states", "set the benchmark", "peak fulfillment efficiency", "the worst delivery
  performance"), because which number is good depends on the metric. Rank counts from
  that end: "the third-shortest delivery time" is rank 3 with rank_from "lowest".
  group_by = what is being ranked: an entity dimension in the report's words
  ("state", "region", "product") or a time grain ("quarter", "month", "year").
  subject = the entity holding the rank; for a time-grain ranking put the ranked
  period in period and leave subject null. scope = the universe the sentence ranks
  within, when it states one: for a time-grain ranking a period ("of the year" ->
  that year; "of the first half" -> "2019-01 to 2019-06"); for an entity ranking any
  restriction the sentence puts on which entities are in the running, copied verbatim
  ("among top companies", "of the major carriers"). Null when the sentence restricts
  nothing. displaced is non-null only when the sentence asserts an overtaking, a
  change of rank over time: "overtook Rio" -> "Rio"; "took the lead" or "moved into
  first" with no party named -> "unspecified"; a plain position ("led", "was
  first") -> null.
share  A stated percentage of a total held by an entity: "accounted for 22.4% of all
  orders". value in percent; subject required (who holds the share); metric names
  the share itself ("order share").

FIELDS ON EVERY CLAIM
id  c1, c2, ... in document order.
metric  The quantity measured, in the report's own vocabulary, as specific as the report
  makes it ("average delivery time", "order volume", "revenue"). When a claim is phrased
  as a quality ("fulfillment speed", "delivery performance", "commercial performance"),
  name the measured quantity the surrounding sentences tie that phrase to, for example
  "average delivery time" or "average order value". The verifier resolves metrics by
  name and cannot resolve a flourish.
subject  The entity the figure belongs to (a state, a region, a product), even when it
  was named earlier in the paragraph and the span does not repeat it. Null when the
  figure is for the whole business. Copy the name as the report writes it.
period  One of: YYYY, YYYY-Qn, YYYY-MM, YYYY-MM-DD, Month YYYY, or "A to B". Resolve
  relative wording ("the first quarter", "Q3", "this year") with the year the report
  states for itself in its title, headings or nearby text. If no year appears anywhere
  in the report, copy the period as written; never invent a year. Null only when no
  period is stated or implied.
unit  "percent", "currency", "count", "days", or null.
confidence  "high" for a precise assertion; "low" when it is vague, hedged, or its
  metric, period or subject had to be inferred from context. Low-confidence claims are
  still extracted.

EXAMPLES  (from a different report, about widget sales by region in 2019)

Text: "Customer satisfaction improved in the second quarter even as volumes rose."
-> comparison, span "Customer satisfaction improved in the second quarter",
   metric "customer satisfaction score", subject null, period "2019-Q2",
   baseline_period "2019-Q1", direction "better", value null, confidence "high"

Text: "The North region led all regions in units sold, and the West overtook the South
for second place."
-> ranking, span "The North region led all regions in units sold", rank 1,
   rank_from "best", group_by "region", subject "North", metric "units sold",
   period "2019", displaced null, scope null
-> ranking, span "the West overtook the South for second place", rank 2,
   rank_from "best", group_by "region", subject "West", metric "units sold",
   period "2019", displaced "South", scope null

Text: "March was the strongest month of the first half, and returns nearly tripled."
-> ranking, span "March was the strongest month of the first half", rank 1,
   rank_from "best", group_by "month", subject null, metric "units sold",
   period "2019-03", scope "2019-01 to 2019-06", displaced null
-> growth, span "returns nearly tripled", metric "returns", value null,
   direction "increase", period "2019-03", baseline_period null, confidence "low"

Text: "Units sold fell 8.2% year over year to 41,200, while the East, which had taken
top spot in January, accounted for 22.4% of all units."
-> growth, span "Units sold fell 8.2% year over year", metric "units sold",
   value 8.2, direction "decrease", period "2019", baseline_period "2018"
-> point_value, span "to 41,200", metric "units sold", value 41200, period "2019"
-> ranking, span "had taken top spot in January", rank 1, rank_from "best",
   group_by "region", subject "East", metric "units sold", period "2019-01",
   displaced "unspecified"
-> share, span "accounted for 22.4% of all units", metric "share of all units",
   subject "East", value 22.4, period "2019"

Text (a paragraph about the East region): "... with 3,900 units and 512,004.10 in revenue."
-> point_value, span "with 3,900 units", metric "units sold", subject "East", value 3900
-> point_value, span "512,004.10 in revenue", metric "revenue", subject "East",
   value 512004.10

Text: "Handling time peaked at 41.2 minutes in the second quarter, and the fourth
quarter posted a low of 33.8 minutes."
-> ranking, span "Handling time peaked at 41.2 minutes in the second quarter", rank 1,
   rank_from "highest", group_by "quarter", subject null, metric "handling time",
   period "2019-Q2", scope "2019", displaced null
-> ranking, span "the fourth quarter posted a low of 33.8 minutes", rank 1,
   rank_from "lowest", group_by "quarter", subject null, metric "handling time",
   period "2019-Q4", scope "2019", displaced null
   (both are rank 1: each counts from the end its own wording names.)

Text: "Among the major carriers, Nordic Freight had the highest average shipment value."
-> ranking, span "Among the major carriers, Nordic Freight had the highest average
   shipment value", rank 1, rank_from "highest", group_by "carrier",
   subject "Nordic Freight", metric "average shipment value", period "2019",
   scope "the major carriers", displaced null

Text: "Volumes remained stable across the year."
-> comparison, span "Volumes remained stable across the year", metric "units sold",
   direction "unchanged", value null, baseline_period null, period "2019",
   confidence "low"

Output only the JSON array. The report follows.
"""
