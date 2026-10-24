import argparse
import json
import logging
import sys

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

    args = p.parse_args(argv)
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


if __name__ == "__main__":
    sys.exit(main())
