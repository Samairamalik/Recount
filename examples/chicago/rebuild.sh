#!/usr/bin/env bash
# Rebuild chicago_taxi_2025.parquet from the City of Chicago data portal (see README.md
# for attribution and the required disclaimer). Twelve parallel monthly pulls, then one
# DuckDB load. ~3 minutes, ~66 MB, 6,825,838 rows. Needs curl and duckdb on PATH.
set -euo pipefail
cd "$(dirname "$0")"

BASE="https://data.cityofchicago.org/resource/ajtu-isnz.csv"
COLS="trip_start_timestamp,company,payment_type,trip_total,fare,tips,trip_miles,trip_seconds"

echo "pulling twelve months of 2025..."
for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
  nm=$(printf "%02d" $((10#$m + 1)))
  ny=2025
  if [ "$m" = "12" ]; then nm=01; ny=2026; fi
  where="trip_start_timestamp%20%3E=%20%272025-$m-01%27%20AND%20trip_start_timestamp%20%3C%20%27$ny-$nm-01%27"
  curl -sS -o "chi_2025_$m.csv" "$BASE?\$limit=1500000&\$select=$COLS&\$where=$where" &
done
wait

echo "building the parquet..."
duckdb -c "
COPY (
  SELECT CAST(trip_start_timestamp AS TIMESTAMP) AS trip_start,
         company, payment_type,
         CAST(trip_total AS DOUBLE)   AS trip_total,
         CAST(fare AS DOUBLE)         AS fare,
         CAST(tips AS DOUBLE)         AS tips,
         CAST(trip_miles AS DOUBLE)   AS trip_miles,
         CAST(trip_seconds AS BIGINT) AS trip_seconds
  FROM read_csv_auto('chi_2025_*.csv', union_by_name = true)
  WHERE trip_start_timestamp >= '2025-01-01' AND trip_start_timestamp < '2026-01-01'
) TO 'chicago_taxi_2025.parquet' (FORMAT parquet);
"
rm -f chi_2025_*.csv
duckdb -c "SELECT COUNT(*) AS rows, MIN(trip_start), MAX(trip_start)
           FROM read_parquet('chicago_taxi_2025.parquet');"
echo "expected: 6,825,838 rows covering 2025-01-01 to 2025-12-31"
