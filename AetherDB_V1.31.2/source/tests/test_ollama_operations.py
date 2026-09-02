import json
import sqlite3

import services.database_registry as registry
import services.ollama_management as management
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from services.model_execution import ModelTaskRequest
from services.model_registry import (
    create_model_profile,
    create_provider,
    update_model_profile,
)
from services.ollama_observability import (
    list_model_observations,
    mark_probe_result,
)
from services.model_routing import RouteStatus, UniqueModelRouter
from tests.asgi_client import asgi_request


class PullResponse:
    status_code = 200

    def iter_lines(self):
        yield json.dumps({"status": "pulling", "completed": 5, "total": 10}).encode()
        yield json.dumps({"status": "success", "completed": 10, "total": 10}).encode()

    def close(self):
        pass


def request(method, path, *, json_body=None, headers=None):
    return asgi_request(app, method, path, json_body=json_body, headers=headers)


def setup_registry(tmp_path, monkeypatch):
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
            "models_endpoint": "/api/tags",
        }
    )
    create_model_profile(
        {
            "id": "local-main:qwen",
            "provider_id": "local-main",
            "provider_model_name": "qwen3:8b",
            "display_name": "Qwen 3 8B",
            "model_type": "text",
            "privacy_level": "local_only",
        }
    )
    return {"X-API-Key": ADMIN_API_KEY}


