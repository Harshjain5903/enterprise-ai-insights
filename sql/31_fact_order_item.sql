-- params: @load_start DATE, @load_end DATE, @batch_id STRING, @salt STRING

MERGE `${project}.${curated}.fact_order_item` T
USING (
--#include select/order_items.sql
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
