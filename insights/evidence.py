"""Build the evidence packet: the only thing the model gets to see.

Fetching (BigQuery) and building (pure python) are kept apart so the builder
can be tested with plain dicts.
"""
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from .metrics import D, compare, decompose_revenue, moving_average, q2, safe_div

PACKET_VERSION = "1.1"
METRIC_CONTRACT = "rev-metrics-v1"
MAX_FACTS = 40
TOP_CATEGORIES = 3

Unit = Literal["USD", "orders", "customers", "items", "events", "pct"]


class Fact(BaseModel):
    fact_id: str
    metric: str
    value: str
    unit: Unit
    period: Literal["current", "prior", "change", "trailing_4w"]
    segment: str = "all"


class Window(BaseModel):
    start: dt.date
    end_exclusive: dt.date


class Packet(BaseModel):
    packet_version: str = PACKET_VERSION
    report_id: str
    report_type: str = "weekly_revenue_change"
    time_zone: str
    period: Window
    comparison: Window
    metric_contract_version: str = METRIC_CONTRACT
    query_hashes: dict[str, str] = {}
    quality_status: Literal["PASS", "WARN", "BLOCK"]
    facts: list[Fact]
    limitations: list[str] = []

    def evidence_hash(self) -> str:
        body = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def fact_index(self) -> dict[str, Fact]:
        return {f.fact_id: f for f in self.facts}


@dataclass
class WeeklyInputs:
    week_start: dt.date
    current: dict             # totals row for the report week
    prior: dict               # totals row for the week before
    trailing_net: list        # net_sales of the 4 weeks before `prior`
    categories: list = field(default_factory=list)  # {category, net_cur, net_prev}
    channels: list = field(default_factory=list)    # {channel, net_cur, net_prev, spend_cur, spend_prev, spend_days_cur}
    days_cur: int = 7
    days_prev: int = 7
    quality_status: str = "PASS"
    quality_notes: list = field(default_factory=list)
    query_hashes: dict = field(default_factory=dict)


def _fmt(x: Decimal, unit: str) -> str:
    if unit == "pct":
        return str(x.quantize(Decimal("0.1")))
    if unit == "USD":
        return str(q2(x))
    return str(int(x))


class _Facts:
    def __init__(self):
        self.items: list[Fact] = []

    def add(self, fact_id, metric, value, unit, period, segment="all"):
        if value is None:
            return
        self.items.append(Fact(fact_id=fact_id, metric=metric, value=_fmt(D(value), unit),
                               unit=unit, period=period, segment=segment))


