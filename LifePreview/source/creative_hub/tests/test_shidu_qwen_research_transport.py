from __future__ import annotations

import json

import pytest

from creative_hub.shidu.glm_research_transport import GlmRateLimitError
from creative_hub.shidu.provider_trace import (
    InMemoryStructuredProviderTraceSink,
    structured_provider_request_digest,
    structured_provider_response_digest,
)
from creative_hub.shidu.qwen_research_transport import (
    QWEN_RESEARCH_HOST,
    QWEN_RESEARCH_MODEL,
    QWEN_RESEARCH_PATH,
    RATE_LIMIT_FAILOVER_PROVIDER_ID,
    QwenStructuredModelClient,
    RateLimitFailoverStructuredModelClient,
)


class ResponseFixture:
    status = 200

    def __init__(self, payload):
        self._body = json.dumps(
            {
                "choices": [
                    {"message": {"content": json.dumps(payload)}}
                ]
            }
        ).encode()

    def read(self, limit):
        return self._body[:limit]


class ConnectionFixture:
    def __init__(self, host, port, timeout, *, calls, payload):
        calls.append({"host": host, "port": port, "timeout": timeout})
        self.calls = calls
        self.payload = payload

    def request(self, method, path, *, body, headers):
        self.calls[-1].update(
            {
                "method": method,
                "path": path,
                "body": json.loads(body),
                "authorization": headers["Authorization"],
            }
        )

    def getresponse(self):
        return ResponseFixture(self.payload)

    def close(self):
        return None


def test_qwen_client_uses_fixed_token_plan_endpoint_and_json_contract():
    calls = []

    def factory(host, port, timeout):
        return ConnectionFixture(
            host, port, timeout, calls=calls, payload={"claims": []}
        )

    client = QwenStructuredModelClient(
        api_key="test-qwen-key-do-not-log",
        _connection_factory=factory,
    )

    assert "test-qwen-key-do-not-log" not in repr(client)
    assert client.complete(
        system_prompt="中文固定策略",
        input_payload={"document": "Reader 数据"},
        response_schema={"type": "object"},
    ) == {"claims": []}
    assert calls[0]["host"] == QWEN_RESEARCH_HOST
    assert calls[0]["path"] == QWEN_RESEARCH_PATH
    assert QWEN_RESEARCH_HOST == "token-plan.cn-beijing.maas.aliyuncs.com"
    assert QWEN_RESEARCH_PATH == "/compatible-mode/v1/chat/completions"
    assert calls[0]["body"]["model"] == QWEN_RESEARCH_MODEL
    assert calls[0]["body"]["enable_thinking"] is False
    assert calls[0]["body"]["response_format"] == {"type": "json_object"}
    assert calls[0]["body"]["messages"][1]["content"] == (
        '{"document":"Reader 数据"}'
    )


