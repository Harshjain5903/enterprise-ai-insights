import datetime as dt
import logging
import os
import time
import uuid
from zoneinfo import ZoneInfo

from . import quality
from .warehouse import Warehouse

log = logging.getLogger(__name__)

STEPS = [
    "10_load_raw.sql",
    "20_synth_refunds.sql",
    "21_synth_spend.sql",
    "30_curated.sql",
    "40_marts.sql",
]


def load_window(today: dt.date, full: bool, lookback_days: int, history_days: int):
    """[start, end) in reporting-local dates. end is today so the partial day is excluded."""
    days = history_days if full else lookback_days
    return today - dt.timedelta(days=days), today


def refresh(wh: Warehouse, full: bool = False, lookback_days: int = 7, history_days: int = 365,
            today: dt.date | None = None) -> dict:
    tz = ZoneInfo(wh.settings.tz)
    today = today or dt.datetime.now(tz).date()
    start, end = load_window(today, full, lookback_days, history_days)
    batch_id = f"{today:%Y%m%d}-{uuid.uuid4().hex[:8]}"
    salt = os.environ.get("CUSTOMER_SALT", "local-dev-salt")
    params = {"load_start": start, "load_end": end, "batch_id": batch_id, "salt": salt}

    log.info("batch %s: %s -> %s (%s)", batch_id, start, end, "full" if full else "incremental")
    t0 = time.monotonic()
    wh.run_file("00_ddl.sql")
    _record_batch(wh, batch_id, "full" if full else "incremental", start, end, "RUNNING")

    try:
        for step in STEPS:
            # only send the params a script actually references
            wh.run_file(step, {k: v for k, v in params.items() if _uses(step, k)})
        results = quality.run_checks(wh, run_id=batch_id)
    except Exception as e:
        _finish_batch(wh, batch_id, "FAILED", str(e)[:1000])
        raise

    blocking = [r for r in results if r.failed and r.severity == "BLOCK"]
    status = "QUARANTINED" if blocking else "REPORTABLE"
    _finish_batch(wh, batch_id, status, None)
    elapsed = time.monotonic() - t0
    log.info("batch %s finished %s in %.1fs", batch_id, status, elapsed)
    return {"batch_id": batch_id, "status": status, "seconds": round(elapsed, 1),
            "load_start": str(start), "load_end": str(end),
            "checks": [r.as_dict() for r in results]}


def _uses(step: str, param: str) -> bool:
    from .warehouse import SQL_DIR
    return f"@{param}" in (SQL_DIR / step).read_text()


def _record_batch(wh, batch_id, mode, start, end, status):
    wh.query(
        f"INSERT INTO {wh.table('raw', 'load_batches')} "
        "(batch_id, mode, load_start, load_end, started_at, status) "
        "VALUES (@batch_id, @mode, @start, @end, CURRENT_TIMESTAMP(), @status)",
        {"batch_id": batch_id, "mode": mode, "start": start, "end": end, "status": status},
    )


def _finish_batch(wh, batch_id, status, error):
    wh.query(
        f"UPDATE {wh.table('raw', 'load_batches')} "
        "SET status = @status, error = @error, finished_at = CURRENT_TIMESTAMP() "
        "WHERE batch_id = @batch_id",
        {"batch_id": batch_id, "status": status, "error": error or ""},
    )
