# enterprise-ai-insights

Weekly retail performance reports where the numbers come from BigQuery and
Gemini only writes the sentences around them.

The data is Google's [TheLook eCommerce](https://console.cloud.google.com/marketplace/product/bigquery-public-data/thelook-ecommerce)
public dataset (`bigquery-public-data.thelook_ecommerce`). It's a fake online
clothing store with orders, items, products and users. It has no refund
ledger and no ad spend, so I generate both from its return data (see
[Data](#data)).

## How it works

```
thelook (public)  ──MERGE──>  raw  ──>  curated  ──>  mart  ──>  evidence packet  ──>  gemini  ──>  validator  ──>  report
                                 \_ synthetic refunds + spend                                            \_ fallback template
```

1. **Refresh** (`insights refresh`) pulls the last 7 days from TheLook into
   `raw` with MERGE, so re-running a day doesn't duplicate anything. Then it
   rebuilds the curated facts and the daily marts and runs 16 data quality checks.
2. **Evidence**: for a given week the report SQL computes net sales, orders,
   AOV, refunds, a revenue decomposition (order count vs basket size), the
   4-week average, the top 3 category movers and per-channel spend. Every
   value becomes a typed fact with an id (`F_NET_SALES_CUR`, `F_CAT1_NET_CHANGE`, ...).
3. **Narrative**: the packet goes to `gemini-2.5-flash` on Vertex AI
   (temperature 0.2, JSON output against a pydantic schema). Every insight has
   to list the facts it uses.
4. **Validation**: before anything gets published, `validator.py` checks that
   every number in the text matches a fact the insight cites (rounding is
   allowed, new numbers aren't), that the ids exist, that "up"/"down" agrees
   with the sign, and that there's no causal wording ("because", "due to", ...).
5. If the model errors out or the draft fails validation, a template report
   built straight from the facts gets published instead, and the rejected draft
   is kept in `meta.json` so I can look at it.

The point is that Gemini never does any arithmetic. If a number appears in a
report, it came out of SQL.

## Data

| table | grain | notes |
|---|---|---|
| `raw.orders`, `raw.order_items` | one row per id | merged from TheLook over a rolling window |
| `raw.refunds` | refund event | **synthetic**: built from `order_items.returned_at`. Full, partial and two-part refunds, 1-9 days after the return, some rejected or pending |
| `raw.marketing_spend` | day × campaign | **synthetic**: 6 campaigns across the paid TheLook traffic sources, with weekly/yearly patterns and a few missing days on purpose |
| `curated.fact_order_item` | order item | category/channel frozen at sale time, customer id hashed with a salt |
| `curated.fact_refund` | refund event | carries the item's channel/category so it can be summed on its own date |
| `mart.daily_kpi` | day × channel × category | `orders` here is **not** additive across categories |
| `mart.daily_totals` | day | company-level distinct orders/customers |
| `mart.daily_spend` | day × channel | |

Some definitions that matter:

- **Net sales** = item sale price for non-cancelled items, minus *settled*
  refunds dated in the same period. Refunds count on the day they settle, not
  pushed back onto the original sale. No tax or shipping (TheLook doesn't have them).
- **AOV** = net sales / distinct orders.
- **Channel** is the customer's acquisition source (`users.traffic_source`),
  not per-order attribution. Spend vs sales per channel is reported side by
  side and never as ROAS.
- Weeks are Monday to Sunday in America/Chicago.

Names, emails and addresses from `users` are never loaded. Only aggregates go
to the model.

## Setup

Needs a GCP project with billing, BigQuery and Vertex AI enabled.

```bash
make install
cp .env.example .env        # set GOOGLE_CLOUD_PROJECT
gcloud auth application-default login

make full                   # first load: 365 days of history
make report                 # report for the last complete week
```

Reports land in `out/<report_id>/` as `report.md`, `report.html`,
`report.json`, plus the `packet.json` that was sent and a `meta.json` with
timings, token counts, hashes and any validation failures.

Other commands:

```bash
insights refresh                    # daily incremental (7 day lookback)
insights dq                         # just the data quality checks
insights report --week 2026-09-28   # specific week (must be a Monday)
insights report --no-llm --no-log   # template report, no gemini call
```

Every query runs with `maximum_bytes_billed` (2 GB by default, `MAX_BYTES_BILLED`
to change it) so a bad query can't scan something huge.

## Tests and evals

```bash
make test                                      # unit tests, no GCP needed
python -m evals.run_evals --narrator fallback  # eval harness against the template
python -m evals.run_evals                      # the real thing, calls gemini 100 times
```

`evals/cases.jsonl` has 100 generated cases (`evals/make_cases.py`, fixed
seed): normal drops and rises, refunds up while sales are up, fewer orders but
bigger baskets, zero and tiny baselines, partial weeks, short history, missing
spend days, and prompt injection hidden in category and channel names.

Each run prints and saves:

- `schema_valid`: the model returned JSON that matches the schema
- `numeric_correct`: numbers in the text that match a cited fact, over all numbers checked
- `citation_complete`: every insight cites something and the expected key facts are cited
- `forbidden_hits`: injected text or causal wording showing up in the report
- latency p50 / p95

Results go to `evals/results/` (gitignored). The CI workflow runs the
template version so the harness itself stays honest.

## Scheduling

`deploy/README.md` has the Cloud Run job + Cloud Scheduler setup (06:00
America/Chicago, dedicated service account, salt in Secret Manager).

## Layout

```
sql/          00_ddl, 10 raw loads, 20/21 synthetic refunds + spend, 30 curated, 40 marts
insights/
  pipeline.py   refresh: runs the sql steps, records the batch, runs dq
  quality.py    the 16 checks
  evidence.py   weekly facts -> packet (fetch and build are separate)
  metrics.py    deltas, decomposition, robust z
  narrator.py   gemini call, retries, one repair attempt
  validator.py  number / citation / direction / causal checks
  fallback.py   template report
  report.py     ties it together, writes outputs + report_snapshot
evals/        case generator and runner
tests/
```

## Not done yet

- anomaly flags per day (the robust z helper is there, not wired into the packet)
- push HTML reports to a bucket instead of the container's `/tmp`
- the causal-wording check is a word list, it will miss things
- category movers are by absolute change, so big categories always win
