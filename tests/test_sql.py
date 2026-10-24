import re
from types import SimpleNamespace

import pytest

from insights.config import Settings
from insights.pipeline import STEPS
from insights.warehouse import SQL_DIR, Warehouse, render_sql

DML = re.compile(r"^\s*(MERGE|INSERT|UPDATE|DELETE)\b", re.M | re.I)


class FakeJob:
    job_id = "job"
    total_bytes_billed = 0

    def result(self):
        return []


class FakeClient:
    def __init__(self):
        self.sql = []

    def query(self, sql, job_config=None):
        self.sql.append(sql)
        return FakeJob()


def wh(sandbox):
    return Warehouse(Settings(project="p", sandbox=sandbox), client=FakeClient())


@pytest.mark.parametrize("sandbox", [False, True])
def test_every_step_renders(sandbox):
    w = wh(sandbox)
    for step in ["00_ddl.sql"] + STEPS:
        sql = render_sql(w.sql_path(step).read_text(), w.settings)
        assert "${" not in sql and "--#include" not in sql, step


def test_sandbox_steps_have_no_dml():
    w = wh(True)
    for step in ["00_ddl.sql"] + STEPS:
        sql = render_sql(w.sql_path(step).read_text(), w.settings)
        assert not DML.search(sql), f"{step} uses DML: {DML.search(sql).group(0)}"
        assert "PARTITION BY day" not in sql and "PARTITION BY DATE(" not in sql


def test_normal_mode_keeps_merge_and_partitions():
    w = wh(False)
    assert "MERGE" in render_sql(w.sql_path("31_fact_order_item.sql").read_text(), w.settings)
    assert "PARTITION BY day" in render_sql((SQL_DIR / "40_marts.sql").read_text(), w.settings)


def test_include_expanded():
    sql = render_sql((SQL_DIR / "20_synth_refunds.sql").read_text(), Settings(project="p"))
    assert "FARM_FINGERPRINT" in sql


def test_append_sql():
    w = wh(False)
    w.append("mart", "dq_results", "SELECT 1")
    assert w.client.sql[-1] == "INSERT INTO `p.enterprise_ai_insights_mart.dq_results` SELECT 1"

    w = wh(True)
    w.append("mart", "dq_results", "SELECT 1")
    assert w.client.sql[-1].startswith("CREATE OR REPLACE TABLE `p.enterprise_ai_insights_mart.dq_results`")
    assert "UNION ALL SELECT 1" in w.client.sql[-1]


class CheckJob(FakeJob):
    def __init__(self, sql):
        self._sql = sql

    def result(self):
        return [{"failures": 0}] if "AS failures" in self._sql else []


class RecordingClient(FakeClient):
    def query(self, sql, job_config=None):
        self.sql.append(sql)
        return CheckJob(sql)


def test_sandbox_refresh_end_to_end_without_dml():
    import datetime as dt
    from insights.pipeline import refresh

    w = Warehouse(Settings(project="p", sandbox=True), client=RecordingClient())
    out = refresh(w, full=False, today=dt.date(2026, 10, 24))
    assert out["status"] == "REPORTABLE"
    assert out["load_start"] == "2025-10-24"  # forced to the full window
    assert len(out["checks"]) == 16
    for sql in w.client.sql:
        assert not DML.search(sql), sql[:200]


def test_sandbox_partition_strip_keeps_semicolon():
    sql = render_sql((SQL_DIR / "00_ddl.sql").read_text(), Settings(project="p", sandbox=True))
    statements = [s for s in sql.split(";") if s.strip()]
    # every CREATE has to end up in its own statement
    assert all(s.strip().count("CREATE ") == 1 for s in statements)


def test_sandbox_partition_strip_keeps_as():
    sql = render_sql((SQL_DIR / "40_marts.sql").read_text(), Settings(project="p", sandbox=True))
    assert "daily_totals`\n AS\nWITH sales" in sql


def test_sandbox_keeps_window_partition_by():
    s = Settings(project="p", sandbox=True)
    w = Warehouse(s, client=FakeClient())
    for step in ("31_fact_order_item.sql", "32_fact_refund.sql"):
        sql = render_sql(w.sql_path(step).read_text(), s)
        assert "OVER (PARTITION BY" in sql, step
