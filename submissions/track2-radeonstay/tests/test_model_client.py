from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from radeonstay.config import Settings
from radeonstay.model_client import LocalModelClient, ModelClientError


def _settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    return Settings(
        project_root=root,
        model_base_url="http://127.0.0.1:8000/v1",
        model_name="local-test-model",
        model_api_key="local-only",
        model_timeout_seconds=5.0,
        database_path=root / "runtime" / "test.db",
        policy_dir=root / "data" / "policies",
        audit_secret="model-client-test-audit-secret",
        identity_secret="model-client-test-identity-secret",
        deterministic_mode=False,
        host="127.0.0.1",
        port=7860,
        public_demo_enabled=False,
        ui_username="",
        ui_password="",
    )


def _client(model_ids: list[str]) -> httpx.Client:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": model_id, "path": "/private/model/path"}
                    for model_id in model_ids
                ],
            },
        )

    return httpx.Client(
        base_url="http://127.0.0.1:8000/v1/",
        transport=httpx.MockTransport(handler),
    )


def test_health_requires_the_configured_model_and_redacts_raw_service_payload() -> None:
    model = LocalModelClient(_settings(), _client(["local-test-model", "other-model"]))
    try:
        health = model.health()
    finally:
        model.close()

    assert health["ok"] is True
    assert health["target_model_advertised"] is True
    assert health["advertised_model_count"] == 2
    assert "service" not in health
    assert "/private/model/path" not in str(health)


def test_health_rejects_a_reachable_endpoint_serving_the_wrong_model() -> None:
    model = LocalModelClient(_settings(), _client(["wrong-model"]))
    try:
        with pytest.raises(ModelClientError, match="does not advertise"):
            model.health()
    finally:
        model.close()


def test_chat_trace_records_usage_without_response_content() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "local-test-model",
                "choices": [{"message": {"content": "local private answer"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                "timings": {"predicted_per_second": 42.5},
            },
        )

    client = httpx.Client(
        base_url="http://127.0.0.1:8000/v1/",
        transport=httpx.MockTransport(handler),
    )
    model = LocalModelClient(_settings(), client)
    try:
        model.start_trace()
        model.chat([{"role": "user", "content": "hello"}])
        calls = model.finish_trace()
    finally:
        model.close()

    assert len(calls) == 1
    assert calls[0]["ok"] is True
    assert calls[0]["prompt_tokens"] == 12
    assert calls[0]["completion_tokens"] == 4
    assert calls[0]["effective_output_tokens_per_second"] > 0
    assert calls[0]["server_decode_tokens_per_second"] == 42.5
    assert calls[0]["ttft_ms"] is None
    assert calls[0]["server_timings"] == {"predicted_per_second": 42.5}
    assert "local private answer" not in str(calls)


def test_chat_http_failure_is_traced_without_response_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="private response secret")

    client = httpx.Client(
        base_url="http://127.0.0.1:8000/v1/",
        transport=httpx.MockTransport(handler),
    )
    model = LocalModelClient(_settings(), client)
    try:
        model.start_trace()
        with pytest.raises(ModelClientError):
            model.chat([{"role": "user", "content": "hello"}])
        calls = model.finish_trace()
    finally:
        model.close()

    assert len(calls) == 1
    assert calls[0]["ok"] is False
    assert calls[0]["elapsed_ms"] >= 0
    assert calls[0]["error_type"] == "HTTPStatusError"
    assert "private response secret" not in str(calls)


def test_chat_wrong_model_alias_is_traced_without_response_content() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "private-wrong-alias",
                "choices": [{"message": {"content": "private answer secret"}}],
            },
        )

    client = httpx.Client(
        base_url="http://127.0.0.1:8000/v1/",
        transport=httpx.MockTransport(handler),
    )
    model = LocalModelClient(_settings(), client)
    try:
        model.start_trace()
        with pytest.raises(ModelClientError, match="unexpected model alias"):
            model.chat([{"role": "user", "content": "hello"}])
        calls = model.finish_trace()
    finally:
        model.close()

    assert len(calls) == 1
    assert calls[0]["ok"] is False
    assert calls[0]["elapsed_ms"] >= 0
    assert calls[0]["error_type"] == "ModelClientError"
    assert "private-wrong-alias" not in str(calls)
    assert "private answer secret" not in str(calls)


def test_chat_json_marks_invalid_first_response_before_successful_repair() -> None:
    response_contents = iter(["not valid json", '{"answer": "repaired"}'])

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "local-test-model",
                "choices": [{"message": {"content": next(response_contents)}}],
            },
        )

    client = httpx.Client(
        base_url="http://127.0.0.1:8000/v1/",
        transport=httpx.MockTransport(handler),
    )
    model = LocalModelClient(_settings(), client)
    try:
        model.start_trace()
        parsed, _ = model.chat_json([{"role": "user", "content": "return json"}])
        calls = model.finish_trace()
    finally:
        model.close()

    assert parsed == {"answer": "repaired"}
    assert len(calls) == 2
    assert calls[0]["ok"] is False
    assert calls[0]["error_type"] == "ValueError"
    assert calls[1]["ok"] is True
