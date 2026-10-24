import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from .config import Settings


def main(argv=None):
    p = argparse.ArgumentParser(prog="insights")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("refresh", help="load TheLook + rebuild curated/marts")
    r.add_argument("--full", action="store_true", help="reload the whole history window")
    r.add_argument("--lookback", type=int, default=7)
    r.add_argument("--history", type=int, default=365)

    sub.add_parser("dq", help="run data quality checks only")

    rp = sub.add_parser("report", help="generate the weekly report")
    rp.add_argument("--week", type=dt.date.fromisoformat,
                    help="monday of the report week (default: last complete week)")
    rp.add_argument("--out", type=Path, default=Path("out"))
    rp.add_argument("--no-llm", action="store_true", help="skip gemini, template report only")
    rp.add_argument("--no-log", action="store_true", help="don't write to report_snapshot")

    v = sub.add_parser("validate", help="re-run the validator on a saved report (no gcp needed)")
    v.add_argument("report_dir", type=Path, nargs="?", help="out/<report_id>, default: latest")
    v.add_argument("--tamper", action="store_true",
                   help="change the first number in the headline first, to show it getting caught")

    args = p.parse_args(argv)
    if args.cmd == "validate":
        return _validate_saved(args)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # google libs are chatty at debug
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    settings = Settings.from_env()
    from .warehouse import Warehouse
    wh = Warehouse(settings)

    if args.cmd == "refresh":
        from .pipeline import refresh
        out = refresh(wh, full=args.full, lookback_days=args.lookback, history_days=args.history)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out["status"] == "REPORTABLE" else 2

    if args.cmd == "dq":
        from .quality import run_checks
        results = run_checks(wh)
        for res in results:
            flag = "FAIL" if res.failed else "ok"
            print(f"{flag:5} {res.severity:5} {res.name:40} {res.failures}")
        return 2 if any(r.failed and r.severity == "BLOCK" for r in results) else 0

    if args.cmd == "report":
        from zoneinfo import ZoneInfo
        from .report import last_complete_week, run_weekly

        week = args.week or last_complete_week(dt.datetime.now(ZoneInfo(settings.tz)).date())
        if week.weekday() != 0:
            p.error(f"--week must be a Monday, got {week} ({week:%A})")
        if args.no_llm:
            narrator = _NoLLM()
        else:
            from .narrator import GeminiNarrator
            narrator = GeminiNarrator(settings)
        res = run_weekly(wh, narrator, week, args.out, log_snapshot=not args.no_log)
        print(f"{res.status}: {res.report.headline}")
        for v in res.violations:
            print(f"  - {v}")
        print(f"written to {args.out / res.packet.report_id}")
        return 0 if res.status in ("approved", "fallback") else 2


def _validate_saved(args):
    import re
    from .evidence import Packet
    from .schema import Report
    from .validator import validate

    d = args.report_dir or max(Path("out").glob("*/report.json"), key=lambda f: f.stat().st_mtime).parent
    packet = Packet.model_validate_json((d / "packet.json").read_text())
    report = Report.model_validate_json((d / "report.json").read_text())
    print(f"report: {d}")
    if args.tamper:
        m = re.search(r"\d+(?:\.\d+)?", report.headline)
        if m:
            fake = str(round(float(m.group(0)) * 1.5 + 1, 1))
            report.headline = report.headline[:m.start()] + fake + report.headline[m.end():]
            print(f"tampered headline: {m.group(0)} -> {fake}")
    print(f"headline: {report.headline}")
    res = validate(report, packet)
    print(f"numbers checked: {res.numbers_checked}, matched facts: {res.numbers_ok}")
    if res.ok:
        print("PASS: every number traces back to a fact in the packet")
        return 0
    print("REJECTED:")
    for viol in res.violations:
        print(f"  - {viol}")
    return 1


class _NoLLM:
    prompt_hash = None

    def generate(self, packet):
        raise RuntimeError("llm disabled (--no-llm)")


if __name__ == "__main__":
    sys.exit(main())
