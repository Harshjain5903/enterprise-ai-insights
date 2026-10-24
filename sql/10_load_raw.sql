-- Pull the load window out of the public TheLook tables.
-- params: @load_start DATE, @load_end DATE (exclusive), @batch_id STRING
--
-- TheLook gets regenerated upstream so statuses on recent orders move around;
-- MERGE keeps one row per id and only touches rows that actually changed.

MERGE `${project}.${raw}.orders` T
USING (
  SELECT order_id, user_id, status, created_at, shipped_at, delivered_at, returned_at, num_of_item
  FROM `bigquery-public-data.thelook_ecommerce.orders`
  WHERE DATE(created_at, '${tz}') >= @load_start
    AND DATE(created_at, '${tz}') < @load_end
) S
ON T.order_id = S.order_id
WHEN MATCHED AND (T.status IS DISTINCT FROM S.status
                  OR T.returned_at IS DISTINCT FROM S.returned_at
                  OR T.delivered_at IS DISTINCT FROM S.delivered_at) THEN
  UPDATE SET status = S.status, shipped_at = S.shipped_at, delivered_at = S.delivered_at,
             returned_at = S.returned_at, batch_id = @batch_id, ingested_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (order_id, user_id, status, created_at, shipped_at, delivered_at, returned_at,
          num_of_item, batch_id, ingested_at)
  VALUES (S.order_id, S.user_id, S.status, S.created_at, S.shipped_at, S.delivered_at,
          S.returned_at, S.num_of_item, @batch_id, CURRENT_TIMESTAMP());

MERGE `${project}.${raw}.order_items` T
USING (
  SELECT id, order_id, user_id, product_id, status, created_at, returned_at, sale_price
  FROM `bigquery-public-data.thelook_ecommerce.order_items`
  WHERE DATE(created_at, '${tz}') >= @load_start
    AND DATE(created_at, '${tz}') < @load_end
) S
ON T.id = S.id
WHEN MATCHED AND (T.status IS DISTINCT FROM S.status
                  OR T.returned_at IS DISTINCT FROM S.returned_at) THEN
  UPDATE SET status = S.status, returned_at = S.returned_at,
             batch_id = @batch_id, ingested_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (id, order_id, user_id, product_id, status, created_at, returned_at, sale_price,
          batch_id, ingested_at)
  VALUES (S.id, S.order_id, S.user_id, S.product_id, S.status, S.created_at, S.returned_at,
          S.sale_price, @batch_id, CURRENT_TIMESTAMP());

-- Small dimension tables, just snapshot them.
CREATE OR REPLACE TABLE `${project}.${raw}.products` AS
SELECT id, name, brand, category, department, cost, retail_price, CURRENT_TIMESTAMP() AS ingested_at
FROM `bigquery-public-data.thelook_ecommerce.products`;

-- No names, emails or street addresses past this point.
CREATE OR REPLACE TABLE `${project}.${raw}.users` AS
SELECT id, age, gender, state, country, traffic_source, created_at, CURRENT_TIMESTAMP() AS ingested_at
FROM `bigquery-public-data.thelook_ecommerce.users`;