class ModelFixture:
    def __init__(self, model_id, *, provider_id=None, result=None, error=None):
        self.model_id = model_id
        self.provider_id = provider_id or model_id.split("-", 1)[0]
        self.result = result
        self.error = error
        self.calls = 0

    def complete(self, **_request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def test_failover_uses_qwen_only_when_glm_is_rate_limited():
    primary = ModelFixture(
        "glm-5.1",
        provider_id="zhipu",
        error=GlmRateLimitError("limited"),
    )
    fallback = ModelFixture(
        "qwen3.7-plus",
        provider_id="aliyun",
        result={"claims": []},
    )
    client = RateLimitFailoverStructuredModelClient(primary, fallback)

    assert client.complete(
        system_prompt="fixed",
        input_payload={},
        response_schema={"type": "object"},
    ) == {"claims": []}
    assert primary.calls == 1
    assert fallback.calls == 1
    assert client.provider_id == RATE_LIMIT_FAILOVER_PROVIDER_ID
    assert client.model_id == "rate-limit-failover:glm-5.1->qwen3.7-plus"


def test_failover_rejects_non_zhipu_primary_provider():
    with pytest.raises(ValueError, match="primary provider"):
        RateLimitFailoverStructuredModelClient(
            ModelFixture("glm-5.1", provider_id="other"),
            ModelFixture(
                QWEN_RESEARCH_MODEL,
                provider_id="aliyun",
                result={"claims": []},
            ),
        )


@pytest.mark.parametrize(
    ("provider_id", "model_id"),
    [
        ("other", QWEN_RESEARCH_MODEL),
        ("aliyun", "other-qwen-model"),
    ],
)
def test_failover_rejects_non_application_owned_qwen_fallback(
    provider_id,
    model_id,
):
    with pytest.raises(ValueError, match="fallback provider"):
        RateLimitFailoverStructuredModelClient(
            ModelFixture("glm-5.1", provider_id="zhipu"),
            ModelFixture(model_id, provider_id=provider_id, result={"claims": []}),
        )


def test_failover_emits_one_digest_bound_trace_for_primary_success_and_429_fallback():
    request = {
        "system_prompt": "fixed policy",
        "input_payload": {"document": "Reader 数据"},
        "response_schema": {"type": "object"},
    }

    primary_sink = InMemoryStructuredProviderTraceSink()
    primary = ModelFixture("glm-5.1", provider_id="zhipu", result={"claims": ["a"]})
    primary_client = RateLimitFailoverStructuredModelClient(
        primary,
        ModelFixture("qwen3.7-plus", provider_id="aliyun", result={"claims": []}),
        trace_sink=primary_sink,
    )
    primary_result = primary_client.complete(**request)
    primary_trace = primary_sink.traces[0]
    assert len(primary_sink.traces) == 1
    assert primary_trace.requested_provider_id == "zhipu"
    assert primary_trace.actual_provider_id == "zhipu"
    assert primary_trace.actual_model_id == "glm-5.1"
    assert primary_trace.fallback_reason is None
    assert primary_trace.status == "success"
    assert primary_trace.request_digest == structured_provider_request_digest(**request)
    assert primary_trace.response_digest == structured_provider_response_digest(primary_result)

    fallback_sink = InMemoryStructuredProviderTraceSink()
    fallback_client = RateLimitFailoverStructuredModelClient(
        ModelFixture(
            "glm-5.1",
            provider_id="zhipu",
            error=GlmRateLimitError("limited"),
        ),
        ModelFixture(
            "qwen3.7-plus",
            provider_id="aliyun",
            result={"claims": ["fallback"]},
        ),
        trace_sink=fallback_sink,
    )
    fallback_result = fallback_client.complete(**request)
    fallback_trace = fallback_sink.traces[0]
    assert len(fallback_sink.traces) == 1
    assert fallback_trace.requested_provider_id == "zhipu"
    assert fallback_trace.requested_model_id == "glm-5.1"
    assert fallback_trace.actual_provider_id == "aliyun"
    assert fallback_trace.actual_model_id == "qwen3.7-plus"
    assert fallback_trace.fallback_reason == "glm_http_429"
    assert fallback_trace.status == "success"
    assert fallback_trace.request_digest == structured_provider_request_digest(**request)
    assert fallback_trace.response_digest == structured_provider_response_digest(fallback_result)


def test_failover_does_not_hide_non_rate_limit_primary_errors():
    failure = RuntimeError("invalid response")
    primary = ModelFixture("glm-5.1", provider_id="zhipu", error=failure)
    fallback = ModelFixture(
        "qwen3.7-plus",
        provider_id="aliyun",
        result={"claims": []},
    )
    client = RateLimitFailoverStructuredModelClient(primary, fallback)

    try:
        client.complete(
            system_prompt="fixed",
            input_payload={},
            response_schema={"type": "object"},
        )
    except RuntimeError as caught:
        assert caught is failure
    else:
        raise AssertionError("non-rate-limit errors must remain fail-closed")
    assert fallback.calls == 0
