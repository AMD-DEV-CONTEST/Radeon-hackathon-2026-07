from pathlib import Path

import services.database_registry as registry
import services.ollama_management as management
from services.ollama_observability import list_external_resource_occupancy
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from tests.asgi_client import asgi_request


def request(method, path, *, json_body=None, headers=None):
    return asgi_request(app, method, path, json_body=json_body, headers=headers)


def setup_registry(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()


def test_status_distinguishes_installed_loaded_and_runtime_state(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(management, "find_ollama_executable", lambda: Path("C:/Ollama/ollama.exe"))

    def fake_request(_provider, _method, endpoint, _payload=None):
        if endpoint == "/api/version":
            return {"version": "0.32.0"}
        if endpoint == "/api/ps":
            return {
                "models": [
                    {
                        "name": "qwen3:8b",
                        "size": 8 * 1024 * 1024 * 1024,
                        "size_vram": 6 * 1024 * 1024 * 1024,
                        "context_length": 32768,
                        "expires_at": "2026-07-30T12:00:00Z",
                    }
                ]
            }
        return {
            "models": [
                {
                    "name": "qwen3:8b",
                    "size": 123,
                    "digest": "digest",
                    "details": {"family": "qwen3", "parameter_size": "8B"},
                },
                {"name": "deepseek-r1:7b", "size": 456, "details": {}},
            ]
        }

    monkeypatch.setattr(management, "_request_json", fake_request)
    admin = {"X-API-Key": ADMIN_API_KEY}
    assert request("GET", "/api/ollama/status")[0] == 401
    status, body = request("GET", "/api/ollama/status", headers=admin)

    assert status == 200
    assert body["installed"] is True
    assert body["running"] is True
    assert body["compatibility"] == "tested_target"
    assert body["installed_model_count"] == 2
    assert body["loaded_model_count"] == 1
    assert body["ownership"] == "external"
    assert body["runtime_id"].startswith("ollama:")
    assert body["models"][0]["loaded"] is True
    assert body["models"][0]["size_vram"] == 6 * 1024 * 1024 * 1024
    assert body["models"][0]["context_length"] == 32768
    assert body["models"][0]["discovery_status"] == "DETECTED"
    assert body["models"][1]["loaded"] is False
    assert body["external_occupancy"][0]["observed_vram_mb"] == 6144
    assert list_external_resource_occupancy()[0]["model_id"] == "qwen3:8b"

    observation_status, observations = request(
        "GET",
        "/api/ollama/observations",
        headers=admin,
    )
    assert observation_status == 200
    assert observations["runtimes"][0]["ownership"] == "external"
    assert observations["models"][0]["loaded"] is False
    assert observations["models"][1]["loaded"] is True
    close_connection()


def test_start_reports_missing_install_without_executing_shell(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(management, "find_ollama_executable", lambda: None)
    monkeypatch.setattr(
        management,
        "get_runtime_status",
        lambda _provider_id=None: {"running": False},
    )
    admin = {"X-API-Key": ADMIN_API_KEY}

    status, body = request("POST", "/api/ollama/start", headers=admin, json_body={})

    assert status == 409
    assert body["detail"]["code"] == "OLLAMA_NOT_INSTALLED"
    close_connection()


def test_external_runtime_cannot_be_stopped_by_aetherdb(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(management, "_MANAGED_PROCESS", None)
    admin = {"X-API-Key": ADMIN_API_KEY}

    status, body = request(
        "POST",
        "/api/ollama/stop",
        headers=admin,
        json_body={},
    )

    assert status == 409
    assert body["detail"]["code"] == "EXTERNAL_RUNTIME_CONTROL_BLOCKED"
    close_connection()


def test_managed_stop_only_terminates_the_owned_process(tmp_path, monkeypatch):
    setup_registry(tmp_path, monkeypatch)

    class ManagedProcess:
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            return 0

    process = ManagedProcess()
    monkeypatch.setattr(management, "_MANAGED_PROCESS", process)
    monkeypatch.setattr(
        management,
        "get_runtime_status",
        lambda _provider_id=None: {
            "running": False,
            "runtime_id": "ollama:test",
            "ownership": "external",
        },
    )

    result = management.stop_managed_runtime()

    assert result["stopped"] is True
    assert process.terminated is True
    assert management._MANAGED_PROCESS is None
    close_connection()
