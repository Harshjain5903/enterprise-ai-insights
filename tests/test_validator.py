import pytest

from insights.evidence import build_packet
from insights.schema import Report
from insights.validator import extract_numbers, validate
from tests.test_evidence import make_inputs


@pytest.fixture
def packet():
    return build_packet(make_inputs())


def report(**kw):
    base = {
        "headline": "Net sales were $92,000.00, down 8.0% week over week",
        "headline_fact_ids": ["F_NET_SALES_CUR", "F_NET_SALES_CHANGE_PCT"],
        "insights": [
            {"statement": "Orders were down 3.0% to 970.", "kind": "observation",
             "claims": [{"fact_id": "F_ORDERS_CHANGE_PCT", "value": "-3.0"},
                        {"fact_id": "F_ORDERS_CUR", "value": "970"}]},
        ],
        "recommended_investigations": [
            {"action": "Look at Jeans returns", "rationale": "largest category drop",
             "fact_ids": ["F_CAT1_NET_CHANGE"]}],
        "limitations": [],
    }
    base.update(kw)
    return Report.model_validate(base)


def codes(res):
    return [v.code for v in res.violations]


def test_clean_report_passes(packet):
    res = validate(report(), packet)
    assert res.ok, res.violations
    assert res.numbers_checked == res.numbers_ok == 4


def test_rounded_display_ok(packet):
    r = report(headline="Net sales were $92,000, down 8% week over week")
    assert validate(r, packet).ok


def test_changed_number_rejected(packet):
    r = report(headline="Net sales were $92,000.00, down 12.0% week over week")
    assert "UNSUPPORTED_NUMBER" in codes(validate(r, packet))


def test_number_from_uncited_fact_rejected(packet):
    # 970 exists in the packet but the headline doesn't cite F_ORDERS_CUR
    r = report(headline="970 orders, net sales $92,000.00")
    assert "UNSUPPORTED_NUMBER" in codes(validate(r, packet))


def test_unknown_fact_id(packet):
    r = report(headline_fact_ids=["F_NET_SALES_CUR", "F_MADE_UP"])
    assert "UNKNOWN_FACT" in codes(validate(r, packet))


def test_claim_value_must_match_fact(packet):
    r = report(insights=[{"statement": "Orders were down.", "kind": "observation",
                          "claims": [{"fact_id": "F_ORDERS_CHANGE_PCT", "value": "-4.0"}]}])
    assert "CLAIM_VALUE_MISMATCH" in codes(validate(r, packet))


def test_no_citation(packet):
    r = report(insights=[{"statement": "Things were quieter.", "kind": "observation", "claims": []}])
    assert "NO_CITATION" in codes(validate(r, packet))


def test_causal_language(packet):
    r = report(insights=[{"statement": "Orders fell 3.0% because of lower search spend.",
                          "kind": "observation",
                          "claims": [{"fact_id": "F_ORDERS_CHANGE_PCT", "value": "-3.0"}]}])
    assert "CAUSAL_CLAIM" in codes(validate(r, packet))


def test_wrong_direction(packet):
    r = report(headline="Net sales rose 8.0%", headline_fact_ids=["F_NET_SALES_CHANGE_PCT"])
    assert "WRONG_DIRECTION" in codes(validate(r, packet))


def test_warn_needs_limitations():
    p = build_packet(make_inputs(days_cur=5))
    assert "MISSING_LIMITATIONS" in codes(validate(report(), p))


def test_extract_numbers_skips_dates_and_small_ints():
    nums = extract_numbers("Top 3 categories on 2026-09-28: $1,250.50 and 4.5% and 1200 orders")
    assert [n[1] for n in nums] == [1250.50, 4.5, 1200]
