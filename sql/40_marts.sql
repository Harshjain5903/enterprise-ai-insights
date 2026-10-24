-- Reporting marts. Refunds are counted on refund_date (transaction period),
-- not pushed back onto the original sale day.
-- Cancelled items are not sales. Returned items are: the sale happened and
-- the settled refund comes off separately.

CREATE OR REPLACE TABLE `${project}.${mart}.daily_kpi`
PARTITION BY day
CLUSTER BY channel, category AS
WITH sales AS (
  SELECT
    order_date AS day, channel, category,
    COUNT(DISTINCT order_id) AS orders,
    COUNT(*) AS items,
    SUM(sale_price) AS gross_sales,
    SUM(IFNULL(unit_cost, 0)) AS cogs
  FROM `${project}.${curated}.fact_order_item`
  WHERE status != 'cancelled'
  GROUP BY 1, 2, 3
),
refunds AS (
  SELECT
    refund_date AS day, channel, category,
    COUNT(*) AS refund_events,
    SUM(refund_amount) AS settled_refunds
  FROM `${project}.${curated}.fact_refund`
  WHERE refund_status = 'settled' AND currency = 'USD'
  GROUP BY 1, 2, 3
)
SELECT
  day, channel, category,
  IFNULL(s.orders, 0) AS orders,  -- not additive across categories
  IFNULL(s.items, 0) AS items,
  IFNULL(s.gross_sales, 0) AS gross_sales,
  IFNULL(s.cogs, 0) AS cogs,
  IFNULL(r.refund_events, 0) AS refund_events,
  IFNULL(r.settled_refunds, 0) AS settled_refunds,
  IFNULL(s.gross_sales, 0) - IFNULL(r.settled_refunds, 0) AS net_sales
FROM sales s
FULL OUTER JOIN refunds r USING (day, channel, category);

-- Company-level day totals. Distinct orders/customers have to be counted
-- here, summing daily_kpi.orders would double count multi-category orders.
CREATE OR REPLACE TABLE `${project}.${mart}.daily_totals`
PARTITION BY day AS
WITH sales AS (
  SELECT
    order_date AS day,
    COUNT(DISTINCT order_id) AS orders,
    COUNT(DISTINCT customer_key) AS customers,
    COUNT(*) AS items,
    SUM(sale_price) AS gross_sales
  FROM `${project}.${curated}.fact_order_item`
  WHERE status != 'cancelled'
  GROUP BY 1
),
refunds AS (
  SELECT refund_date AS day, COUNT(*) AS refund_events, SUM(refund_amount) AS settled_refunds
  FROM `${project}.${curated}.fact_refund`
  WHERE refund_status = 'settled' AND currency = 'USD'
  GROUP BY 1
)
SELECT
  day,
  IFNULL(s.orders, 0) AS orders,
  IFNULL(s.customers, 0) AS customers,
  IFNULL(s.items, 0) AS items,
  IFNULL(s.gross_sales, 0) AS gross_sales,
  IFNULL(r.refund_events, 0) AS refund_events,
  IFNULL(r.settled_refunds, 0) AS settled_refunds,
  IFNULL(s.gross_sales, 0) - IFNULL(r.settled_refunds, 0) AS net_sales
FROM sales s
FULL OUTER JOIN refunds r USING (day);

CREATE OR REPLACE TABLE `${project}.${mart}.daily_spend`
PARTITION BY day AS
SELECT
  spend_date AS day,
  channel,
  COUNT(DISTINCT campaign_id) AS active_campaigns,
  SUM(spend_usd) AS spend_usd
FROM `${project}.${raw}.marketing_spend`
WHERE currency = 'USD'
GROUP BY 1, 2;

CREATE TABLE IF NOT EXISTS `${project}.${mart}.dq_results` (
  run_id STRING NOT NULL,
  check_name STRING NOT NULL,
  severity STRING NOT NULL,
  failures INT64 NOT NULL,
  checked_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS `${project}.${mart}.report_snapshot` (
  report_id STRING NOT NULL,
  week_start DATE NOT NULL,
  status STRING NOT NULL,
  model STRING,
  prompt_hash STRING,
  evidence_hash STRING,
  quality_status STRING,
  violations ARRAY<STRING>,
  latency_ms INT64,
  created_at TIMESTAMP NOT NULL
);