def test_pull_runs_as_persisted_background_operation(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(
        management,
        "_start_background_thread",
        lambda target, args, _name: target(*args),
    )
    monkeypatch.setattr(management.requests, "request", lambda *_args, **_kwargs: PullResponse())

    assert request("POST", "/api/ollama/models/pull", json_body={"model": "qwen3:8b"})[0] == 401
    status, body = request(
        "POST",
        "/api/ollama/models/pull",
        headers=admin,
        json_body={"provider_id": "local-main", "model": "qwen3:8b"},
    )

    assert status == 202
    operation_id = body["operation"]["id"]
    status, detail = request(
        "GET", f"/api/ollama/operations/{operation_id}", headers=admin
    )
    assert status == 200
    assert detail["operation"]["status"] == "completed"
    assert detail["operation"]["progress"] == 1.0
    close_connection()


def test_load_unload_and_confirmed_delete_use_fixed_api_actions(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    calls = []

    def fake_request(provider, method, endpoint, payload=None):
        calls.append((provider["id"], method, endpoint, payload))
        return {"done": True}

    monkeypatch.setattr(management, "_request_json", fake_request)
    monkeypatch.setattr(management, "_is_managed_running", lambda: True)
    for endpoint in ("load", "unload"):
        status, _ = request(
            "POST",
            f"/api/ollama/models/{endpoint}",
            headers=admin,
            json_body={"provider_id": "local-main", "model": "qwen3:8b"},
        )
        assert status == 200
    assert calls[0][2:] == (
        "/api/generate",
        {"model": "qwen3:8b", "prompt": "", "stream": False, "keep_alive": -1},
    )
    assert calls[1][3]["keep_alive"] == 0

    status, body = request(
        "POST",
        "/api/ollama/models/delete",
        headers=admin,
        json_body={
            "provider_id": "local-main",
            "model": "qwen3:8b",
            "confirm_model": "wrong-model",
        },
    )
    assert status == 409
    assert body["detail"]["code"] == "CONFIRMATION_MISMATCH"

    status, body = request(
        "POST",
        "/api/ollama/models/delete",
        headers=admin,
        json_body={
            "provider_id": "local-main",
            "model": "qwen3:8b",
            "confirm_model": "qwen3:8b",
        },
    )
    assert status == 200
    assert body["profile_deleted"] is False
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        profile = conn.execute(
            "SELECT enabled,remote_status FROM model_profiles WHERE id='local-main:qwen'"
        ).fetchone()
    assert profile == (0, "missing")
    close_connection()


def test_external_runtime_models_are_observed_but_not_controlled(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(management, "_is_managed_running", lambda: False)

    for endpoint, payload in (
        ("load", {"provider_id": "local-main", "model": "qwen3:8b"}),
        ("unload", {"provider_id": "local-main", "model": "qwen3:8b"}),
        (
            "delete",
            {
                "provider_id": "local-main",
                "model": "qwen3:8b",
                "confirm_model": "qwen3:8b",
            },
        ),
    ):
        status, body = request(
            "POST",
            f"/api/ollama/models/{endpoint}",
            headers=admin,
            json_body=payload,
        )
        assert status == 409
        assert body["detail"]["code"] == "EXTERNAL_RUNTIME_CONTROL_BLOCKED"
    close_connection()


def test_interrupted_pull_is_recoverable_and_explicitly_retryable(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        conn.execute(
            "INSERT INTO ollama_operations "
            "(id,provider_id,operation,model_name,status,status_message) "
            "VALUES ('old-pull','local-main','pull','qwen3:8b','running','downloading')"
        )
        conn.execute(
            "INSERT INTO ollama_operations "
            "(id,provider_id,operation,model_name,status,status_message,cancel_requested) "
            "VALUES ('cancel-pull','local-main','pull','other:latest','running','cancelling',1)"
        )
        conn.commit()

    management.recover_interrupted_operations()
    recovered = management.get_operation("old-pull")
    assert recovered["status"] == "failed"
    assert recovered["error_code"] == "INTERRUPTED"
    assert management.get_operation("cancel-pull")["status"] == "cancelled"

    monkeypatch.setattr(
        management,
        "_start_background_thread",
        lambda target, args, _name: target(*args),
    )
    monkeypatch.setattr(management.requests, "request", lambda *_args, **_kwargs: PullResponse())
    status, body = request(
        "POST", "/api/ollama/operations/old-pull/retry", headers=admin, json_body={}
    )
    assert status == 202
    assert body["operation"]["status"] == "completed"
    assert body["operation"]["retry_of"] == "old-pull"
    close_connection()


def test_duplicate_pull_is_idempotent_and_queued_pull_can_be_cancelled(
    tmp_path, monkeypatch
):
    admin = setup_registry(tmp_path, monkeypatch)
    scheduled = []
    monkeypatch.setattr(
        management,
        "_start_background_thread",
        lambda target, args, name: scheduled.append((target, args, name)),
    )

    first_status, first = request(
        "POST",
        "/api/ollama/models/pull",
        headers=admin,
        json_body={"provider_id": "local-main", "model": "qwen3:8b"},
    )
    second_status, second = request(
        "POST",
        "/api/ollama/models/pull",
        headers=admin,
        json_body={"provider_id": "local-main", "model": "qwen3:8b"},
    )

    assert first_status == second_status == 202
    assert first["operation"]["id"] == second["operation"]["id"]
    assert len(scheduled) == 1
    operation_id = first["operation"]["id"]
    status, body = request(
        "POST",
        f"/api/ollama/operations/{operation_id}/cancel",
        headers=admin,
        json_body={},
    )
    assert status == 200
    assert body["operation"]["status"] == "cancelled"
    assert body["operation"]["cancel_requested"] is True
    close_connection()


def test_running_pull_cancel_closes_active_response(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(
        management,
        "_start_background_thread",
        lambda _target, _args, _name: None,
    )
    operation = management.start_pull_operation("qwen3:8b", "local-main")
    management._update_operation(operation["id"], status="running")

    class ActiveResponse:
        closed = False

        def close(self):
            self.closed = True

    response = ActiveResponse()
    management._ACTIVE_OPERATION_RESPONSES[operation["id"]] = response
    result = management.cancel_operation(operation["id"])

    assert response.closed is True
    assert result["cancel_requested"] is True
    management._ACTIVE_OPERATION_RESPONSES.pop(operation["id"], None)
    management._run_pull_operation(operation["id"])
    assert management.get_operation(operation["id"])["status"] == "cancelled"
    close_connection()


def test_profile_sync_preserves_user_choice_and_marks_unverified_or_missing(
    tmp_path, monkeypatch
):
    setup_registry(tmp_path, monkeypatch)
    create_model_profile(
        {
            "id": "local-main:missing",
            "provider_id": "local-main",
            "provider_model_name": "removed:latest",
            "display_name": "Removed",
            "model_type": "text",
            "enabled": True,
            "privacy_level": "local_only",
        }
    )

    def fake_request(_provider, method, endpoint, payload=None):
        if method == "GET" and endpoint == "/api/tags":
            return {
                "models": [
                    {"name": "qwen3:8b"},
                    {"name": "unknown:latest"},
                ]
            }
        if endpoint == "/api/show" and payload["model"] == "qwen3:8b":
            return {
                "capabilities": ["completion", "tools"],
                "model_info": {"qwen3.context_length": 32768},
            }
        raise management.ModelDiagnosticError("HTTP_500", "Model details unavailable")

    monkeypatch.setattr(management, "_request_json", fake_request)
    result = management.sync_ollama_model_profiles("local-main")
    profiles = {
        item["provider_model_name"]: item
        for item in management.list_model_profiles("local-main")
    }

    assert result["installed_model_count"] == 2
    assert profiles["qwen3:8b"]["enabled"] == 1
    assert profiles["qwen3:8b"]["remote_status"] == "available"
    assert profiles["qwen3:8b"]["supports_tools"] == 1
    assert profiles["qwen3:8b"]["context_length"] == 32768
    assert profiles["unknown:latest"]["enabled"] == 0
    assert profiles["unknown:latest"]["remote_status"] == "available_unverified"
    assert profiles["removed:latest"]["enabled"] == 0
    assert profiles["removed:latest"]["remote_status"] == "missing"

    custom = update_model_profile(
        profiles["unknown:latest"]["id"],
        {
            "enabled": True,
            "supports_streaming": True,
            "supports_json_mode": True,
        },
    )
    route = UniqueModelRouter().resolve(
        ModelTaskRequest(
            task_id="custom-ollama-route",
            task_type="chapter_analysis",
            database_id="default",
            book_id="default",
            messages=({"role": "user", "content": "chapter"},),
            privacy_level="local_only",
            requires_json=True,
            requires_streaming=True,
            user_selected_model_id=custom["id"],
        )
    )
    assert route.status == RouteStatus.RESOLVED
    assert route.selected_model_profile_id == custom["id"]

    management.sync_ollama_model_profiles("local-main")
    preserved = next(
        item
        for item in management.list_model_profiles("local-main")
        if item["id"] == custom["id"]
    )
    assert preserved["enabled"] == 1
    assert preserved["supports_streaming"] == 1
    assert preserved["supports_json_mode"] == 1
    assert preserved["remote_status"] == "available_unverified"
    observation = next(
        item
        for item in list_model_observations("local-main")
        if item["model_name"] == "unknown:latest"
    )
    assert observation["discovery_status"] == "USER_CONFIGURED"
    assert observation["user_configured"] is True
    close_connection()


def test_digest_change_requires_reprobe_without_deleting_user_model(
    tmp_path,
    monkeypatch,
):
    setup_registry(tmp_path, monkeypatch)
    digest = {"value": "old-digest"}

    def fake_request(_provider, method, endpoint, payload=None):
        if method == "GET" and endpoint == "/api/tags":
            return {
                "models": [
                    {
                        "name": "qwen3:8b",
                        "digest": digest["value"],
                        "details": {
                            "family": "qwen3",
                            "parameter_size": "8B",
                            "quantization_level": "Q4_K_M",
                        },
                    }
                ]
            }
        if endpoint == "/api/show":
            return {
                "capabilities": ["completion", "tools"],
                "model_info": {"qwen3.context_length": 32768},
            }
        raise AssertionError((method, endpoint, payload))

    monkeypatch.setattr(management, "_request_json", fake_request)
    management.sync_ollama_model_profiles("local-main")
    first = list_model_observations("local-main")[0]
    assert first["discovery_status"] == "PROBED"
    assert first["digest"] == "old-digest"

    digest["value"] = "new-digest"
    management.sync_ollama_model_profiles("local-main")
    changed = list_model_observations("local-main")[0]
    profile = next(
        item
        for item in management.list_model_profiles("local-main")
        if item["provider_model_name"] == "qwen3:8b"
    )

    assert changed["discovery_status"] == "DIGEST_CHANGED"
    assert changed["previous_digest"] == "old-digest"
    assert changed["digest"] == "new-digest"
    assert profile["enabled"] == 1
    assert profile["remote_status"] == "available_unverified"

    mark_probe_result(profile["id"], verified=True)
    verified = list_model_observations("local-main")[0]
    assert verified["discovery_status"] == "VERIFIED"
    assert verified["previous_digest"] is None
    close_connection()


def test_completed_pull_creates_disabled_profile_from_show_capabilities(
    tmp_path, monkeypatch
):
    admin = setup_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(
        management,
        "_start_background_thread",
        lambda target, args, _name: target(*args),
    )
    monkeypatch.setattr(
        management.requests,
        "request",
        lambda *_args, **_kwargs: PullResponse(),
    )
    monkeypatch.setattr(
        management,
        "_request_json",
        lambda _provider, _method, endpoint, _payload=None: {
            "capabilities": ["completion"],
            "model_info": {"new.context_length": 8192},
        }
        if endpoint == "/api/show"
        else {},
    )

    status, body = request(
        "POST",
        "/api/ollama/models/pull",
        headers=admin,
        json_body={"provider_id": "local-main", "model": "new-model:1b"},
    )
    profile = next(
        item
        for item in management.list_model_profiles("local-main")
        if item["provider_model_name"] == "new-model:1b"
    )

    assert status == 202
    assert body["operation"]["status"] == "completed"
    assert body["operation"]["error_code"] is None
    assert profile["enabled"] == 0
    assert profile["remote_status"] == "available"
    assert profile["supports_streaming"] == 1
    assert profile["context_length"] == 8192
    close_connection()