def build_packet(inp: WeeklyInputs, tz: str = "America/Chicago") -> Packet:
    ws = inp.week_start
    period = Window(start=ws, end_exclusive=ws + dt.timedelta(days=7))
    comparison = Window(start=ws - dt.timedelta(days=7), end_exclusive=ws)
    limitations = [
        "Refund and marketing spend data are synthetic, derived from TheLook returns.",
        "Channel means the customer's acquisition source, not per-order attribution.",
    ]
    limitations += [f"Data quality: {n}" for n in inp.quality_notes]

    f = _Facts()
    cur, prev = inp.current, inp.prior

    net = compare(prev.get("net_sales"), cur.get("net_sales"))
    f.add("F_NET_SALES_CUR", "net_sales", net.current, "USD", "current")
    f.add("F_NET_SALES_PRIOR", "net_sales", net.previous, "USD", "prior")
    f.add("F_NET_SALES_CHANGE", "net_sales_change", net.absolute, "USD", "change")
    f.add("F_NET_SALES_CHANGE_PCT", "net_sales_change_pct", net.pct, "pct", "change")
    if net.reason:
        limitations.append("Prior week net sales were zero, so no percent change is given.")

    f.add("F_GROSS_SALES_CUR", "gross_sales", cur.get("gross_sales"), "USD", "current")
    f.add("F_GROSS_SALES_PRIOR", "gross_sales", prev.get("gross_sales"), "USD", "prior")
    f.add("F_REFUNDS_CUR", "settled_refunds", cur.get("settled_refunds"), "USD", "current")
    f.add("F_REFUNDS_PRIOR", "settled_refunds", prev.get("settled_refunds"), "USD", "prior")
    for key, row, period_name in (("CUR", cur, "current"), ("PRIOR", prev, "prior")):
        rate = safe_div(D(row.get("settled_refunds")), D(row.get("gross_sales")))
        f.add(f"F_REFUND_RATE_{key}", "refund_rate", None if rate is None else rate * 100,
              "pct", period_name)

    orders = compare(prev.get("orders"), cur.get("orders"))
    f.add("F_ORDERS_CUR", "orders", orders.current, "orders", "current")
    f.add("F_ORDERS_PRIOR", "orders", orders.previous, "orders", "prior")
    f.add("F_ORDERS_CHANGE_PCT", "orders_change_pct", orders.pct, "pct", "change")
    f.add("F_CUSTOMERS_CUR", "customers", cur.get("customers"), "customers", "current")

    aov_cur = safe_div(net.current, orders.current)
    aov_prev = safe_div(net.previous, orders.previous)
    f.add("F_AOV_CUR", "aov", aov_cur, "USD", "current")
    f.add("F_AOV_PRIOR", "aov", aov_prev, "USD", "prior")
    if aov_cur is not None and aov_prev is not None:
        f.add("F_AOV_CHANGE_PCT", "aov_change_pct", compare(aov_prev, aov_cur).pct, "pct", "change")
        dec = decompose_revenue(orders.previous, aov_prev, orders.current, aov_cur)
        f.add("F_VOLUME_EFFECT", "net_sales_change_from_order_count", dec.volume_effect, "USD", "change")
        f.add("F_BASKET_EFFECT", "net_sales_change_from_aov", dec.basket_effect, "USD", "change")

    if len(inp.trailing_net) == 4:
        avg = moving_average(inp.trailing_net)
        f.add("F_NET_SALES_4W_AVG", "net_sales_4w_avg", avg, "USD", "trailing_4w")
        f.add("F_NET_SALES_VS_4W_PCT", "net_sales_vs_4w_avg_pct", compare(avg, net.current).pct,
              "pct", "change")
    else:
        limitations.append("Less than 4 complete weeks of history before the comparison week.")

    movers = sorted(inp.categories, key=lambda c: abs(D(c["net_cur"]) - D(c["net_prev"])),
                    reverse=True)[:TOP_CATEGORIES]
    for i, c in enumerate(movers, 1):
        # ids are positional on purpose: category names come from source data
        # and shouldn't end up inside identifiers the validator trusts
        seg = str(c["category"])[:80]
        d = compare(c["net_prev"], c["net_cur"])
        f.add(f"F_CAT{i}_NET_CUR", "category_net_sales", d.current, "USD", "current", seg)
        f.add(f"F_CAT{i}_NET_PRIOR", "category_net_sales", d.previous, "USD", "prior", seg)
        f.add(f"F_CAT{i}_NET_CHANGE", "category_net_sales_change", d.absolute, "USD", "change", seg)

    for i, ch in enumerate(sorted(inp.channels, key=lambda c: str(c["channel"])), 1):
        seg = str(ch["channel"])[:40]
        f.add(f"F_CH{i}_NET_CUR", "channel_net_sales", ch.get("net_cur"), "USD", "current", seg)
        if D(ch.get("spend_cur")) > 0 or D(ch.get("spend_prev")) > 0:
            f.add(f"F_CH{i}_SPEND_CUR", "channel_spend", ch.get("spend_cur"), "USD", "current", seg)
            sp = compare(ch.get("spend_prev"), ch.get("spend_cur"))
            f.add(f"F_CH{i}_SPEND_CHANGE_PCT", "channel_spend_change_pct", sp.pct, "pct", "change", seg)
            if ch.get("spend_days_cur", 7) < 7:
                limitations.append(f"Spend for {seg} is missing on {7 - ch['spend_days_cur']} day(s).")

    if inp.days_cur < 7 or inp.days_prev < 7:
        limitations.append(f"Incomplete weeks: {inp.days_cur}/7 days current, {inp.days_prev}/7 prior.")

    status = inp.quality_status
    if status == "PASS" and (inp.days_cur < 7 or inp.days_prev < 7):
        status = "WARN"

    return Packet(
        report_id=f"wk-{ws:%Y%m%d}-{dt.datetime.now(dt.timezone.utc):%H%M%S}",
        time_zone=tz,
        period=period,
        comparison=comparison,
        query_hashes=inp.query_hashes,
        quality_status=status,
        facts=f.items[:MAX_FACTS],
        limitations=limitations,
    )


def approx_tokens(packet: Packet) -> int:
    # rough, json is token-dense. good enough for a budget check
    return len(packet.model_dump_json()) // 3


def trim_to_budget(packet: Packet, max_tokens: int) -> Packet:
    facts = list(packet.facts)
    trimmed = packet
    while approx_tokens(trimmed) > max_tokens and facts:
        # drop channel facts first, then categories, keep the headline numbers
        idx = next((i for i in range(len(facts) - 1, -1, -1) if facts[i].fact_id.startswith("F_CH")),
                   next((i for i in range(len(facts) - 1, -1, -1) if facts[i].fact_id.startswith("F_CAT")),
                        None))
        if idx is None:
            break
        facts.pop(idx)
        trimmed = packet.model_copy(update={"facts": facts})
    return trimmed


# --- fetching ----------------------------------------------------------------

def week_expr(col: str = "day") -> str:
    # 0 = report week, -1 = comparison week, ... FLOOR because DIV truncates toward zero
    return f"CAST(FLOOR(DATE_DIFF({col}, @week_start, DAY) / 7) AS INT64)"


WEEK_EXPR = week_expr()

