"""Spike step 1: generate the test artifact. Throwaway.

Computes real aggregates from spike/data/orders.parquet, hands them to Gemini, and asks
for a natural-sounding quarterly report. The dataset itself never leaves this machine —
only the aggregates below, which is what spike/README.md step 3 directs.
"""
import re
from pathlib import Path

import duckdb
from google import genai
from google.genai import types

MODEL = "gemini-3.6-flash"
ROOT = Path(__file__).resolve().parent.parent

con = duckdb.connect()
con.register("o", con.read_parquet(str(ROOT / "spike/data/orders.parquet")))


def table(sql: str) -> str:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    lines = [" | ".join(cols)]
    for row in cur.fetchall():
        lines.append(" | ".join(str(v) for v in row))
    return "\n".join(lines)


facts = f"""
Quarterly totals (2017):
{table("SELECT 'Q'||QUARTER(order_date) AS quarter, COUNT(*) AS orders, ROUND(SUM(revenue),2) AS revenue, ROUND(AVG(delivery_days),2) AS avg_delivery_days FROM o GROUP BY 1 ORDER BY 1")}

Quarter-over-quarter growth (%):
{table("WITH q AS (SELECT QUARTER(order_date) q, COUNT(*) c, SUM(revenue) r FROM o GROUP BY 1) SELECT 'Q'||q AS quarter, ROUND(100.0*(r-LAG(r) OVER (ORDER BY q))/LAG(r) OVER (ORDER BY q),2) AS revenue_growth_pct, ROUND(100.0*(c-LAG(c) OVER (ORDER BY q))/LAG(c) OVER (ORDER BY q),2) AS order_growth_pct FROM q ORDER BY q")}

Top states, full year:
{table("SELECT state, COUNT(*) AS orders, ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),2) AS pct_of_all_orders, ROUND(SUM(revenue),2) AS revenue, ROUND(AVG(delivery_days),2) AS avg_delivery_days FROM o GROUP BY 1 ORDER BY orders DESC LIMIT 6")}

Full year: 43428 orders, 6921535.24 revenue, average order value 159.38,
average delivery 12.98 days, 27 states.
State codes: SP = Sao Paulo, RJ = Rio de Janeiro, MG = Minas Gerais, RS = Rio Grande do Sul,
PR = Parana, SC = Santa Catarina, BA = Bahia.
"""

PROMPT = f"""You are a business analyst writing the 2017 annual review for a Brazilian
e-commerce marketplace. Write it in Markdown, about 600 words, with a few short sections.

Here are the real figures. Use them; do not invent different numbers.
{facts}

Requirements:
- Make roughly 15 checkable assertions about revenue, order volume, delivery times,
  state rankings, and shares.
- Write like a human analyst, in flowing prose. Do NOT include tables or bullet lists of
  raw figures. Some sentences should combine two assertions.
- Refer to states by their full names (Sao Paulo, Rio de Janeiro, Minas Gerais), not codes.
- Include AT LEAST THREE deliberately vague or paraphrased claims that a reader would
  understand but a machine would struggle with, for example phrasings in the spirit of
  "nearly doubled", "took the lead", "roughly one in five", "well under two weeks".
- Include one sentence stating that Sao Paulo took the lead in a specific quarter.
- Do not add caveats, footnotes, or a methodology section. Just the report.
"""

key = re.search(r"GEMINI_API_KEY=(\S+)", (ROOT / ".env").read_text()).group(1)
client = genai.Client(api_key=key)
resp = client.models.generate_content(
    model=MODEL,
    contents=PROMPT,
    config=types.GenerateContentConfig(temperature=0.0),
)

out = ROOT / "spike/report.md"
out.write_text(resp.text)
print(f"wrote {out} ({len(resp.text)} chars) using {MODEL}")
