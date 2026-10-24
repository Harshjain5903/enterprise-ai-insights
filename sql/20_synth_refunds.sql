-- Refund ledger, see synth/refunds.sql for how it's generated.
-- params: @load_start DATE, @load_end DATE, @batch_id STRING

MERGE `${project}.${raw}.refunds` T
USING (
--#include synth/refunds.sql
) S
ON T.refund_id = S.refund_id
WHEN MATCHED AND T.refund_status IS DISTINCT FROM S.refund_status THEN
  UPDATE SET refund_status = S.refund_status, batch_id = @batch_id, ingested_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (refund_id, order_item_id, refund_ts, refund_amount, currency, refund_status, batch_id, ingested_at)
  VALUES (S.refund_id, S.order_item_id, S.refund_ts, S.refund_amount, S.currency, S.refund_status,
          @batch_id, CURRENT_TIMESTAMP());