TOTALS_SQL = f"""
SELECT {WEEK_EXPR} AS wk,
       COUNTIF(orders > 0) AS days_with_orders,
       SUM(items) AS items,
       SUM(gross_sales) AS gross_sales, SUM(settled_refunds) AS settled_refunds,
       SUM(net_sales) AS net_sales
FROM `${{project}}.${{mart}}.daily_totals`
WHERE day >= DATE_SUB(@week_start, INTERVAL 35 DAY) AND day < DATE_ADD(@week_start, INTERVAL 7 DAY)
GROUP BY wk ORDER BY wk
"""
# orders/customers are counted distinct over the whole week separately,
# summing the daily distinct counts would double count

CUSTOMERS_SQL = """
SELECT COUNT(DISTINCT customer_key) AS customers
FROM `${project}.${curated}.fact_order_item`
WHERE order_date >= @week_start AND order_date < DATE_ADD(@week_start, INTERVAL 7 DAY)
  AND status != 'cancelled'
"""

WEEKLY_ORDERS_SQL = f"""
SELECT {week_expr('order_date')} AS wk, COUNT(DISTINCT order_id) AS orders
FROM `${{project}}.${{curated}}.fact_order_item`
WHERE order_date >= DATE_SUB(@week_start, INTERVAL 7 DAY)
  AND order_date < DATE_ADD(@week_start, INTERVAL 7 DAY)
  AND status != 'cancelled'
GROUP BY wk
"""

CATEGORY_SQL = f"""
SELECT category,
       SUM(IF({WEEK_EXPR} = 0, net_sales, 0)) AS net_cur,
       SUM(IF({WEEK_EXPR} = -1, net_sales, 0)) AS net_prev
FROM `${{project}}.${{mart}}.daily_kpi`
WHERE day >= DATE_SUB(@week_start, INTERVAL 7 DAY) AND day < DATE_ADD(@week_start, INTERVAL 7 DAY)
GROUP BY category
"""

CHANNEL_SQL = f"""
WITH sales AS (
  SELECT channel,
         SUM(IF({WEEK_EXPR} = 0, net_sales, 0)) AS net_cur,
         SUM(IF({WEEK_EXPR} = -1, net_sales, 0)) AS net_prev
  FROM `${{project}}.${{mart}}.daily_kpi`
  WHERE day >= DATE_SUB(@week_start, INTERVAL 7 DAY) AND day < DATE_ADD(@week_start, INTERVAL 7 DAY)
  GROUP BY channel
), spend AS (
  SELECT channel,
         SUM(IF({WEEK_EXPR} = 0, spend_usd, 0)) AS spend_cur,
         SUM(IF({WEEK_EXPR} = -1, spend_usd, 0)) AS spend_prev,
         COUNT(DISTINCT IF({WEEK_EXPR} = 0, day, NULL)) AS spend_days_cur
  FROM `${{project}}.${{mart}}.daily_spend`
  WHERE day >= DATE_SUB(@week_start, INTERVAL 7 DAY) AND day < DATE_ADD(@week_start, INTERVAL 7 DAY)
  GROUP BY channel
)
SELECT channel, IFNULL(net_cur, 0) AS net_cur, IFNULL(net_prev, 0) AS net_prev,
       IFNULL(spend_cur, 0) AS spend_cur, IFNULL(spend_prev, 0) AS spend_prev,
       IFNULL(spend_days_cur, 0) AS spend_days_cur
FROM sales FULL OUTER JOIN spend USING (channel)
"""


def _hash(sql: str, params: dict) -> str:
    return hashlib.sha256((sql + json.dumps(params, default=str, sort_keys=True)).encode()).hexdigest()[:16]


def fetch_weekly_inputs(wh, week_start: dt.date) -> WeeklyInputs:
    from .quality import latest_status

    params = {"week_start": week_start}
    hashes = {}

    def run(name, sql):
        hashes[name] = _hash(sql, params)
        return wh.query(sql, params)

    weeks = {r["wk"]: r for r in run("weekly_totals", TOTALS_SQL)}
    orders = {r["wk"]: r["orders"] for r in run("weekly_orders", WEEKLY_ORDERS_SQL)}
    customers = run("weekly_customers", CUSTOMERS_SQL)[0]["customers"]

    empty = {"orders": 0, "gross_sales": 0, "settled_refunds": 0, "net_sales": 0, "days_with_orders": 0}
    cur = dict(weeks.get(0, empty))
    prev = dict(weeks.get(-1, empty))
    cur["orders"], prev["orders"] = orders.get(0, 0), orders.get(-1, 0)
    cur["customers"] = customers

    trailing = [weeks[w]["net_sales"] for w in (-5, -4, -3, -2) if w in weeks]
    status, notes = latest_status(wh)

    return WeeklyInputs(
        week_start=week_start,
        current=cur,
        prior=prev,
        trailing_net=trailing,
        categories=run("category_breakdown", CATEGORY_SQL),
        channels=run("channel_breakdown", CHANNEL_SQL),
        days_cur=cur.get("days_with_orders", 0),
        days_prev=prev.get("days_with_orders", 0),
        quality_status=status,
        quality_notes=notes,
        query_hashes=hashes,
    )
