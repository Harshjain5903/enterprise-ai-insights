-- Canonical order item rows from raw, latest version per id, with
-- channel/category as of load time.
-- params: @load_start DATE, @load_end DATE, @salt STRING
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
