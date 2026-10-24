-- params: @load_start DATE, @load_end DATE, @batch_id STRING

CREATE OR REPLACE TABLE `${project}.${raw}.marketing_spend` AS
SELECT *, @batch_id AS batch_id, CURRENT_TIMESTAMP() AS ingested_at
FROM (
--#include synth/spend.sql
);
