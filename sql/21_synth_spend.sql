-- Campaign spend, see synth/spend.sql.
-- params: @load_start DATE, @load_end DATE, @batch_id STRING

MERGE `${project}.${raw}.marketing_spend` T
USING (
--#include synth/spend.sql
) S
ON T.spend_date = S.spend_date AND T.campaign_id = S.campaign_id
WHEN NOT MATCHED THEN
  INSERT (spend_date, channel, campaign_id, spend_usd, currency, batch_id, ingested_at)
  VALUES (S.spend_date, S.channel, S.campaign_id, S.spend_usd, S.currency, @batch_id, CURRENT_TIMESTAMP());
