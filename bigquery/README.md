# BigQuery port

This folder reruns the same cleaning and metrics pipeline in **Google BigQuery** (GoogleSQL) and checks that the results match the DuckDB version.

| File | Purpose |
|---|---|
| `01_clean.sql` | Assignment-mismatch audit, one row per user (first exposure, via `QUALIFY`), cleaning funnel |
| `02_metrics.sql` | Arm, daily, cumulative and country metrics, plus the primary two-proportion z-test in SQL |
| `check_parity.py` | Compares the BigQuery output with `reports/results.json` from the DuckDB run |

## Result

Run in the BigQuery sandbox (asia-southeast1). [`bq_primary_result.json`](bq_primary_result.json) is the exported BigQuery output, and [`parity_check_output.txt`](parity_check_output.txt) shows all 7 metrics matching the DuckDB results: diff −0.158 pp, 95% CI −0.394 to +0.078 pp, z −1.311, p 0.19.

## Run it in the free BigQuery sandbox (no billing needed)

1. Go to the BigQuery console, sign in with a Google account, and accept the sandbox prompt. Create a project, e.g. `ab-test-portfolio`.
2. **Create a dataset** named `ab_test` (location: US or asia-southeast1).
3. **Load the two CSVs.** In the console: `ab_test` → *Create table* → *Upload*. Alternatively, use Cloud Shell:

   ```bash
   bq load --source_format=CSV --skip_leading_rows=1 \
     ab_test.raw_events data/raw/ab_data.csv \
     user_id:INT64,event_ts:TIMESTAMP,assigned_group:STRING,landing_page:STRING,converted:INT64

   bq load --source_format=CSV --skip_leading_rows=1 \
     ab_test.countries data/raw/countries.csv \
     user_id:INT64,country:STRING
   ```
   The schema renames `timestamp` → `event_ts` and `group` → `assigned_group`, matching the DuckDB staging step.
   Uploading through the console UI caps files at 100 MB; `ab_data.csv` is about 16 MB, so either route works.
4. **Run** `01_clean.sql`, then `02_metrics.sql`, in the query editor. Each file is a multi-statement script, so run it whole.
5. **Check the funnel:** `SELECT * FROM ab_test.cleaning_funnel ORDER BY step_order`. Expect 294,478 raw rows, 3,893 mismatches and 290,584 clean users.
6. **Export and verify:** save `SELECT * FROM ab_test.primary_result` as JSON to `bigquery/bq_primary_result.json`, then run `python bigquery/check_parity.py`.

## Dialect notes (DuckDB → BigQuery)

- `read_csv_auto(...)` → `bq load` with an explicit schema
- `CAST(ts AS DATE)` → `DATE(ts)`
- Ranked CTE with `WHERE rn = 1` → `QUALIFY ROW_NUMBER() OVER (...) = 1`
- `GROUP BY ALL` → explicit `GROUP BY` columns
- `<>` → `!=` (both are valid; `!=` is more common in GoogleSQL)
- No normal-CDF function in BigQuery, so the z-score is computed in SQL and the p-value in Python
- In the sandbox, tables expire after 60 days and DML (`INSERT`/`UPDATE`) is disabled. `CREATE OR REPLACE TABLE ... AS SELECT` still works.
