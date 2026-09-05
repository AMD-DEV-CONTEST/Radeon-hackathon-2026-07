from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from radeonstay.cloud_model_client import RadeonCloudFreeModelClient
from radeonstay.config import Settings
from radeonstay.model_client import ModelClientError


def _settings(*, structured_mode: str = "auto") -> Settings:
    root = Path(__file__).resolve().parents[1]
    return Settings(
        project_root=root,
        model_base_url="http://127.0.0.1:8000/v1",
        model_name="local-test-model",
        model_api_key="local-only",
        model_timeout_seconds=5.0,
        database_path=Path(":memory:"),
        policy_dir=root / "data" / "policies",
        audit_secret="cloud-client-test-audit-secret-0001",
        identity_secret="cloud-client-test-identity-secret-02",
        deterministic_mode=False,
        host="127.0.0.1",
        port=7860,
        public_demo_enabled=False,
        ui_username="",
        ui_password="",
        inference_provider="radeon_cloud_free",
        radeon_cloud_base_url="https://developer.amd.com.cn/radeon/api/v1",
        radeon_cloud_model="Qwen3.6-35B-A3B",
        radeon_cloud_api_key="private-test-cloud-key-123456789",
        radeon_cloud_structured_mode=structured_mode,
        bonus_demo=True,
    )


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(
        base_url="https://developer.amd.com.cn/radeon/api/v1/",
        headers={"Authorization": "Bearer private-test-cloud-key-123456789"},
        transport=handler,
        follow_redirects=False,
    )


def test_health_is_configuration_only_and_spends_no_tokens() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    model = RadeonCloudFreeModelClient(
        _settings(),
        _client(httpx.MockTransport(handler)),
    )
    try:
        health = model.health()
    finally:
        model.close()

    assert requests == []
    assert health["ok"] is True
    assert health["local_only"] is False
    assert health["synthetic_only"] is True
    assert health["last_request"]["status"] == "not_yet_called"
    assert "api_key" not in repr(health).casefold()


def test_chat_uses_only_the_allow_listed_openai_compatible_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-safe-id",
                "model": "Qwen3.6-35B-A3B",
                "choices": [{"message": {"content": "hello"}}],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            },
        )

    model = RadeonCloudFreeModelClient(
        _settings(),
        _client(httpx.MockTransport(handler)),
    )
    try:
        model.start_trace()
        result = model.chat([{"role": "user", "content": "hello"}])
        calls = model.finish_trace()
    finally:
        model.close()

    payload = json.loads(requests[0].content)
    assert requests[0].url == httpx.URL(
        "https://developer.amd.com.cn/radeon/api/v1/chat/completions"
    )
    assert requests[0].headers["authorization"].startswith("Bearer ")
    assert payload["model"] == "Qwen3.6-35B-A3B"
    assert "chat_template_kwargs" not in payload
    assert result.model == "Qwen3.6-35B-A3B"
    assert calls[0]["provider"] == "radeon_cloud_free"
    assert calls[0]["response_id"] == "chatcmpl-safe-id"
    assert calls[0]["total_tokens"] == 5
    assert "private-test-cloud-key" not in repr(calls)


def test_structured_output_downgrades_once_and_caches_the_capability() -> None:
    response_formats: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        response_format = payload.get("response_format", {}).get("type", "text")
        response_formats.append(response_format)
        if response_format == "json_schema":
            return httpx.Response(400, json={"error": "unsupported"})
        return httpx.Response(
            200,
            json={
                "model": "Qwen3.6-35B-A3B",
                "choices": [{"message": {"content": '{"ok":true}'}}],
            },
        )

    model = RadeonCloudFreeModelClient(
        _settings(),
        _client(httpx.MockTransport(handler)),
    )
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    try:
        model.start_trace()
        first, _ = model.chat_json(
            [{"role": "user", "content": "json"}],
            json_schema=schema,
        )
        first_calls = model.finish_trace()
        model.chat_json(
            [{"role": "user", "content": "json again"}],
            json_schema=schema,
        )
    finally:
        model.close()

    assert first == {"ok": True}
    assert response_formats == ["json_schema", "json_object", "json_object"]
    assert [call["ok"] for call in first_calls] == [False, True]
    assert first_calls[1]["response_format"] == "json_object"


def test_fixed_json_object_mode_skips_json_schema_probe() -> None:
    response_formats: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        response_formats.append(payload["response_format"]["type"])
        return httpx.Response(
            200,
            json={
                "model": "Qwen3.6-35B-A3B",
                "choices": [{"message": {"content": '{"ok":true}'}}],
            },
        )

    model = RadeonCloudFreeModelClient(
        _settings(structured_mode="json_object"),
        _client(httpx.MockTransport(handler)),
    )
    try:
        parsed, _ = model.chat_json(
            [{"role": "user", "content": "json"}],
            json_schema={"type": "object"},
        )
    finally:
        model.close()

    assert parsed == {"ok": True}
    assert response_formats == ["json_object"]


def test_model_mismatch_and_http_errors_fail_closed_without_leaking_the_key() -> None:
    def wrong_model(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "unexpected-model",
                "choices": [{"message": {"content": "unsafe"}}],
            },
        )

    model = RadeonCloudFreeModelClient(
        _settings(),
        _client(httpx.MockTransport(wrong_model)),
    )
    try:
        with pytest.raises(ModelClientError, match="unexpected model") as mismatch:
            model.chat([{"role": "user", "content": "hello"}])
    finally:
        model.close()

    assert "private-test-cloud-key" not in str(mismatch.value)

    def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "credential rejected"})

    model = RadeonCloudFreeModelClient(
        _settings(),
        _client(httpx.MockTransport(unauthorized)),
    )
    try:
        model.start_trace()
        with pytest.raises(ModelClientError, match="request failed") as denied:
            model.chat([{"role": "user", "content": "hello"}])
        calls = model.finish_trace()
    finally:
        model.close()

    assert calls[0]["http_status"] == 401
    assert "credential rejected" not in str(denied.value)
    assert "private-test-cloud-key" not in str(denied.value)
