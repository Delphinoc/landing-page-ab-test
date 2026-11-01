-- bigquery/01_clean.sql  (GoogleSQL / BigQuery dialect)
-- Port of sql/01_clean.sql. Run after loading ab_test.raw_events and ab_test.countries
-- (see bigquery/README.md). Works in the free BigQuery sandbox: CREATE TABLE AS SELECT
-- is DDL, not DML. Sandbox tables expire after 60 days by default.

-- Rows where the assigned arm and the page served disagree (logging / assignment bug).
CREATE OR REPLACE TABLE ab_test.assignment_issues AS
SELECT
  assigned_group,
  landing_page,
  COUNT(*)                AS n_rows,
  COUNT(DISTINCT user_id) AS n_users
FROM ab_test.raw_events
WHERE (assigned_group = 'control'   AND landing_page != 'old_page')
   OR (assigned_group = 'treatment' AND landing_page != 'new_page')
GROUP BY assigned_group, landing_page;

-- One row per user: correctly-served rows only, first exposure per user.
CREATE OR REPLACE TABLE ab_test.ab_clean AS
WITH valid AS (
  SELECT *
  FROM ab_test.raw_events
  WHERE (assigned_group = 'control'   AND landing_page = 'old_page')
     OR (assigned_group = 'treatment' AND landing_page = 'new_page')
)
SELECT
  v.user_id,
  v.event_ts,
  DATE(v.event_ts) AS event_date,
  v.assigned_group,
  v.landing_page,
  v.converted,
  c.country
FROM valid AS v
LEFT JOIN ab_test.countries AS c USING (user_id)
-- BigQuery's QUALIFY replaces the ranked-CTE + WHERE rn = 1 pattern
QUALIFY ROW_NUMBER() OVER (PARTITION BY v.user_id ORDER BY v.event_ts) = 1;

-- Audit trail of the cleaning funnel.
CREATE OR REPLACE TABLE ab_test.cleaning_funnel AS
SELECT 1 AS step_order, 'raw rows' AS step, COUNT(*) AS n FROM ab_test.raw_events
UNION ALL
SELECT 2, 'raw distinct users', COUNT(DISTINCT user_id) FROM ab_test.raw_events
UNION ALL
SELECT 3, 'rows with group/page mismatch', COALESCE(SUM(n_rows), 0) FROM ab_test.assignment_issues
UNION ALL
SELECT 4, 'clean users (1 row each)', COUNT(*) FROM ab_test.ab_clean;
