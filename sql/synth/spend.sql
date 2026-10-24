-- Daily campaign spend per paid channel. Channel names line up with
-- users.traffic_source in TheLook (Organic has no spend).
-- Weekend dip + a slow yearly cycle + per-day noise. Roughly 1 in 200
-- campaign-days is left out on purpose so "missing" and "zero" stay different.
-- params: @load_start DATE, @load_end DATE

WITH days AS (
  SELECT d FROM UNNEST(GENERATE_DATE_ARRAY(@load_start, DATE_SUB(@load_end, INTERVAL 1 DAY))) AS d
),
campaigns AS (
  SELECT * FROM UNNEST([
    STRUCT('Search' AS channel, 'SRCH-BRAND' AS campaign_id, 420.0 AS base),
    STRUCT('Search', 'SRCH-NONBRAND', 610.0),
    STRUCT('Facebook', 'FB-PROSPECTING', 380.0),
    STRUCT('Facebook', 'FB-RETARGETING', 190.0),
    STRUCT('Display', 'DSP-AWARENESS', 240.0),
    STRUCT('Email', 'EML-NEWSLETTER', 35.0)
  ])
)
SELECT
  d AS spend_date,
  channel,
  campaign_id,
  CAST(ROUND(
    base
    * CASE EXTRACT(DAYOFWEEK FROM d) WHEN 1 THEN 0.8 WHEN 7 THEN 0.85 ELSE 1.0 END
    * (1 + 0.3 * SIN(2 * ACOS(-1) * EXTRACT(DAYOFYEAR FROM d) / 365))
    * (0.85 + MOD(ABS(FARM_FINGERPRINT(CONCAT(campaign_id, CAST(d AS STRING)))), 300) / 1000),
  2) AS NUMERIC) AS spend_usd,
  'USD' AS currency
FROM days CROSS JOIN campaigns
WHERE MOD(ABS(FARM_FINGERPRINT(CONCAT('gap', campaign_id, CAST(d AS STRING)))), 200) != 0
