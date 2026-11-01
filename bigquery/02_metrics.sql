-- bigquery/02_metrics.sql  (GoogleSQL / BigQuery dialect)
-- Port of sql/02_metrics.sql, plus the primary two-proportion z-test computed in SQL.

CREATE OR REPLACE TABLE ab_test.arm_metrics AS
SELECT
  assigned_group,
  COUNT(*)       AS users,
  SUM(converted) AS conversions,
  AVG(converted) AS conversion_rate
FROM ab_test.ab_clean
GROUP BY assigned_group;

CREATE OR REPLACE TABLE ab_test.daily_metrics AS
SELECT
  event_date,
  assigned_group,
  COUNT(*)       AS users,
  SUM(converted) AS conversions,
  AVG(converted) AS conversion_rate
FROM ab_test.ab_clean
GROUP BY event_date, assigned_group;

CREATE OR REPLACE TABLE ab_test.cumulative_metrics AS
SELECT
  event_date,
  assigned_group,
  SUM(users)       OVER w AS cum_users,
  SUM(conversions) OVER w AS cum_conversions
FROM ab_test.daily_metrics
WINDOW w AS (PARTITION BY assigned_group ORDER BY event_date
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);

CREATE OR REPLACE TABLE ab_test.country_metrics AS
SELECT
  country,
  assigned_group,
  COUNT(*)       AS users,
  SUM(converted) AS conversions,
  AVG(converted) AS conversion_rate
FROM ab_test.ab_clean
GROUP BY country, assigned_group;

-- Primary result: sample-ratio check inputs, difference, unpooled 95% CI and pooled z.
-- (BigQuery has no normal-CDF function, so the p-value is computed in
--  bigquery/check_parity.py from z; everything else is pure SQL.)
CREATE OR REPLACE TABLE ab_test.primary_result AS
WITH a AS (
  SELECT
    MAX(IF(assigned_group = 'control',   users, NULL))           AS n_c,
    MAX(IF(assigned_group = 'treatment', users, NULL))           AS n_t,
    MAX(IF(assigned_group = 'control',   conversion_rate, NULL)) AS p_c,
    MAX(IF(assigned_group = 'treatment', conversion_rate, NULL)) AS p_t,
    SUM(conversions) / SUM(users)                                AS p_pool
  FROM ab_test.arm_metrics
)
SELECT
  n_c,
  n_t,
  ROUND(100 * n_c / (n_c + n_t), 3)                                   AS control_share_pct,
  ROUND(100 * p_c, 3)                                                 AS control_cr_pct,
  ROUND(100 * p_t, 3)                                                 AS treatment_cr_pct,
  ROUND(100 * (p_t - p_c), 3)                                         AS diff_pp,
  ROUND(100 * ((p_t - p_c) - 1.959964 * SQRT(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)), 3) AS ci_low_pp,
  ROUND(100 * ((p_t - p_c) + 1.959964 * SQRT(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)), 3) AS ci_high_pp,
  ROUND((p_t - p_c) / SQRT(p_pool * (1 - p_pool) * (1 / n_c + 1 / n_t)), 3) AS z
FROM a;
