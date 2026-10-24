import html

from .evidence import Packet
from .schema import Report


def _cite(ids) -> str:
    return " ".join(f"[{i}]" for i in ids)


def to_markdown(report: Report, packet: Packet, status: str) -> str:
    p = packet
    lines = [
        f"# {report.headline}",
        "",
        f"Week {p.period.start} to {p.period.end_exclusive} (exclusive), compared with "
        f"{p.comparison.start} to {p.comparison.end_exclusive}. Times in {p.time_zone}.",
        f"Status: **{status}**, data quality: **{p.quality_status}**",
        "",
        "## Findings",
        "",
    ]
    for ins in report.insights:
        tag = " _(association)_" if ins.kind == "association" else ""
        lines.append(f"- {ins.statement}{tag} {_cite(c.fact_id for c in ins.claims)}")
    if report.recommended_investigations:
        lines += ["", "## Worth checking", ""]
        for inv in report.recommended_investigations:
            lines.append(f"- **{inv.action}**: {inv.rationale} {_cite(inv.fact_ids)}")
    if report.limitations:
        lines += ["", "## Limitations", ""]
        lines += [f"- {l}" for l in report.limitations]
    lines += ["", "## Facts", "", "| id | metric | segment | period | value | unit |",
              "|---|---|---|---|---|---|"]
    for f in p.facts:
        seg = f.segment.replace("|", "\\|")
        lines.append(f"| {f.fact_id} | {f.metric} | {seg} | {f.period} | {f.value} | {f.unit} |")
    return "\n".join(lines) + "\n"


def to_html(report: Report, packet: Packet, status: str) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(f.fact_id)}</td><td>{e(f.metric)}</td><td>{e(f.segment)}</td>"
        f"<td>{e(f.period)}</td><td class=n>{e(f.value)}</td><td>{e(f.unit)}</td></tr>"
        for f in packet.facts)
    items = "".join(
        f"<li>{e(i.statement)} <small>{e(_cite(c.fact_id for c in i.claims))}</small></li>"
        for i in report.insights)
    invs = "".join(
        f"<li><b>{e(i.action)}</b>: {e(i.rationale)}</li>" for i in report.recommended_investigations)
    lims = "".join(f"<li>{e(l)}</li>" for l in report.limitations)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{e(report.headline)}</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<style>
body{{font:15px/1.5 -apple-system,Segoe UI,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border-bottom:1px solid #ddd;padding:4px 6px;text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}small{{color:#777}}.meta{{color:#555}}
</style></head><body>
<h1>{e(report.headline)}</h1>
<p class=meta>{e(str(packet.period.start))} &ndash; {e(str(packet.period.end_exclusive))} (exclusive)
vs {e(str(packet.comparison.start))} &ndash; {e(str(packet.comparison.end_exclusive))} &middot;
status {e(status)} &middot; data quality {e(packet.quality_status)}</p>
<h2>Findings</h2><ul>{items}</ul>
{"<h2>Worth checking</h2><ul>" + invs + "</ul>" if invs else ""}
{"<h2>Limitations</h2><ul>" + lims + "</ul>" if lims else ""}
<h2>Facts</h2><table><tr><th>id</th><th>metric</th><th>segment</th><th>period</th><th>value</th><th>unit</th></tr>{rows}</table>
</body></html>
"""
