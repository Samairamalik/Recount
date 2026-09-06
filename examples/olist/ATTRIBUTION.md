# Example data attribution

`orders.parquet` is a sampled, transformed derivative of the
[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(Kaggle), licensed **CC BY-NC-SA 4.0**.

Transformation (see `spike/sample_olist.py`): orders with status `delivered` and a
purchase timestamp in calendar year 2017, joined to customers (for `state`) and
order items, aggregated to one row per order with columns
`order_id, order_date, state, revenue (= sum of price + freight), delivery_days`.
43,428 rows, 1.7 MB: only this small sample (<5 MB) is committed, for demonstration,
the golden tests and benchmarking. Two rows have a NULL `delivery_days`.

This license covers the **example data only**. The Recount code is Apache-2.0
(see the repository `LICENSE`). The non-commercial clause applies to this dataset,
not to the tool.
