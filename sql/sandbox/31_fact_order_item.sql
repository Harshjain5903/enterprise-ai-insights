-- params: @load_start DATE, @load_end DATE, @batch_id STRING, @salt STRING

CREATE OR REPLACE TABLE `${project}.${curated}.fact_order_item`
CLUSTER BY channel, category AS
SELECT *, @batch_id AS batch_id, CURRENT_TIMESTAMP() AS updated_at
FROM (
--#include select/order_items.sql
);
