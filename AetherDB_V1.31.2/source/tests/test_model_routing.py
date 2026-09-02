import asyncio
import sqlite3

import pytest

import services.database_registry as registry
from services.db import close_connection, init_db
from services.model_execution import ModelTaskRequest
from services.model_registry import create_binding, create_model_profile, create_provider
from services.model_routing import (
    CredentialResolver,
    ExistingProviderAdapter,
    ModelRouteError,
    RouteStatus,
    RoutedModelExecutionGateway,
    UniqueModelRouter,
)


class RecordingAdapter:
    def __init__(self):
        self.calls = []

    async def complete(self, provider, model_profile, messages, options):
        self.calls.append((provider, model_profile, messages, options))
        return {
            "content": "ok",
            "usage": {"input_tokens": 4, "output_tokens": 2},
            "provider_request_id": "request-1",
        }


def setup_registry(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()
    return runtime_root


def add_local_model(profile_id, provider_model_name):
    if profile_id == "local-main:qwen":
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
    return create_model_profile(
        {
            "id": profile_id,
            "provider_id": "local-main",
            "provider_model_name": provider_model_name,
            "display_name": profile_id,
            "model_type": "text",
            "enabled": True,
            "supports_streaming": True,
            "supports_json_mode": True,
            "privacy_level": "local_only",
        }
    )


def add_cloud_model(profile_id, provider_model_name):
    create_provider(
        {
            "id": "cloud-main",
            "display_name": "Cloud",
            "provider_type": "openai_compatible",
            "base_url": "https://api.example.com/v1",
            "api_format": "openai_compatible",
            "credential_ref": "env:CLOUD_TOKEN",
            "enabled": True,
        }
    )
    return create_model_profile(
        {
            "id": profile_id,
            "provider_id": "cloud-main",
            "provider_model_name": provider_model_name,
            "display_name": profile_id,
            "model_type": "text",
            "enabled": True,
            "supports_streaming": True,
            "supports_json_mode": True,
            "privacy_level": "cloud_upload",
        }
    )


def task(**overrides):
    data = {
        "task_id": "task-1",
        "task_type": "chapter_analysis",
        "database_id": "default",
        "book_id": "default",
        "messages": ({"role": "user", "content": "chapter"},),
        "privacy_level": "local_only",
        "requires_json": True,
        "requires_streaming": True,
    }
    data.update(overrides)
    return ModelTaskRequest(**data)


def test_single_model_resolves_and_records_exact_provider_model(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    add_local_model("local-main:qwen", "qwen2.5:7b")
    adapter = RecordingAdapter()
    gateway = RoutedModelExecutionGateway(adapter=adapter, credential_resolver=CredentialResolver(env={}))

    result = asyncio.run(gateway.execute(task()))

    assert result.provider_id == "local-main"
    assert result.model_profile_id == "local-main:qwen"
    assert adapter.calls[0][1]["provider_model_name"] == "qwen2.5:7b"
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        usage = conn.execute(
            "SELECT provider_id,model_profile_id,provider_model_name FROM model_usage_log"
        ).fetchone()
    assert usage == ("local-main", "local-main:qwen", "qwen2.5:7b")
    with sqlite3.connect(registry.get_db_path("default")) as conn:
        audit = conn.execute(
            "SELECT details FROM audit_log WHERE event_type='model.execute' ORDER BY log_id DESC LIMIT 1"
        ).fetchone()[0]
    assert "qwen2.5:7b" in audit
    close_connection()


def test_cloud_json_task_requests_json_object_response_format(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    add_cloud_model("cloud-main:analysis", "deepseek-v4-flash")
    adapter = RecordingAdapter()
    gateway = RoutedModelExecutionGateway(
        adapter=adapter,
        credential_resolver=CredentialResolver(env={"CLOUD_TOKEN": "resolved-value"}),
    )

    result = asyncio.run(
        gateway.execute(
            task(privacy_level="cloud_upload", requires_json=True)
        )
    )

    assert result.model_profile_id == "cloud-main:analysis"
    assert adapter.calls[0][3]["response_format"] == {"type": "json_object"}
    assert adapter.calls[0][3]["credential"] == "resolved-value"
    close_connection()


def test_multiple_models_without_binding_are_ambiguous_and_not_called(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    add_local_model("local-main:qwen", "qwen2.5:7b")
    add_local_model("local-main:coder", "qwen2.5-coder:7b")
    adapter = RecordingAdapter()
    gateway = RoutedModelExecutionGateway(adapter=adapter, credential_resolver=CredentialResolver(env={}))

    with pytest.raises(ModelRouteError) as captured:
        asyncio.run(gateway.execute(task()))

    assert captured.value.result.status is RouteStatus.AMBIGUOUS
    assert adapter.calls == []
    close_connection()


def test_text_translation_ignores_non_text_model_profiles(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    add_local_model("local-main:qwen", "qwen2.5:7b")
    create_model_profile(
        {
            "id": "local-main:image",
            "provider_id": "local-main",
            "provider_model_name": "image-generator:latest",
            "display_name": "Image generator",
            "model_type": "image",
            "enabled": True,
            "privacy_level": "local_only",
        }
    )

    request = task(
        task_type="translation.chapter",
        privacy_level="local_only",
        requires_json=False,
        requires_streaming=False,
    )

    result = UniqueModelRouter().resolve(request)

    assert result.status is RouteStatus.RESOLVED
    assert result.selected_model_profile_id == "local-main:qwen"
    close_connection()


def test_scope_priority_and_single_request_override(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    add_local_model("local-main:qwen", "qwen2.5:7b")
    add_local_model("local-main:coder", "qwen2.5-coder:7b")
    create_binding(
        {
            "id": "global-analysis",
            "scope_type": "global",
            "scope_id": None,
            "task_type": "chapter_analysis",
            "target_id": "local-main:qwen",
            "priority": 0,
        }
    )
    create_binding(
        {
            "id": "book-analysis",
            "scope_type": "book",
            "scope_id": "default/default",
            "task_type": "chapter_analysis",
            "target_id": "local-main:coder",
            "priority": 0,
        }
    )

    router = UniqueModelRouter()
    assert router.resolve(task()).selected_model_profile_id == "local-main:coder"
    assert router.resolve(task(user_selected_model_id="local-main:qwen")).selected_model_profile_id == "local-main:qwen"
    close_connection()


def test_privacy_and_health_rules_block_execution(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    add_local_model("local-main:qwen", "qwen2.5:7b")
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        conn.execute(
            "UPDATE model_profiles SET privacy_level='cloud_upload' WHERE id='local-main:qwen'"
        )
        conn.commit()
    assert UniqueModelRouter().resolve(task()).status is RouteStatus.BLOCKED

    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        conn.execute(
            "UPDATE model_profiles SET privacy_level='local_only',health_status='unhealthy' "
            "WHERE id='local-main:qwen'"
        )
        conn.commit()
    assert UniqueModelRouter().resolve(task()).status is RouteStatus.UNAVAILABLE
    adapter = RecordingAdapter()
    with pytest.raises(ModelRouteError):
        asyncio.run(
            RoutedModelExecutionGateway(
                adapter=adapter,
                credential_resolver=CredentialResolver(env={}),
            ).execute(task())
        )
    assert adapter.calls == []
    close_connection()


def test_credential_resolver_rejects_executable_and_file_refs():
    resolver = CredentialResolver(env={"MODEL_TOKEN": "resolved-value"})
    assert resolver.resolve("env:MODEL_TOKEN") == "resolved-value"
    for ref in ("file:C:/secret", "cmd:whoami", "shell:test", "python:test"):
        with pytest.raises(ValueError):
            resolver.resolve(ref)
    with pytest.raises(ValueError):
        resolver.resolve("env:MISSING_TOKEN")


def test_existing_adapter_passes_exact_provider_model_name(monkeypatch):
    calls = []

    class FakeOllamaProvider:
        def __init__(self, base_url, model):
            calls.append(("init", base_url, model))

        def chat(self, messages, model=None, **kwargs):
            calls.append(("chat", model, messages, kwargs))
            return "ok"

    monkeypatch.setattr("services.llm_provider.OllamaProvider", FakeOllamaProvider)
    provider = {
        "id": "local-main",
        "provider_type": "local_ollama",
        "base_url": "http://127.0.0.1:11434",
    }
    profile = {"provider_model_name": "qwen2.5:7b"}
    result = asyncio.run(
        ExistingProviderAdapter().complete(
            provider,
            profile,
            [{"role": "user", "content": "test"}],
            {"credential": None, "max_tokens": 100},
        )
    )

    assert result["content"] == "ok"
    assert calls[0] == ("init", "http://127.0.0.1:11434", "qwen2.5:7b")
    assert calls[1][0:2] == ("chat", "qwen2.5:7b")
