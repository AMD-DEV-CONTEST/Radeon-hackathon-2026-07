import asyncio
import sqlite3

import pytest

import services.database_registry as registry
from services.db import close_connection, init_db
from services.model_execution import ModelTaskRequest
from services.model_registry import create_binding, create_model_profile, create_provider
from services.model_reliability import (
    FallbackRequired,
    ModelErrorCode,
    ModelExecutionError,
    RetryPolicy,
)
from services.model_routing import CredentialResolver, RoutedModelExecutionGateway


def setup_models(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    create_provider(
        {
            "id": "local-main",
            "display_name": "Local",
            "provider_type": "local_ollama",
            "base_url": "http://127.0.0.1:11434",
            "api_format": "ollama_chat",
            "enabled": True,
        }
    )
    create_provider(
        {
            "id": "cloud-main",
            "display_name": "Cloud",
            "provider_type": "openai_compatible",
            "base_url": "https://api.example.invalid/v1",
            "api_format": "openai_chat",
            "enabled": True,
        }
    )
    for profile_id, provider_id, model_name, privacy in (
        ("local-main:qwen", "local-main", "qwen2.5:7b", "local_only"),
        ("cloud-main:writer", "cloud-main", "writer-v1", "cloud_upload"),
    ):
        create_model_profile(
            {
                "id": profile_id,
                "provider_id": provider_id,
                "provider_model_name": model_name,
                "display_name": profile_id,
                "model_type": "text",
                "enabled": True,
                "supports_streaming": True,
                "supports_json_mode": True,
                "privacy_level": privacy,
            }
        )
    create_binding(
        {
            "id": "analysis-primary",
            "scope_type": "global",
            "task_type": "chapter_analysis",
            "target_id": "local-main:qwen",
        }
    )


def task():
    return ModelTaskRequest(
        task_id="reliable-task",
        task_type="chapter_analysis",
        database_id="default",
        book_id="default",
        messages=({"role": "user", "content": "chapter"},),
        privacy_level="private",
        requires_json=True,
        requires_streaming=True,
    )


class SequenceAdapter:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def complete(self, provider, profile, messages, options):
        self.calls.append(profile["id"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {"content": outcome, "usage": {}}


def gateway(adapter):
    return RoutedModelExecutionGateway(
        adapter=adapter,
        credential_resolver=CredentialResolver(env={}),
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
    )


def test_auth_failure_is_not_retried(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch)
    adapter = SequenceAdapter([ModelExecutionError(ModelErrorCode.AUTH_FAILED)])
    with pytest.raises(FallbackRequired) as captured:
        asyncio.run(gateway(adapter).execute(task()))
    assert captured.value.code is ModelErrorCode.AUTH_FAILED
    assert adapter.calls == ["local-main:qwen"]
    close_connection()


def test_timeout_retries_once_then_succeeds(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch)
    adapter = SequenceAdapter([ModelExecutionError(ModelErrorCode.TIMEOUT), "ok"])
    result = asyncio.run(gateway(adapter).execute(task()))
    assert result.content == "ok"
    assert adapter.calls == ["local-main:qwen", "local-main:qwen"]
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        attempts = conn.execute(
            "SELECT success,error_code FROM model_usage_log ORDER BY created_at,id"
        ).fetchall()
    assert sorted(attempts) == [(0, "TIMEOUT"), (1, None)]
    close_connection()


def test_fallback_requires_confirmation_and_calls_one_model(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch)
    adapter = SequenceAdapter([ModelExecutionError(ModelErrorCode.NETWORK_ERROR), ModelExecutionError(ModelErrorCode.NETWORK_ERROR)])
    execution = gateway(adapter)
    with pytest.raises(FallbackRequired) as captured:
        asyncio.run(execution.execute(task()))
    assert captured.value.candidate_model_ids == ("cloud-main:writer",)
    assert adapter.calls == ["local-main:qwen", "local-main:qwen"]

    with pytest.raises(PermissionError):
        asyncio.run(
            execution.execute_fallback(task(), "cloud-main:writer", confirmed=False)
        )
    assert adapter.calls == ["local-main:qwen", "local-main:qwen"]

    adapter.outcomes = ["cloud ok"]
    result = asyncio.run(
        execution.execute_fallback(task(), "cloud-main:writer", confirmed=True)
    )
    assert result.model_profile_id == "cloud-main:writer"
    assert adapter.calls[-1] == "cloud-main:writer"
    close_connection()


def test_context_too_long_is_not_retried(tmp_path, monkeypatch):
    setup_models(tmp_path, monkeypatch)
    adapter = SequenceAdapter([ModelExecutionError(ModelErrorCode.CONTEXT_TOO_LONG)])
    with pytest.raises(FallbackRequired):
        asyncio.run(gateway(adapter).execute(task()))
    assert adapter.calls == ["local-main:qwen"]
    close_connection()
