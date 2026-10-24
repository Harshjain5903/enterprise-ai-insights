import datetime as dt
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .evidence import Packet, fetch_weekly_inputs, build_packet, trim_to_budget
from .fallback import build_fallback
from .render import to_html, to_markdown
from .schema import Report
from .validator import validate

log = logging.getLogger(__name__)


@dataclass
class ReportResult:
    status: str  # approved | fallback | blocked
    report: Report
    packet: Packet
    violations: list[str]
    meta: dict


def last_complete_week(today: dt.date) -> dt.date:
    """Monday of the most recent full Mon-Sun week before `today`."""
    this_monday = today - dt.timedelta(days=today.weekday())
    return this_monday - dt.timedelta(days=7)


def generate(packet: Packet, narrator) -> ReportResult:
    timings = {}
    meta = {"prompt_hash": getattr(narrator, "prompt_hash", None),
            "evidence_hash": packet.evidence_hash(), "timings_ms": timings}

    if packet.quality_status == "BLOCK":
        rep = build_fallback(packet, "data quality checks failed")
        return ReportResult("blocked", rep, packet, [], meta)

    t = time.monotonic()
    try:
        narration = narrator.generate(packet)
    except Exception as e:  # noqa: BLE001
        log.error("narration failed: %s", e)
        timings["generate"] = int((time.monotonic() - t) * 1000)
        meta["error"] = f"{type(e).__name__}: {e}"[:300]
        return ReportResult("fallback", build_fallback(packet, "model unavailable"), packet, [], meta)
    timings["generate"] = int((time.monotonic() - t) * 1000)
    meta.update(model=narration.model_version, attempts=narration.attempts, calls=narration.calls,
                input_tokens=narration.input_tokens, output_tokens=narration.output_tokens)

    if narration.report is None:
        return ReportResult("fallback", build_fallback(packet, "invalid model output"), packet,
                            narration.errors, meta)

    t = time.monotonic()
    res = validate(narration.report, packet)
    timings["validate"] = int((time.monotonic() - t) * 1000)
    meta["numbers_checked"], meta["numbers_ok"] = res.numbers_checked, res.numbers_ok
    if not res.ok:
        # fail closed: keep the model draft for review but publish the template version
        meta["rejected_draft"] = narration.report.model_dump()
        return ReportResult("fallback", build_fallback(packet, "failed validation"), packet,
                            [str(v) for v in res.violations], meta)
    return ReportResult("approved", narration.report, packet, [], meta)


def run_weekly(wh, narrator, week_start: dt.date, out_dir: Path, log_snapshot: bool = True) -> ReportResult:
    t0 = time.monotonic()
    t = time.monotonic()
    inputs = fetch_weekly_inputs(wh, week_start)
    fetch_ms = int((time.monotonic() - t) * 1000)

    packet = build_packet(inputs, tz=wh.settings.tz)
    packet = trim_to_budget(packet, wh.settings.max_input_tokens)
    result = generate(packet, narrator)
    result.meta["timings_ms"]["fetch"] = fetch_ms
    result.meta["timings_ms"]["total"] = int((time.monotonic() - t0) * 1000)

    write_outputs(result, out_dir)
    if log_snapshot:
        _log_snapshot(wh, result)
    return result


def write_outputs(result: ReportResult, out_dir: Path) -> Path:
    d = out_dir / result.packet.report_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "packet.json").write_text(result.packet.model_dump_json(indent=2))
    (d / "report.json").write_text(result.report.model_dump_json(indent=2))
    (d / "report.md").write_text(to_markdown(result.report, result.packet, result.status))
    (d / "report.html").write_text(to_html(result.report, result.packet, result.status))
    (d / "meta.json").write_text(json.dumps(
        {"status": result.status, "violations": result.violations, **result.meta}, indent=2, default=str))
    return d


def _log_snapshot(wh, result: ReportResult):
    wh.query(
        "INSERT INTO `${project}.${mart}.report_snapshot` "
        "(report_id, week_start, status, model, prompt_hash, evidence_hash, quality_status, "
        " violations, latency_ms, created_at) VALUES "
        "(@report_id, @week_start, @status, @model, @prompt_hash, @evidence_hash, @quality, "
        " IF(@violations = '', [], SPLIT(@violations, '\\n')), @latency, CURRENT_TIMESTAMP())",
        {
            "report_id": result.packet.report_id,
            "week_start": result.packet.period.start,
            "status": result.status,
            "model": result.meta.get("model") or "",
            "prompt_hash": result.meta.get("prompt_hash") or "",
            "evidence_hash": result.meta["evidence_hash"],
            "quality": result.packet.quality_status,
            "violations": "\n".join(result.violations),
            "latency": result.meta["timings_ms"]["total"],
        },
    )
