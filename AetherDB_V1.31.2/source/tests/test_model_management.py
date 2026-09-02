import socket
import sqlite3

import yaml

import services.database_registry as registry
import services.llm_engine.manager as llm_manager
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from tests.asgi_client import asgi_request


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"

    def json(self):
        return self._payload


def request(method, path, *, json_body=None, headers=None):
    return asgi_request(app, method, path, json_body=json_body, headers=headers)


def setup_registry(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()
    admin = {"X-API-Key": ADMIN_API_KEY}
    provider = {
        "id": "local-main",
        "display_name": "Local runtime",
        "provider_type": "local_ollama",
        "base_url": "http://127.0.0.1:11434",
        "api_format": "ollama_chat",
        "models_endpoint": "/api/tags",
        "supports_model_discovery": True,
    }
    model = {
        "id": "local-main:qwen",
        "provider_id": "local-main",
        "provider_model_name": "qwen2.5:7b",
        "display_name": "Qwen 2.5 7B",
        "model_type": "text",
        "supports_streaming": True,
        "privacy_level": "local_only",
    }
    assert request("POST", "/api/model-providers", headers=admin, json_body=provider)[0] == 200
    assert request("POST", "/api/model-profiles", headers=admin, json_body=model)[0] == 200
    return admin


def test_analysis_preference_is_admin_managed_and_persisted_locally(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    config_path = tmp_path / "runtime" / "config.local.yaml"
    config_path.write_text(
        yaml.safe_dump({"llm": {"import_analysis": {"default_mode": "ask"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_manager, "get_runtime_config_path", lambda: config_path)
    monkeypatch.setattr(llm_manager, "get_writable_config_path", lambda: config_path)

    assert request("GET", "/api/ai/analysis-preferences")[0] == 401
    status, initial = request("GET", "/api/ai/analysis-preferences", headers=admin)
    assert status == 200
    assert initial["default_mode"] == "ask"
    assert initial["local_rules_available"] is True

    status, updated = request(
        "PUT",
        "/api/ai/analysis-preferences",
        headers=admin,
        json_body={"default_mode": "local_rules"},
    )
    assert status == 200
    assert updated["default_mode"] == "local_rules"
    persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert persisted["llm"]["import_analysis"]["default_mode"] == "local_rules"
    close_connection()


def test_provider_and_model_diagnostics_persist_safe_summaries(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/api/tags"):
            return FakeResponse({"models": [{"name": "qwen2.5:7b"}]})
        return FakeResponse({"message": {"role": "assistant", "content": "OK"}})

    monkeypatch.setattr("services.model_management.requests.request", fake_request)

    assert request("POST", "/api/model-providers/local-main/test-connection")[0] == 401
    status, provider_result = request(
        "POST", "/api/model-providers/local-main/test-connection", headers=admin
    )
    assert status == 200
    assert provider_result["status"] == "passed"
    assert provider_result["capabilities"]["reported_model_count"] == 1

    status, model_result = request(
        "POST", "/api/model-profiles/local-main:qwen/test", headers=admin
    )
    assert status == 200
    assert model_result["status"] == "passed"
    assert "content" not in str(model_result).lower()
    assert calls[-1][2]["json"]["model"] == "qwen2.5:7b"
    assert calls[-1][2]["allow_redirects"] is False

    status, history = request("GET", "/api/model-tests", headers=admin)
    assert status == 200
    assert len(history["tests"]) == 2
    assert all("OK" not in str(item) for item in history["tests"])
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        provider_health = conn.execute(
            "SELECT health_status FROM model_providers WHERE id='local-main'"
        ).fetchone()[0]
        model_health = conn.execute(
            "SELECT health_status,remote_status FROM model_profiles WHERE id='local-main:qwen'"
        ).fetchone()
    assert provider_health == "healthy"
    assert model_health == ("healthy", "available")
    close_connection()


def test_failed_diagnostic_records_only_normalized_error(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)

    def failed_request(*_args, **_kwargs):
        return FakeResponse({"raw": "private provider body"}, status_code=401)

    monkeypatch.setattr("services.model_management.requests.request", failed_request)
    status, body = request(
        "POST", "/api/model-providers/local-main/test-connection", headers=admin
    )
    assert status == 200
    assert body["status"] == "failed"
    assert body["error"]["code"] == "AUTH_FAILED"
    assert "private provider body" not in str(body)
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        stored = conn.execute(
            "SELECT error_code,error_message FROM model_test_results"
        ).fetchone()
    assert stored == ("AUTH_FAILED", "Provider authentication failed")
    close_connection()


def test_local_provider_cannot_rebind_to_public_address(tmp_path, monkeypatch):
    admin = setup_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "services.model_management.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 11434))],
    )
    status, body = request(
        "POST", "/api/model-providers/local-main/test-connection", headers=admin
    )
    assert status == 200
    assert body["status"] == "failed"
    assert body["error"]["code"] == "TARGET_BLOCKED"
    close_connection()
