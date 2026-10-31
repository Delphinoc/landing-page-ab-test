-- 01_clean.sql
-- Load the raw experiment log, quantify assignment/logging issues, and build one
-- clean row per user for analysis.
-- Expects the variables data_dir to be substituted by src/run_analysis.py.

CREATE OR REPLACE TABLE raw_events AS
SELECT
    user_id,
    "timestamp"        AS event_ts,
    "group"            AS assigned_group,
    landing_page,
    converted
FROM read_csv_auto('{data_dir}/ab_data.csv');

CREATE OR REPLACE TABLE countries AS
SELECT user_id, country
FROM read_csv_auto('{data_dir}/countries.csv');

-- Rows where the assigned arm and the page actually served disagree.
-- These are treated as a logging / assignment bug: we cannot tell which
-- experience the user really saw, so they are excluded from the analysis.
CREATE OR REPLACE TABLE assignment_issues AS
SELECT
    assigned_group,
    landing_page,
    COUNT(*)                      AS n_rows,
    COUNT(DISTINCT user_id)       AS n_users
FROM raw_events
WHERE (assigned_group = 'control'   AND landing_page <> 'old_page')
   OR (assigned_group = 'treatment' AND landing_page <> 'new_page')
GROUP BY ALL;

-- One row per user: keep only correctly-served rows, and if a user still has
-- more than one row keep their first exposure (intent-to-treat on first visit).
CREATE OR REPLACE TABLE ab_clean AS
WITH valid AS (
    SELECT *
    FROM raw_events
    WHERE (assigned_group = 'control'   AND landing_page = 'old_page')
       OR (assigned_group = 'treatment' AND landing_page = 'new_page')
),
ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY event_ts) AS rn
    FROM valid
)
SELECT
    r.user_id,
    r.event_ts,
    CAST(r.event_ts AS DATE)   AS event_date,
    r.assigned_group,
    r.landing_page,
    r.converted,
    c.country
FROM ranked r
LEFT JOIN countries c USING (user_id)
WHERE r.rn = 1;

-- Audit trail of the cleaning funnel.
CREATE OR REPLACE TABLE cleaning_funnel AS
SELECT 'raw rows'                       AS step, COUNT(*) AS n FROM raw_events
UNION ALL
SELECT 'raw distinct users',            COUNT(DISTINCT user_id) FROM raw_events
UNION ALL
SELECT 'rows with group/page mismatch', COALESCE(SUM(n_rows), 0) FROM assignment_issues
UNION ALL
SELECT 'clean users (1 row each)',      COUNT(*) FROM ab_clean;
