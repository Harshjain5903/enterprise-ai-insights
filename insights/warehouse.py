import datetime as dt
import logging
from decimal import Decimal
from pathlib import Path
from string import Template

from .config import Settings

log = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def render_sql(text: str, settings: Settings) -> str:
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

    def run_file(self, name: str, params: dict | None = None):
        sql = (SQL_DIR / name).read_text()
        job = self.client.query(render_sql(sql, self.settings), job_config=self._job_config(params))
        job.result()
        log.info("%s ok (job %s, %s bytes billed)", name, job.job_id, job.total_bytes_billed)
        return job
