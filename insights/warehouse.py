import datetime as dt
import logging
import re
from decimal import Decimal
from pathlib import Path
from string import Template

from .config import Settings

log = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


INCLUDE_RE = re.compile(r"^--#include (\S+)$", re.M)
PARTITION_RE = re.compile(r"^\s*PARTITION BY .*\n", re.M)


def expand_includes(text: str, depth: int = 0) -> str:
    if depth > 3:
        raise ValueError("--#include nested too deep")
    return INCLUDE_RE.sub(lambda m: expand_includes((SQL_DIR / m.group(1)).read_text(), depth + 1).rstrip(), text)


def render_sql(text: str, settings: Settings) -> str:
    text = expand_includes(text)
    if settings.sandbox:
        # sandbox tables get a 60 day partition expiration, which would quietly
        # drop most of the history. tables are small, just don't partition.
        text = PARTITION_RE.sub("", text)
    # substitute() not safe_substitute(): a typo'd placeholder should blow up here,
    # not get sent to BigQuery
    return Template(text).substitute(
        project=settings.project,
        raw=f"{settings.dataset}_raw",
        curated=f"{settings.dataset}_curated",
        mart=f"{settings.dataset}_mart",
        tz=settings.tz,
        bq_location=settings.bq_location,
    )


def _param(name, value):
    from google.cloud import bigquery

    if isinstance(value, bool):
        return bigquery.ScalarQueryParameter(name, "BOOL", value)
    if isinstance(value, int):
        return bigquery.ScalarQueryParameter(name, "INT64", value)
    if isinstance(value, Decimal):
        return bigquery.ScalarQueryParameter(name, "NUMERIC", value)
    if isinstance(value, dt.datetime):
        return bigquery.ScalarQueryParameter(name, "TIMESTAMP", value)
    if isinstance(value, dt.date):
        return bigquery.ScalarQueryParameter(name, "DATE", value)
    return bigquery.ScalarQueryParameter(name, "STRING", str(value))


class Warehouse:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        if client is None:
            from google.cloud import bigquery
            client = bigquery.Client(project=settings.project, location=settings.bq_location)
        self.client = client

    def table(self, layer: str, name: str) -> str:
        return f"`{self.settings.project}.{self.settings.dataset}_{layer}.{name}`"

    def _job_config(self, params: dict | None):
        from google.cloud import bigquery

        return bigquery.QueryJobConfig(
            query_parameters=[_param(k, v) for k, v in (params or {}).items()],
            maximum_bytes_billed=self.settings.max_bytes_billed,
        )

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        job = self.client.query(render_sql(sql, self.settings), job_config=self._job_config(params))
        rows = [dict(r.items()) for r in job.result()]
        log.debug("job %s: %s rows, %s bytes billed", job.job_id, len(rows), job.total_bytes_billed)
        return rows

    def sql_path(self, name: str) -> Path:
        if self.settings.sandbox and (SQL_DIR / "sandbox" / name).exists():
            return SQL_DIR / "sandbox" / name
        return SQL_DIR / name

    def append(self, layer: str, name: str, select_sql: str, params: dict | None = None):
        """Add rows to a table. select_sql must produce the table's columns in order."""
        t = self.table(layer, name)
        if self.settings.sandbox:
            # no INSERT in the sandbox, rewrite the table with the new rows on the end
            sql = f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM {t} UNION ALL {select_sql}"
        else:
            sql = f"INSERT INTO {t} {select_sql}"
        return self.query(sql, params)

    def run_file(self, name: str, params: dict | None = None):
        sql = self.sql_path(name).read_text()
        job = self.client.query(render_sql(sql, self.settings), job_config=self._job_config(params))
        job.result()
        log.info("%s ok (job %s, %s bytes billed)", name, job.job_id, job.total_bytes_billed)
        return job
