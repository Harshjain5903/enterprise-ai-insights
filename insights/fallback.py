"""Template report used when the model is down or its output fails validation.

Only restates facts, so it always validates.
"""
from decimal import Decimal

from .evidence import Packet
from .schema import Claim, Insight, Report


def _usd(v: str) -> str:
    return f"${abs(Decimal(v)):,.2f}"


def _pct(v: str) -> str:
    return f"{abs(Decimal(v))}%"


def _dir(v: str) -> str:
    return "up" if Decimal(v) > 0 else "down" if Decimal(v) < 0 else "flat"


def build_fallback(packet: Packet, reason: str) -> Report:
    idx = packet.fact_index()
    insights = []

    def claim(*ids):
        return [Claim(fact_id=i, value=idx[i].value) for i in ids]

    cur = idx.get("F_NET_SALES_CUR")
    pct = idx.get("F_NET_SALES_CHANGE_PCT")
    if cur and pct:
        headline = f"Net sales {_usd(cur.value)}, {_dir(pct.value)} {_pct(pct.value)} on the prior week"
        head_ids = [cur.fact_id, pct.fact_id]
    elif cur:
        headline = f"Net sales {_usd(cur.value)} this week"
        head_ids = [cur.fact_id]
    else:
        headline = "Weekly report: no sales data for this period"
        head_ids = []

    if "F_ORDERS_CUR" in idx and "F_ORDERS_CHANGE_PCT" in idx:
        o, op = idx["F_ORDERS_CUR"], idx["F_ORDERS_CHANGE_PCT"]
        insights.append(Insight(
            statement=f"Orders: {int(o.value):,} ({_dir(op.value)} {_pct(op.value)}).",
            kind="observation", claims=claim("F_ORDERS_CUR", "F_ORDERS_CHANGE_PCT")))
    if "F_AOV_CUR" in idx and "F_AOV_CHANGE_PCT" in idx:
        a, ap = idx["F_AOV_CUR"], idx["F_AOV_CHANGE_PCT"]
        insights.append(Insight(
            statement=f"Average order value: {_usd(a.value)} ({_dir(ap.value)} {_pct(ap.value)}).",
            kind="observation", claims=claim("F_AOV_CUR", "F_AOV_CHANGE_PCT")))
    if "F_REFUNDS_CUR" in idx and "F_REFUND_RATE_CUR" in idx:
        insights.append(Insight(
            statement=f"Settled refunds: {_usd(idx['F_REFUNDS_CUR'].value)}, "
                      f"{_pct(idx['F_REFUND_RATE_CUR'].value)} of gross sales.",
            kind="observation", claims=claim("F_REFUNDS_CUR", "F_REFUND_RATE_CUR")))
    if "F_CAT1_NET_CHANGE" in idx:
        c = idx["F_CAT1_NET_CHANGE"]
        insights.append(Insight(
            statement=f'Largest category move: "{c.segment}", {_dir(c.value)} {_usd(c.value)}.',
            kind="observation", claims=claim("F_CAT1_NET_CHANGE")))

    if not insights:
        insights.append(Insight(statement="No comparable facts were available.", kind="observation",
                                claims=claim(*head_ids) if head_ids else []))

    return Report(
        headline=headline,
        headline_fact_ids=head_ids,
        insights=insights,
        recommended_investigations=[],
        limitations=[f"Narrative unavailable ({reason}); figures shown as computed."] + packet.limitations,
    )
