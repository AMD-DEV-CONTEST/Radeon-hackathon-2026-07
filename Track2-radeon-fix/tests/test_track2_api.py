from types import SimpleNamespace

from swe_experiments.api import (
    APIConfig,
    APIProbe,
    add_usage,
    estimate_cost_usd,
    extract_usage,
    redact_base_url,
)


def _response(content="OK", usage=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


class FakeCompletions:
    def create(self, **kwargs):
        if kwargs.get("tools"):
            call = SimpleNamespace(function=SimpleNamespace(name="track2_probe"))
            return _response(tool_calls=[call], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5))
        if kwargs.get("extra_body"):
            return _response('{"action":"finish","reason":"probe"}')
        if kwargs["messages"][0].get("role") == "system":
            return _response('{"ok":true}', usage=SimpleNamespace(prompt_tokens=4, completion_tokens=1, total_tokens=5))
        return _response("OK", usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3))


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())
        self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[SimpleNamespace(id="small-code")]))


def test_api_probe_reports_capabilities_without_exposing_key():
    config = APIConfig("https://example.test/v1", "secret-not-serialized", "small-code")
    report = APIProbe(config, client=FakeClient()).run()
    assert report["api_key_configured"] is True
    assert "secret-not-serialized" not in str(report)
    assert report["probes"]["basic_chat"]["ok"] is True
    assert report["probes"]["tool_calling"]["tool_call_count"] == 1
    assert report["probes"]["json_prompt"]["valid_json"] is True
    assert report["probes"]["structured_outputs"]["ok"] is True


def test_usage_and_optional_cost_are_normalized():
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    add_usage(total, SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)))
    assert total == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    assert extract_usage(SimpleNamespace(usage=None))["total_tokens"] == 0
    assert estimate_cost_usd(total, 1.0, 2.0) == 0.00014


def test_url_redaction_removes_credentials_and_query_secrets():
    safe = redact_base_url("https://user:secret@example.test/v1?api_key=secret&region=us")
    assert "secret" not in safe
    assert "region=us" in safe
