-- 02_metrics.sql
-- Metric tables used by the statistical analysis and charts.

-- Primary metric by arm: user-level conversion rate.
CREATE OR REPLACE TABLE arm_metrics AS
SELECT
    assigned_group,
    COUNT(*)            AS users,
    SUM(converted)      AS conversions,
    AVG(converted)      AS conversion_rate
FROM ab_clean
GROUP BY ALL
ORDER BY assigned_group;

-- Daily metrics by arm (for novelty / time-trend checks).
CREATE OR REPLACE TABLE daily_metrics AS
SELECT
    event_date,
    assigned_group,
    COUNT(*)            AS users,
    SUM(converted)      AS conversions,
    AVG(converted)      AS conversion_rate
FROM ab_clean
GROUP BY ALL
ORDER BY event_date, assigned_group;

-- Cumulative metrics by day (to show what an analyst "peeking" daily would have seen).
CREATE OR REPLACE TABLE cumulative_metrics AS
SELECT
    event_date,
    assigned_group,
    SUM(users)       OVER w AS cum_users,
    SUM(conversions) OVER w AS cum_conversions
FROM daily_metrics
WINDOW w AS (PARTITION BY assigned_group ORDER BY event_date
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
ORDER BY event_date, assigned_group;

-- Segment metrics by country (exploratory).
CREATE OR REPLACE TABLE country_metrics AS
SELECT
    country,
    assigned_group,
    COUNT(*)            AS users,
    SUM(converted)      AS conversions,
    AVG(converted)      AS conversion_rate
FROM ab_clean
GROUP BY ALL
ORDER BY country, assigned_group;
