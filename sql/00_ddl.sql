-- Datasets and tables that the loads MERGE into. Safe to re-run.

CREATE SCHEMA IF NOT EXISTS `${project}.${raw}` OPTIONS (location = '${bq_location}');
CREATE SCHEMA IF NOT EXISTS `${project}.${curated}` OPTIONS (location = '${bq_location}');
CREATE SCHEMA IF NOT EXISTS `${project}.${mart}` OPTIONS (location = '${bq_location}');

CREATE TABLE IF NOT EXISTS `${project}.${raw}.orders` (
  order_id INT64 NOT NULL,
  user_id INT64,
  status STRING,
  created_at TIMESTAMP,
  shipped_at TIMESTAMP,
  delivered_at TIMESTAMP,
  returned_at TIMESTAMP,
  num_of_item INT64,
  batch_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at);

CREATE TABLE IF NOT EXISTS `${project}.${raw}.order_items` (
  id INT64 NOT NULL,
  order_id INT64 NOT NULL,
  user_id INT64,
  product_id INT64,
  status STRING,
  created_at TIMESTAMP,
  returned_at TIMESTAMP,
  sale_price FLOAT64,
  batch_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at);

CREATE TABLE IF NOT EXISTS `${project}.${raw}.refunds` (
  refund_id STRING NOT NULL,
  order_item_id INT64 NOT NULL,
  refund_ts TIMESTAMP NOT NULL,
  refund_amount NUMERIC NOT NULL,
  currency STRING NOT NULL,
  refund_status STRING NOT NULL,
  batch_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(refund_ts);

CREATE TABLE IF NOT EXISTS `${project}.${raw}.marketing_spend` (
  spend_date DATE NOT NULL,
  channel STRING NOT NULL,
  campaign_id STRING NOT NULL,
  spend_usd NUMERIC NOT NULL,
  currency STRING NOT NULL,
  batch_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY spend_date;

CREATE TABLE IF NOT EXISTS `${project}.${raw}.load_batches` (
  batch_id STRING NOT NULL,
  mode STRING,
  load_start DATE,
  load_end DATE,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  status STRING,
  error STRING
);

CREATE TABLE IF NOT EXISTS `${project}.${curated}.fact_order_item` (
  order_item_id INT64 NOT NULL,
  order_id INT64 NOT NULL,
  customer_key STRING,
  product_id INT64,
  channel STRING NOT NULL,
  category STRING NOT NULL,
  order_ts TIMESTAMP NOT NULL,
  order_date DATE NOT NULL,
  status STRING NOT NULL,
  sale_price NUMERIC NOT NULL,
  unit_cost NUMERIC,
  returned_at TIMESTAMP,
  batch_id STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY order_date
CLUSTER BY channel, category;
