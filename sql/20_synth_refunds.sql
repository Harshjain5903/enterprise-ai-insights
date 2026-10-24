-- TheLook only has returned_at on order items, there is no refund ledger.
-- This builds one from the returns so refunds can be handled as their own fact:
--   * most returns are refunded in full, some partially, ~6% in two payments
--   * refund lands 1-9 days after the return
--   * ~3% get rejected, anything with a future refund_ts is still pending
-- Everything is keyed off FARM_FINGERPRINT so reruns produce the same ledger.
-- params: @load_start DATE, @load_end DATE, @batch_id STRING

MERGE `${project}.${raw}.refunds` T
USING (
  WITH returned AS (
    SELECT
      id AS order_item_id,
      CAST(ROUND(sale_price, 2) AS NUMERIC) AS sale_price,
      returned_at,
      MOD(ABS(FARM_FINGERPRINT(CAST(id AS STRING))), 1000) AS h
    FROM `bigquery-public-data.thelook_ecommerce.order_items`
    WHERE returned_at IS NOT NULL
      AND DATE(returned_at, '${tz}') >= @load_start
      AND DATE(returned_at, '${tz}') < @load_end
  ),
  events AS (
    SELECT order_item_id, 1 AS seq, returned_at, h,
      CASE
        WHEN h < 60 THEN ROUND(sale_price * 0.5, 2)
        WHEN h < 200 THEN ROUND(sale_price * (0.6 + MOD(h, 30) / 100), 2)
        ELSE sale_price
      END AS amount
    FROM returned
    UNION ALL
    SELECT order_item_id, 2 AS seq, returned_at, h, sale_price - ROUND(sale_price * 0.5, 2)
    FROM returned
    WHERE h < 60
  ),
  timed AS (
    SELECT *,
      TIMESTAMP_ADD(returned_at, INTERVAL (1 + MOD(h + seq * 7, 9)) * 24 + MOD(h, 13) HOUR) AS refund_ts
    FROM events
  )
  SELECT
    CONCAT('RF-', CAST(order_item_id AS STRING), '-', CAST(seq AS STRING)) AS refund_id,
    order_item_id,
    refund_ts,
    amount AS refund_amount,
    'USD' AS currency,
    CASE
      WHEN h >= 970 THEN 'rejected'
      WHEN refund_ts > CURRENT_TIMESTAMP() THEN 'pending'
      ELSE 'settled'
    END AS refund_status
  FROM timed
) S
ON T.refund_id = S.refund_id
WHEN MATCHED AND T.refund_status IS DISTINCT FROM S.refund_status THEN
  UPDATE SET refund_status = S.refund_status, batch_id = @batch_id, ingested_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (refund_id, order_item_id, refund_ts, refund_amount, currency, refund_status, batch_id, ingested_at)
  VALUES (S.refund_id, S.order_item_id, S.refund_ts, S.refund_amount, S.currency, S.refund_status,
          @batch_id, CURRENT_TIMESTAMP());
