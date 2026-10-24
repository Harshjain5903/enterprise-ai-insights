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
