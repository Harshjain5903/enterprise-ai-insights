import datetime as dt
import json

import pytest

from insights.evidence import build_packet
from insights.fallback import build_fallback
from insights.narrator import Narration
from insights.render import to_html, to_markdown
from insights.report import generate, last_complete_week, write_outputs
from insights.schema import Report
from insights.validator import validate
from tests.test_evidence import make_inputs
from tests.test_validator import report as good_report


class StubNarrator:
    prompt_hash = "test"

    def __init__(self, report=None, exc=None):
        self._report, self._exc = report, exc

    def generate(self, packet):
        if self._exc:
            raise self._exc
        return Narration(report=self._report, attempts=1, calls=1, model_version="stub")


@pytest.fixture
def packet():
    return build_packet(make_inputs())


def test_last_complete_week():
    assert last_complete_week(dt.date(2026, 10, 7)) == dt.date(2026, 9, 28)  # wednesday
    assert last_complete_week(dt.date(2026, 10, 5)) == dt.date(2026, 9, 28)  # monday


def test_fallback_always_validates(packet):
    rep = build_fallback(packet, "test")
    assert validate(rep, packet).ok, validate(rep, packet).violations


def test_fallback_on_empty_packet():
    p = build_packet(make_inputs(current={}, prior={}, categories=[], channels=[], trailing_net=[]))
    rep = build_fallback(p, "test")
    assert rep.headline


def test_approved(packet):
    res = generate(packet, StubNarrator(good_report()))
    assert res.status == "approved"


def test_invalid_draft_falls_back(packet):
    bad = good_report(headline="Net sales collapsed 40.0%")
    res = generate(packet, StubNarrator(bad))
    assert res.status == "fallback"
    assert res.violations
    assert res.meta["rejected_draft"]["headline"] == "Net sales collapsed 40.0%"


def test_model_down_falls_back(packet):
    res = generate(packet, StubNarrator(exc=TimeoutError("deadline")))
    assert res.status == "fallback"
    assert "Narrative unavailable" in res.report.limitations[0]


def test_blocked_packet_skips_model(packet):
    blocked = packet.model_copy(update={"quality_status": "BLOCK"})
    res = generate(blocked, StubNarrator(exc=AssertionError("should not be called")))
    assert res.status == "blocked"


def test_html_escapes_source_text():
    p = build_packet(make_inputs(categories=[
        {"category": "<script>alert(1)</script>", "net_cur": 0, "net_prev": 5000}]))
    out = to_html(build_fallback(p, "x"), p, "fallback")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_escapes_pipes():
    p = build_packet(make_inputs(categories=[{"category": "A|B", "net_cur": 0, "net_prev": 1}]))
    assert "A\\|B" in to_markdown(build_fallback(p, "x"), p, "fallback")


def test_write_outputs(tmp_path, packet):
    res = generate(packet, StubNarrator(good_report()))
    d = write_outputs(res, tmp_path)
    assert {f.name for f in d.iterdir()} == {"packet.json", "report.json", "report.md", "report.html", "meta.json"}
    assert json.loads((d / "meta.json").read_text())["status"] == "approved"
    Report.model_validate_json((d / "report.json").read_text())
