"""Run the golden cases through the narrator + validator and score them.

    python -m evals.run_evals                 # gemini via vertex (needs GOOGLE_CLOUD_PROJECT)
    python -m evals.run_evals --narrator fallback   # template only, checks the harness itself

Scores (each over its own denominator):
  schema_valid      cases where the model returned JSON matching the schema
  numeric_correct   numbers in the text that match a cited fact / numbers checked
  citation_complete cases where every insight cites a fact and the must_cite ids appear
  forbidden_hits    cases containing a forbidden phrase (injection / causal wording)
"""
import argparse
import datetime as dt
import json
import statistics
import time
from decimal import Decimal
from pathlib import Path

from insights.evidence import WeeklyInputs, build_packet
from insights.fallback import build_fallback
from insights.narrator import Narration
from insights.validator import validate

HERE = Path(__file__).parent


def load_cases(path=HERE / "cases.jsonl"):
    for line in path.read_text().splitlines():
        if line.strip():
            yield json.loads(line)


def to_inputs(raw: dict) -> WeeklyInputs:
    d = dict(raw)
    d["week_start"] = dt.date.fromisoformat(d["week_start"])
    d["trailing_net"] = [Decimal(x) for x in d["trailing_net"]]
    return WeeklyInputs(**d)


class FallbackNarrator:
    prompt_hash = "fallback"

    def generate(self, packet):
        return Narration(report=build_fallback(packet, "eval"), attempts=1, calls=1, model_version="fallback")


def all_text(report) -> str:
    parts = [report.headline] + [i.statement for i in report.insights]
    parts += [f"{i.action} {i.rationale}" for i in report.recommended_investigations]
    return " ".join(parts).lower()


def score_case(case, narrator):
    packet = build_packet(to_inputs(case["inputs"]))
    exp = case["expect"]
    row = {"case_id": case["case_id"], "kind": case["kind"], "quality_status": packet.quality_status}

    t = time.monotonic()
    try:
        n = narrator.generate(packet)
    except Exception as e:  # noqa: BLE001
        row.update(error=f"{type(e).__name__}: {e}"[:200], schema_valid=False)
        return row
    row["latency_ms"] = int((time.monotonic() - t) * 1000)
    row["attempts"] = n.attempts
    row["schema_valid"] = n.report is not None
    if n.report is None:
        row["errors"] = n.errors
        return row

    rep = n.report
    res = validate(rep, packet)
    cited = set(rep.headline_fact_ids) | {c.fact_id for i in rep.insights for c in i.claims}
    must = [m for m in exp["must_cite"] if m in packet.fact_index()]
    text = all_text(rep)

    row.update(
        validator_ok=res.ok,
        violations=[str(v) for v in res.violations],
        numbers_checked=res.numbers_checked,
        numbers_ok=res.numbers_ok,
        citation_complete=res.insights == res.insights_cited and all(m in cited for m in must),
        missing_cites=[m for m in must if m not in cited],
        forbidden=[w for w in exp["forbidden"] if w in text],
        limitation_ok=(not exp["expect_limitation"]) or bool(rep.limitations),
        report=rep.model_dump(),
    )
    return row


def summarize(rows):
    n = len(rows)
    valid = [r for r in rows if r.get("schema_valid")]
    checked = sum(r.get("numbers_checked", 0) for r in valid)
    ok = sum(r.get("numbers_ok", 0) for r in valid)
    lat = [r["latency_ms"] for r in rows if "latency_ms" in r]
    return {
        "cases": n,
        "schema_valid": f"{len(valid)}/{n}",
        "validator_pass": f"{sum(r.get('validator_ok', False) for r in valid)}/{n}",
        "numeric_correct": f"{ok}/{checked}",
        "citation_complete": f"{sum(r.get('citation_complete', False) for r in valid)}/{n}",
        "forbidden_hits": sum(bool(r.get("forbidden")) for r in valid),
        "limitation_ok": f"{sum(r.get('limitation_ok', False) for r in valid)}/{n}",
        "latency_p50_ms": int(statistics.median(lat)) if lat else None,
        "latency_p95_ms": int(statistics.quantiles(lat, n=20)[-1]) if len(lat) >= 20 else None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--narrator", choices=["gemini", "fallback"], default="gemini")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--kind", help="only run cases of this kind")
    args = ap.parse_args(argv)

    if args.narrator == "gemini":
        from insights.config import Settings
        from insights.narrator import GeminiNarrator
        narrator = GeminiNarrator(Settings.from_env())
    else:
        narrator = FallbackNarrator()

    cases = [c for c in load_cases() if not args.kind or c["kind"] == args.kind][:args.limit]
    rows = []
    for c in cases:
        row = score_case(c, narrator)
        flag = "ok " if row.get("validator_ok") else "BAD"
        print(f"{flag} {row['case_id']:24} {'; '.join(row.get('violations', []))[:100]}")
        rows.append(row)

    summary = summarize(rows)
    out = HERE / "results" / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{args.narrator}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "rows.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    (out / "summary.json").write_text(json.dumps(
        {"narrator": args.narrator, "prompt_hash": narrator.prompt_hash, **summary}, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"results in {out}")


if __name__ == "__main__":
    main()
