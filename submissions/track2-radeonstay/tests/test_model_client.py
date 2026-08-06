from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from radeonstay.config import Settings
from radeonstay.model_client import (
    LocalModelClient,
    ModelClientError,
    ModelResponseValidationError,
)
from radeonstay.runtime_binding import (
    RuntimeBindingResult,
    _listening_socket_inodes,
    _model_sha256_matches,
    _process_socket_inodes,
)


def _settings(*, thinking_enabled: bool = False) -> Settings:
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
        model_enable_thinking=thinking_enabled,
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
        model.record_last_trace_validation(
            validation_stage="agent_plan_contract",
            validation_ok=True,
            outcome="accepted_initial",
        )
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
    assert calls[0]["purpose"] == "chat"
    assert calls[0]["attempt"] == 1
    assert calls[0]["max_tokens"] == 800
    assert calls[0]["response_format"] == "text"
    assert calls[0]["thinking_enabled"] is False
    assert calls[0]["schema_constrained"] is False
    assert calls[0]["request_configuration_bound"] is False
    assert len(calls[0]["request_configuration_sha256"]) == 64
    assert calls[0]["validation_stage"] == "agent_plan_contract"
    assert calls[0]["validation_ok"] is True
    assert calls[0]["validation_outcome"] == "accepted_initial"
    assert "local private answer" not in str(calls)


def test_bound_request_profile_fails_before_http_when_actual_schema_drifts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    settings = _settings()
    model = LocalModelClient(
        settings,
        httpx.Client(
            base_url="http://127.0.0.1:8000/v1/",
            transport=httpx.MockTransport(handler),
        ),
        runtime_proof={
            "request_configuration_sha256": settings.request_configuration_sha256,
        },
    )
    try:
        model.start_trace()
        with pytest.raises(ModelClientError, match="request configuration"):
            model.chat([{"role": "user", "content": "unconstrained call"}])
        calls = model.finish_trace()
    finally:
        model.close()

    assert requests == []
    assert calls[0]["ok"] is False


def test_chat_binds_the_same_runtime_instance_before_and_after_inference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "local-test-model",
                "choices": [{"message": {"content": "bound response"}}],
            },
        )

    client = httpx.Client(
        base_url="http://127.0.0.1:8000/v1/",
        transport=httpx.MockTransport(handler),
    )
    model = LocalModelClient(_settings(), client)
    digest = "a" * 64
    results = iter(
        [
            RuntimeBindingResult(True, True, digest),
            RuntimeBindingResult(True, True, digest),
        ]
    )
    monkeypatch.setattr(model, "runtime_binding_result", lambda: next(results))
    try:
        model.start_trace()
        model.chat([{"role": "user", "content": "hello"}])
        calls = model.finish_trace()

        monkeypatch.setattr(
            model,
            "runtime_binding_result",
            lambda: RuntimeBindingResult(
                configured=True,
                valid=False,
                error_code="process_identity_mismatch",
            ),
        )
        model.start_trace()
        with pytest.raises(ModelClientError, match="process binding"):
            model.chat([{"role": "user", "content": "blocked"}])
        failed_calls = model.finish_trace()
    finally:
        model.close()

    assert len(requests) == 1
    assert calls[0]["process_binding_valid"] is True
    assert calls[0]["runtime_instance_manifest_sha256"] == digest
    assert failed_calls[0]["ok"] is False
    assert failed_calls[0]["process_binding_valid"] is False

    proc_root = tmp_path / "proc" / "42"
    (proc_root / "fd").mkdir(parents=True)
    (proc_root / "net").mkdir()
    (proc_root / "fd" / "7").symlink_to("socket:[4242]")
    (proc_root / "net" / "tcp").write_text(
        "sl local_address rem_address st tx_queue tr tm retrnsmt uid timeout inode\n"
        "0: 0100007F:1F40 00000000:0000 0A 00000000:00000000 "
        "00:00000000 00000000 1000 0 4242\n",
        encoding="ascii",
    )
    process_inodes = _process_socket_inodes(proc_root)
    listener_inodes = _listening_socket_inodes(proc_root, 8000)
    assert process_inodes.intersection(listener_inodes) == {4242}
    (proc_root / "net" / "tcp").write_text(
        "sl local_address rem_address st tx_queue tr tm retrnsmt uid timeout inode\n"
        "0: 00000000:1F40 00000000:0000 0A 00000000:00000000 "
        "00:00000000 00000000 1000 0 4242\n",
        encoding="ascii",
    )
    assert not _listening_socket_inodes(proc_root, 8000)

    model_file = tmp_path / "bound-model.gguf"
    model_file.write_bytes(b"model-a")
    expected_model_sha256 = hashlib.sha256(b"model-a").hexdigest()
    assert _model_sha256_matches(model_file, expected_model_sha256)
    model_file.write_bytes(b"model-b-different-size")
    assert not _model_sha256_matches(model_file, expected_model_sha256)


def test_chat_json_sends_llama_json_schema_thinking_flag_and_trace_fields() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "local-test-model",
                "choices": [{"message": {"content": '{"answer":"local"}'}}],
            },
        )

    client = httpx.Client(
        base_url="http://127.0.0.1:8000/v1/",
        transport=httpx.MockTransport(handler),
    )
    model = LocalModelClient(_settings(thinking_enabled=True), client)
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    try:
        model.start_trace()
        parsed, _ = model.chat_json(
            [{"role": "user", "content": "return json"}],
            json_schema=schema,
            json_schema_name="local_answer",
            trace_purpose="unit.schema",
            trace_attempt=2,
        )
        calls = model.finish_trace()
    finally:
        model.close()

    assert parsed == {"answer": "local"}
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert requests[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "local_answer",
            "strict": True,
            "schema": schema,
        },
    }
    assert calls[0]["purpose"] == "unit.schema"
    assert calls[0]["attempt"] == 2
    assert calls[0]["max_tokens"] == 1000
    assert calls[0]["response_format"] == "json_schema"
    assert calls[0]["json_schema_name"] == "local_answer"
    assert calls[0]["thinking_enabled"] is True
    assert calls[0]["schema_constrained"] is True


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
        parsed, repaired_result = model.chat_json(
            [{"role": "user", "content": "return json"}]
        )
        calls = model.finish_trace()
    finally:
        model.close()

    assert parsed == {"answer": "repaired"}
    assert repaired_result.syntax_repaired is True
    assert len(calls) == 2
    assert calls[0]["ok"] is False
    assert calls[0]["error_type"] == "JSONDecodeError"
    assert calls[1]["ok"] is True


def test_chat_json_can_forbid_a_third_syntax_repair_call() -> None:
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            json={
                "model": "local-test-model",
                "choices": [{"message": {"content": "not valid json"}}],
            },
        )

    client = httpx.Client(
        base_url="http://127.0.0.1:8000/v1/",
        transport=httpx.MockTransport(handler),
    )
    model = LocalModelClient(_settings(), client)
    try:
        model.start_trace()
        with pytest.raises(ModelResponseValidationError, match="bounded repair"):
            model.chat_json(
                [{"role": "user", "content": "repair json"}],
                allow_syntax_repair=False,
                trace_purpose="planner.semantic_repair",
                trace_attempt=2,
            )
        calls = model.finish_trace()
    finally:
        model.close()

    assert request_count == 1
    assert len(calls) == 1
    assert calls[0]["ok"] is False
    assert calls[0]["max_tokens"] == 1000
