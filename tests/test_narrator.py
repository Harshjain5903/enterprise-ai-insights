import json
from types import SimpleNamespace

import pytest

from insights.config import Settings
from insights.narrator import GeminiNarrator
from tests.test_evidence import make_inputs
from insights.evidence import build_packet

GOOD = json.dumps({
    "headline": "Net sales were $92,000.00, down 8.0% on the prior week",
    "headline_fact_ids": ["F_NET_SALES_CUR", "F_NET_SALES_CHANGE_PCT"],
    "insights": [{"statement": "Orders fell 3.0%.", "kind": "observation",
                  "claims": [{"fact_id": "F_ORDERS_CHANGE_PCT", "value": "-3.0"}]}],
    "recommended_investigations": [],
    "limitations": [],
})


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"api error {code}")
        self.code = code


class FakeModels:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(contents)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item, model_version="gemini-2.5-flash-test",
                               usage_metadata=SimpleNamespace(prompt_token_count=900, candidates_token_count=200))


def narrator(script):
    client = SimpleNamespace(models=FakeModels(script))
    n = GeminiNarrator(Settings(project="test"), client=client, sleep=lambda s: None)
    return n, client.models


@pytest.fixture
def packet():
    return build_packet(make_inputs())


def test_happy_path(packet):
    n, models = narrator([GOOD])
    out = n.generate(packet)
    assert out.report.headline.startswith("Net sales")
    assert out.attempts == 1 and out.calls == 1
    assert out.input_tokens == 900


def test_retries_transient_then_succeeds(packet):
    n, models = narrator([ApiError(503), ApiError(429), GOOD])
    out = n.generate(packet)
    assert out.report is not None
    assert out.calls == 3


def test_permission_error_not_retried(packet):
    n, models = narrator([ApiError(403), GOOD])
    with pytest.raises(ApiError):
        n.generate(packet)
    assert len(models.calls) == 1


def test_bad_json_gets_one_repair(packet):
    n, models = narrator(["{not json", GOOD])
    out = n.generate(packet)
    assert out.report is not None
    assert out.attempts == 2
    assert "did not match the schema" in models.calls[1]


def test_gives_up_after_two_bad_outputs(packet):
    n, _ = narrator(['{"headline": 1}', "nope"])
    out = n.generate(packet)
    assert out.report is None
    assert len(out.errors) == 2


def test_query_hashes_not_sent(packet):
    packet.query_hashes["weekly_totals"] = "abc123"
    n, models = narrator([GOOD])
    n.generate(packet)
    assert "abc123" not in models.calls[0]


def test_studio_backend_needs_key():
    from insights.narrator import make_client
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        make_client(Settings(project="test", gemini_backend="studio", gemini_api_key=None))
