-- Dimensions, small enough to rebuild every run.
-- params: @salt STRING

CREATE OR REPLACE TABLE `${project}.${curated}.dim_product` AS
SELECT
  id AS product_id,
  COALESCE(NULLIF(TRIM(category), ''), 'Unknown') AS category,
  department,
  brand,
  CAST(ROUND(cost, 2) AS NUMERIC) AS unit_cost
FROM `${project}.${raw}.products`;

CREATE OR REPLACE TABLE `${project}.${curated}.dim_customer` AS
SELECT
  TO_HEX(SHA256(CONCAT(@salt, CAST(id AS STRING)))) AS customer_key,
  COALESCE(traffic_source, 'Unknown') AS acquisition_channel,
  DATE(created_at, '${tz}') AS signup_date,
  country,
  state,
  CASE
    WHEN age < 25 THEN '18-24'
    WHEN age < 35 THEN '25-34'
    WHEN age < 50 THEN '35-49'
    ELSE '50+'
  END AS age_band
FROM `${project}.${raw}.users`;
