import asyncio

import pytest
from pydantic import ValidationError

import services.database_registry as registry
from app.models import ModelExecuteRequest
from services.db import close_connection, init_db
from services.model_execution import (
    ModelTaskRequest,
    ModelTaskResult,
    resolve_task_type,
)
from services.model_registry import create_binding, create_model_profile, create_provider
from services.model_routing import UniqueModelRouter


def _setup_registry(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
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
    for profile_id in ("legacy-model", "canonical-model"):
        create_model_profile(
            {
                "id": profile_id,
                "provider_id": "local-main",
                "provider_model_name": profile_id,
                "display_name": profile_id,
                "model_type": "text",
                "enabled": True,
                "supports_streaming": True,
                "privacy_level": "local_only",
            }
        )


def _request(task_type="chapter_analysis"):
    return ModelTaskRequest(
        task_id="task-1",
        task_type=task_type,
        database_id="default",
        book_id="default",
        messages=({"role": "user", "content": "chapter"},),
        privacy_level="local_only",
    )


def test_alias_resolution_is_one_way_and_deterministic():
    resolution = resolve_task_type("chapter_analysis")
    assert resolution.canonical == "chapter.analyze"
    assert resolution.legacy_source == "chapter_analysis"
    assert resolution.binding_lookup_types == ("chapter_analysis", "chapter.analyze")

    canonical = resolve_task_type("chapter.analyze")
    assert canonical.legacy_source is None
    assert canonical.binding_lookup_types == ("chapter.analyze",)
    with pytest.raises(ValueError):
        resolve_task_type("chapter.please_guess")


def test_public_request_accepts_canonical_and_rejects_unknown():
    base = {
        "task_id": "task-1",
        "database_id": "default",
        "book_id": "default",
        "messages": [{"role": "user", "content": "chapter"}],
    }
    assert ModelExecuteRequest(task_type="text.polish", **base).task_type == "text.polish"
    assert ModelExecuteRequest(task_type="creative_assist", **base).task_type == "creative_assist"
    with pytest.raises(ValidationError):
        ModelExecuteRequest(task_type="unknown.operation", **base)


def test_legacy_binding_wins_before_canonical_binding_in_same_scope(tmp_path, monkeypatch):
    _setup_registry(tmp_path, monkeypatch)
    create_binding(
        {
            "id": "legacy-binding",
            "scope_type": "global",
            "scope_id": None,
            "task_type": "chapter_analysis",
            "target_id": "legacy-model",
            "priority": 0,
        }
    )
    create_binding(
        {
            "id": "canonical-binding",
            "scope_type": "global",
            "scope_id": None,
            "task_type": "chapter.analyze",
            "target_id": "canonical-model",
            "priority": 100,
        }
    )
    route = UniqueModelRouter().resolve(_request())
    assert route.selected_model_profile_id == "legacy-model"
    assert route.reason == "global_binding:legacy_exact"
    close_connection()


def test_canonical_binding_is_fallback_for_legacy_request(tmp_path, monkeypatch):
    _setup_registry(tmp_path, monkeypatch)
    create_binding(
        {
            "id": "canonical-binding",
            "scope_type": "global",
            "scope_id": None,
            "task_type": "chapter.analyze",
            "target_id": "canonical-model",
            "priority": 0,
        }
    )
    route = UniqueModelRouter().resolve(_request())
    assert route.selected_model_profile_id == "canonical-model"
    assert route.reason == "global_binding:canonical"
    close_connection()


def test_result_read_model_returns_canonical_name_and_legacy_source():
    result = ModelTaskResult(
        task_id="task-1",
        model_profile_id="model-1",
        provider_id="provider-1",
        content="answer",
        task_type="chapter.analyze",
        legacy_task_type="chapter_analysis",
        runtime="local_ollama",
        fallback_used=False,
    )
    payload = result.to_read_model()
    assert payload["task_type"] == "chapter.analyze"
    assert payload["legacy_task_type"] == "chapter_analysis"
    assert payload["output"] == {"content": "answer"}
    assert payload["fallback_used"] is False
