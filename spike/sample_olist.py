"""Sample the Olist dataset into a single fact table for the spike.

Expects the Kaggle CSVs in spike/data/. Produces spike/data/orders.parquet with columns:
order_id, order_date, state, revenue, delivery_days. Adjust the year filter if needed.
"""
from pathlib import Path

import duckdb

DATA = Path(__file__).parent / "data"

con = duckdb.connect()
con.execute(
    """
    COPY (
      SELECT o.order_id,
             CAST(o.order_purchase_timestamp AS DATE)            AS order_date,
             c.customer_state                                     AS state,
             SUM(oi.price + oi.freight_value)                     AS revenue,
             DATE_DIFF('day', CAST(o.order_purchase_timestamp AS DATE),
                       CAST(o.order_delivered_customer_date AS DATE)) AS delivery_days
      FROM read_csv_auto($orders)     o
      JOIN read_csv_auto($customers)  c  USING (customer_id)
      JOIN read_csv_auto($items)      oi USING (order_id)
      WHERE o.order_status = 'delivered'
        AND o.order_purchase_timestamp >= '2017-01-01'
        AND o.order_purchase_timestamp <  '2018-01-01'
      GROUP BY 1, 2, 3, 5
    ) TO $out (FORMAT PARQUET)
    """,
    {
        "orders": str(DATA / "olist_orders_dataset.csv"),
        "customers": str(DATA / "olist_customers_dataset.csv"),
        "items": str(DATA / "olist_order_items_dataset.csv"),
        "out": str(DATA / "orders.parquet"),
    },
)
n = con.execute("SELECT COUNT(*) FROM read_parquet($p)", {"p": str(DATA / "orders.parquet")}).fetchone()
print(f"wrote {DATA / 'orders.parquet'} with {n[0]} rows")
