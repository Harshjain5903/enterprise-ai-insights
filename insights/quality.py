"""Data quality checks. Each check is a query returning one INT64 `failures` column.

BLOCK checks stop the batch from being reportable. WARN checks get surfaced as
limitations in the report but don't stop it.
"""
import uuid
from dataclasses import dataclass

FOI = "`${project}.${curated}.fact_order_item`"
FR = "`${project}.${curated}.fact_refund`"
SPEND = "`${project}.${raw}.marketing_spend`"
KPI = "`${project}.${mart}.daily_kpi`"
TOT = "`${project}.${mart}.daily_totals`"


@dataclass(frozen=True)
class Check:
    name: str
    severity: str  # BLOCK | WARN
    sql: str


CHECKS = [
    Check("order_item_unique_key", "BLOCK", f"""
        SELECT COUNT(*) AS failures FROM (
          SELECT order_item_id FROM {FOI} GROUP BY 1 HAVING COUNT(*) > 1)"""),
    Check("order_item_required_fields", "BLOCK", f"""
        SELECT COUNTIF(order_id IS NULL OR order_ts IS NULL OR sale_price IS NULL
                       OR product_id IS NULL) AS failures FROM {FOI}"""),
    Check("order_item_status_allowed", "BLOCK", f"""
        SELECT COUNTIF(status NOT IN ('processing','shipped','complete','cancelled','returned'))
          AS failures FROM {FOI}"""),
    Check("order_item_price_non_negative", "BLOCK", f"""
        SELECT COUNTIF(sale_price < 0) AS failures FROM {FOI}"""),
    Check("order_item_unknown_category", "WARN", f"""
        SELECT COUNTIF(category = 'Unknown') AS failures FROM {FOI}"""),
    Check("refund_unique_key", "BLOCK", f"""
        SELECT COUNT(*) AS failures FROM (
          SELECT refund_id FROM {FR} GROUP BY 1 HAVING COUNT(*) > 1)"""),
    Check("refund_amount_positive", "BLOCK", f"""
        SELECT COUNTIF(refund_amount <= 0) AS failures FROM {FR}"""),
    Check("refund_status_allowed", "BLOCK", f"""
        SELECT COUNTIF(refund_status NOT IN ('settled','pending','rejected')) AS failures FROM {FR}"""),
    Check("refund_currency_usd", "BLOCK", f"""
        SELECT COUNTIF(currency != 'USD') AS failures FROM {FR}"""),
    Check("refund_orphaned", "WARN", f"""
        SELECT COUNTIF(order_id IS NULL) AS failures FROM {FR}"""),
    Check("refund_exceeds_sale", "BLOCK", f"""
        SELECT COUNT(*) AS failures FROM (
          SELECT r.order_item_id
          FROM {FR} r JOIN {FOI} f USING (order_item_id)
          WHERE r.refund_status = 'settled'
          GROUP BY r.order_item_id, f.sale_price
          HAVING SUM(r.refund_amount) > f.sale_price)"""),
    Check("spend_unique_key", "BLOCK", f"""
        SELECT COUNT(*) AS failures FROM (
          SELECT spend_date, campaign_id FROM {SPEND} GROUP BY 1, 2 HAVING COUNT(*) > 1)"""),
    Check("spend_non_negative_usd", "BLOCK", f"""
        SELECT COUNTIF(spend_usd < 0 OR currency != 'USD') AS failures FROM {SPEND}"""),
    Check("kpi_reconciles_to_fact", "BLOCK", f"""
        SELECT IF(ABS(
          (SELECT IFNULL(SUM(gross_sales), 0) FROM {KPI})
          - (SELECT IFNULL(SUM(sale_price), 0) FROM {FOI} WHERE status != 'cancelled')) > 0.01, 1, 0)
          AS failures"""),
    Check("totals_reconcile_to_kpi", "BLOCK", f"""
        SELECT COUNT(*) AS failures FROM (
          SELECT t.day
          FROM {TOT} t
          JOIN (SELECT day, SUM(net_sales) AS net FROM {KPI} GROUP BY day) k USING (day)
          WHERE ABS(t.net_sales - k.net) > 0.01)"""),
    Check("sales_freshness", "WARN", f"""
        SELECT IF(IFNULL(MAX(order_date), DATE '1970-01-01')
                  < DATE_SUB(CURRENT_DATE('${{tz}}'), INTERVAL 2 DAY), 1, 0) AS failures
        FROM {FOI}"""),
]


@dataclass
class CheckResult:
    name: str
    severity: str
    failures: int

    @property
    def failed(self) -> bool:
        return self.failures > 0

    def as_dict(self):
        return {"name": self.name, "severity": self.severity, "failures": self.failures}


def run_checks(wh, run_id: str | None = None) -> list[CheckResult]:
    run_id = run_id or f"adhoc-{uuid.uuid4().hex[:8]}"
    results = []
    for check in CHECKS:
        rows = wh.query(check.sql)
        results.append(CheckResult(check.name, check.severity, int(rows[0]["failures"])))

    # plain DML rather than streaming inserts: the table may have been created
    # seconds ago in 40_marts.sql and streaming into fresh tables is flaky
    values = ",\n".join(
        f"(@run_id, '{r.name}', '{r.severity}', {r.failures}, CURRENT_TIMESTAMP())" for r in results
    )
    wh.query(
        "INSERT INTO `${project}.${mart}.dq_results` "
        f"(run_id, check_name, severity, failures, checked_at) VALUES\n{values}",
        {"run_id": run_id},
    )
    return results


def latest_status(wh) -> tuple[str, list[str]]:
    """Overall PASS/WARN/BLOCK from the most recent dq run, plus the failing check names."""
    rows = wh.query(f"""
        SELECT check_name, severity, failures
        FROM `${{project}}.${{mart}}.dq_results`
        WHERE run_id = (SELECT run_id FROM `${{project}}.${{mart}}.dq_results`
                        ORDER BY checked_at DESC LIMIT 1)""")
    if not rows:
        return "BLOCK", ["no data quality run found"]
    failing = [r for r in rows if r["failures"] > 0]
    if any(r["severity"] == "BLOCK" for r in failing):
        status = "BLOCK"
    elif failing:
        status = "WARN"
    else:
        status = "PASS"
    return status, [f"{r['check_name']} ({r['failures']})" for r in failing]
