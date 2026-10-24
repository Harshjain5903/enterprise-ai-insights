"""Checks a generated Report against the packet it was generated from.

Structure is already enforced by pydantic. This is about the content:
every number has to come from a cited fact, ids have to exist, no causal
claims, and directions (up/down) have to match the sign of the fact.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .evidence import Fact, Packet
from .schema import Report

MAX_INSIGHTS = 5
MAX_INVESTIGATIONS = 3

NUMBER_RE = re.compile(r"(?<![\w.])(\$)?(-|−)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(%)?")
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
CAUSAL_RE = re.compile(
    r"\b(caused|causing|because|due to|led to|leading to|resulted in|as a result of|"
    r"thanks to|attributable to|drove|triggered)\b", re.I)
UP_RE = re.compile(r"\b(up|rose|rise|increased?|grew|growth|higher|gain(ed)?)\b", re.I)
DOWN_RE = re.compile(r"\b(down|fell|fall|declined?|decreased?|dropped|drop|lower|shrank)\b", re.I)


@dataclass
class Violation:
    code: str
    where: str
    detail: str

    def __str__(self):
        return f"{self.code} @ {self.where}: {self.detail}"


@dataclass
class Result:
    violations: list[Violation] = field(default_factory=list)
    numbers_checked: int = 0
    numbers_ok: int = 0
    insights: int = 0
    insights_cited: int = 0

    @property
    def ok(self) -> bool:
        return not self.violations

    def add(self, code, where, detail):
        self.violations.append(Violation(code, where, detail))


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", "").replace("−", "-"))
    except (InvalidOperation, AttributeError):
        return None


def extract_numbers(text: str) -> list[tuple[str, Decimal, int, bool]]:
    """(raw, value, decimals, is_pct) for each number in text. Dates are skipped."""
    text = ISO_DATE_RE.sub(" ", text)
    found = []
    for m in NUMBER_RE.finditer(text):
        dollar, sign, whole, frac, pct = m.groups()
        val = _dec(f"{sign or ''}{whole}{frac or ''}")
        if val is None:
            continue
        # small bare integers ("top 3", "2 channels") aren't metric claims
        if not dollar and not pct and not frac and abs(val) <= 10:
            continue
        found.append((m.group(0).strip(), val, len(frac) - 1 if frac else 0, bool(pct)))
    return found


def matches(num: Decimal, decimals: int, is_pct: bool, fact: Fact) -> bool:
    if is_pct and fact.unit != "pct":
        return False
    fv = _dec(fact.value)
    if fv is None:
        return False
    q = Decimal(1).scaleb(-decimals)
    # sign is carried by words ("down 8%"), so compare magnitudes
    return abs(num) == abs(fv).quantize(q, rounding=ROUND_HALF_UP)


def strip_segments(text: str, facts: list[Fact]) -> str:
    """Remove quoted category/channel names. They're source data, so whatever
    is inside them (numbers, instructions) isn't a claim by the writer."""
    for f in facts:
        if f.segment != "all":
            text = text.replace(f'"{f.segment}"', '""')
    return text


def _check_text(text, facts: list[Fact], where, res: Result):
    text = strip_segments(text, facts)
    for raw, val, dec, pct in extract_numbers(text):
        res.numbers_checked += 1
        if any(matches(val, dec, pct, f) for f in facts):
            res.numbers_ok += 1
        else:
            cited = ", ".join(f.fact_id for f in facts) or "none"
            res.add("UNSUPPORTED_NUMBER", where, f"'{raw}' not in cited facts ({cited})")


def _check_direction(text, facts: list[Fact], where, res: Result):
    text = strip_segments(text, facts)
    changes = [_dec(f.value) for f in facts if f.period == "change"]
    changes = [c for c in changes if c is not None and c != 0]
    if not changes:
        return
    says_up, says_down = bool(UP_RE.search(text)), bool(DOWN_RE.search(text))
    if says_up == says_down:  # neither, or both (e.g. "orders down, aov up")
        return
    if says_down and all(c > 0 for c in changes):
        res.add("WRONG_DIRECTION", where, "says down but cited change is positive")
    if says_up and all(c < 0 for c in changes):
        res.add("WRONG_DIRECTION", where, "says up but cited change is negative")


def _resolve(ids, index, where, res) -> list[Fact]:
    out = []
    for fid in ids:
        if fid in index:
            out.append(index[fid])
        else:
            res.add("UNKNOWN_FACT", where, fid)
    return out


def validate(report: Report, packet: Packet) -> Result:
    res = Result()
    index = packet.fact_index()

    if not report.headline.strip():
        res.add("EMPTY", "headline", "headline is empty")
    if not 1 <= len(report.insights) <= MAX_INSIGHTS:
        res.add("COUNT", "insights", f"{len(report.insights)} insights")
    if len(report.recommended_investigations) > MAX_INVESTIGATIONS:
        res.add("COUNT", "recommended_investigations", str(len(report.recommended_investigations)))

    head_facts = _resolve(report.headline_fact_ids, index, "headline", res)
    _check_text(report.headline, head_facts, "headline", res)
    _check_direction(report.headline, head_facts, "headline", res)
    if CAUSAL_RE.search(report.headline):
        res.add("CAUSAL_CLAIM", "headline", CAUSAL_RE.search(report.headline).group(0))

    for i, ins in enumerate(report.insights):
        where = f"insights[{i}]"
        res.insights += 1
        if ins.claims:
            res.insights_cited += 1
        else:
            res.add("NO_CITATION", where, ins.statement[:60])

        facts = []
        for c in ins.claims:
            f = index.get(c.fact_id)
            if f is None:
                res.add("UNKNOWN_FACT", where, c.fact_id)
                continue
            if _dec(c.value) != _dec(f.value):
                res.add("CLAIM_VALUE_MISMATCH", where, f"{c.fact_id}: {c.value} != {f.value}")
            facts.append(f)

        _check_text(ins.statement, facts, where, res)
        _check_direction(ins.statement, facts, where, res)
        m = CAUSAL_RE.search(strip_segments(ins.statement, facts))
        if m:
            res.add("CAUSAL_CLAIM", where, m.group(0))

    for i, inv in enumerate(report.recommended_investigations):
        where = f"recommended_investigations[{i}]"
        facts = _resolve(inv.fact_ids, index, where, res)
        _check_text(inv.action, facts, where, res)

    if packet.quality_status == "WARN" and not report.limitations:
        res.add("MISSING_LIMITATIONS", "limitations", "packet is WARN but no limitations given")

    return res
