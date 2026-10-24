-- Sandbox version of 10_load_raw.sql: no DML, so rebuild the raw tables for
-- the whole history window each run. TheLook is small enough that this is fine.
-- params: @load_start DATE, @load_end DATE, @batch_id STRING

CREATE OR REPLACE TABLE `${project}.${raw}.orders` AS
SELECT order_id, user_id, status, created_at, shipped_at, delivered_at, returned_at, num_of_item,
       @batch_id AS batch_id, CURRENT_TIMESTAMP() AS ingested_at
FROM `bigquery-public-data.thelook_ecommerce.orders`
WHERE DATE(created_at, '${tz}') >= @load_start
  AND DATE(created_at, '${tz}') < @load_end;

CREATE OR REPLACE TABLE `${project}.${raw}.order_items` AS
SELECT id, order_id, user_id, product_id, status, created_at, returned_at, sale_price,
       @batch_id AS batch_id, CURRENT_TIMESTAMP() AS ingested_at
FROM `bigquery-public-data.thelook_ecommerce.order_items`
WHERE DATE(created_at, '${tz}') >= @load_start
  AND DATE(created_at, '${tz}') < @load_end;

CREATE OR REPLACE TABLE `${project}.${raw}.products` AS
SELECT id, name, brand, category, department, cost, retail_price, CURRENT_TIMESTAMP() AS ingested_at
FROM `bigquery-public-data.thelook_ecommerce.products`;

CREATE OR REPLACE TABLE `${project}.${raw}.users` AS
SELECT id, age, gender, state, country, traffic_source, created_at, CURRENT_TIMESTAMP() AS ingested_at
FROM `bigquery-public-data.thelook_ecommerce.users`;
