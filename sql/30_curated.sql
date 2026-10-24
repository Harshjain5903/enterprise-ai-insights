-- Curated layer. fact_order_item is merged over the lookback window, the
-- rest is small enough to rebuild every run.
-- params: @load_start DATE, @load_end DATE, @batch_id STRING, @salt STRING

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

MERGE `${project}.${curated}.fact_order_item` T
USING (
  SELECT
    oi.id AS order_item_id,
    oi.order_id,
    TO_HEX(SHA256(CONCAT(@salt, CAST(oi.user_id AS STRING)))) AS customer_key,
    oi.product_id,
    COALESCE(u.traffic_source, 'Unknown') AS channel,
    COALESCE(p.category, 'Unknown') AS category,
    oi.created_at AS order_ts,
    DATE(oi.created_at, '${tz}') AS order_date,
    LOWER(oi.status) AS status,
    CAST(ROUND(oi.sale_price, 2) AS NUMERIC) AS sale_price,
    p.unit_cost,
    oi.returned_at
  FROM (
    SELECT *
    FROM `${project}.${raw}.order_items`
    WHERE DATE(created_at, '${tz}') >= @load_start
      AND DATE(created_at, '${tz}') < @load_end
    QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY ingested_at DESC, batch_id DESC) = 1
  ) oi
  LEFT JOIN `${project}.${raw}.users` u ON u.id = oi.user_id
  LEFT JOIN `${project}.${curated}.dim_product` p ON p.product_id = oi.product_id
) S
ON T.order_item_id = S.order_item_id
-- category/channel are kept as they were at sale time, only lifecycle fields move
WHEN MATCHED AND (T.status != S.status OR T.returned_at IS DISTINCT FROM S.returned_at) THEN
  UPDATE SET status = S.status, returned_at = S.returned_at,
             batch_id = @batch_id, updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (order_item_id, order_id, customer_key, product_id, channel, category, order_ts,
          order_date, status, sale_price, unit_cost, returned_at, batch_id, updated_at)
  VALUES (S.order_item_id, S.order_id, S.customer_key, S.product_id, S.channel, S.category,
          S.order_ts, S.order_date, S.status, S.sale_price, S.unit_cost, S.returned_at,
          @batch_id, CURRENT_TIMESTAMP());

-- Refunds carry the item's channel/category so they can be aggregated on
-- their own date without joining back to items (which fans out).
CREATE OR REPLACE TABLE `${project}.${curated}.fact_refund`
PARTITION BY refund_date
CLUSTER BY channel, category AS
SELECT
  r.refund_id,
  r.order_item_id,
  f.order_id,
  f.product_id,
  COALESCE(f.channel, 'Unknown') AS channel,
  COALESCE(f.category, 'Unknown') AS category,
  r.refund_ts,
  DATE(r.refund_ts, '${tz}') AS refund_date,
  r.refund_amount,
  r.currency,
  r.refund_status
FROM (
  SELECT * FROM `${project}.${raw}.refunds`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY refund_id ORDER BY ingested_at DESC) = 1
) r
LEFT JOIN `${project}.${curated}.fact_order_item` f USING (order_item_id);
