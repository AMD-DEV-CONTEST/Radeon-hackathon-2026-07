import sqlite3

import services.database_registry as registry
import services.credential_store as credential_store
import services.model_management as model_management
import api.model_registry as model_registry_api
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from services.model_registry import (
    create_model_profile,
    create_provider,
    get_provider,
    list_eligible_model_profiles,
    list_bindings,
    list_model_profiles,
    record_model_usage,
    reconcile_known_cloud_provider_defaults,
)
from services.model_execution import ModelTaskRequest
from services.model_routing import UniqueModelRouter
from services.model_routing import CredentialResolver
from tests.asgi_client import asgi_request


def request(method, path, *, json_body=None, headers=None):
    return asgi_request(app, method, path, json_body=json_body, headers=headers)


def test_provider_and_model_profile_crud_is_separated(tmp_path, monkeypatch):
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
        "credential_ref": "env:LOCAL_MODEL_TOKEN",
        "models_endpoint": "/api/tags",
        "supports_model_discovery": True,
    }

    assert request("GET", "/api/model-providers")[0] == 401
    status, body = request("POST", "/api/model-providers", headers=admin, json_body=provider)
    assert status == 200
    assert body["provider"]["credential_ref"] == "env:LOCAL_MODEL_TOKEN"

    model_one = {
        "id": "local-main:qwen",
        "provider_id": "local-main",
        "provider_model_name": "qwen2.5:7b",
        "display_name": "Qwen 2.5 7B",
        "model_type": "text",
        "supports_streaming": True,
        "supports_json_mode": True,
        "privacy_level": "local_only",
    }
    model_two = {
        **model_one,
        "id": "local-main:coder",
        "provider_model_name": "qwen2.5-coder:7b",
        "display_name": "Qwen Coder 7B",
    }
    assert request("POST", "/api/model-profiles", headers=admin, json_body=model_one)[0] == 200
    assert request("POST", "/api/model-profiles", headers=admin, json_body=model_two)[0] == 200
    assert len(list_eligible_model_profiles()) == 2

    status, _ = request(
        "PUT",
        "/api/model-providers/local-main",
        headers=admin,
        json_body={"enabled": False},
    )
    assert status == 200
    assert list_eligible_model_profiles() == []

    assert request("DELETE", "/api/model-profiles/local-main:qwen", headers=admin)[0] == 200
    assert get_provider("local-main") is not None
    assert request("DELETE", "/api/model-providers/local-main", headers=admin)[0] == 409

    status, body = request(
        "POST",
        "/api/model-providers/local-main/test-connection",
        headers=admin,
    )
    assert status == 200
    assert body["status"] == "failed"
    assert body["error"]["code"] == "CREDENTIAL_UNAVAILABLE"
    close_connection()


def test_provider_api_rejects_plaintext_key_and_remote_ssrf_target(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()
    admin = {"X-API-Key": ADMIN_API_KEY}

    payload = {
        "id": "cloud-main",
        "display_name": "Cloud",
        "provider_type": "openai_compatible",
        "base_url": "http://127.0.0.1:9000",
        "api_format": "openai_chat",
        "api_key": "must-not-be-accepted",
    }
    assert request("POST", "/api/model-providers", headers=admin, json_body=payload)[0] == 422
    payload.pop("api_key")
    assert request("POST", "/api/model-providers", headers=admin, json_body=payload)[0] == 400

    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(model_providers)")}
    assert "api_key" not in columns
    assert "password" not in columns
    close_connection()


def test_provider_credential_uses_separate_encrypted_store(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()

    class ReversibleTestProtector:
        def protect(self, value):
            return b"test-cipher:" + value[::-1]

        def unprotect(self, value):
            assert value.startswith(b"test-cipher:")
            return value.removeprefix(b"test-cipher:")[::-1]

    store_path = runtime_root / "app_data" / "model_credentials.json"
    store = credential_store.ModelCredentialStore(store_path, ReversibleTestProtector())
    monkeypatch.setattr(credential_store, "get_model_credential_store", lambda: store)
    admin = {"X-API-Key": ADMIN_API_KEY}
    provider = {
        "id": "cloud-secure",
        "display_name": "Cloud Secure",
        "provider_type": "openai_compatible",
        "base_url": "https://api.example.com/v1",
        "api_format": "openai_compatible",
    }
    assert request("POST", "/api/model-providers", headers=admin, json_body=provider)[0] == 200

    secret = "test-provider-key-value"
    status, body = request(
        "PUT",
        "/api/model-providers/cloud-secure/credential",
        headers=admin,
        json_body={"api_key": secret},
    )
    assert status == 200
    assert body == {
        "status": "ok",
        "provider_id": "cloud-secure",
        "credential_configured": True,
    }
    assert secret not in store_path.read_text(encoding="utf-8")
    assert get_provider("cloud-secure")["credential_ref"] == "secure:cloud-secure"
    assert CredentialResolver(env={}, secure_store=store).resolve("secure:cloud-secure") == secret

    status, body = request(
        "DELETE",
        "/api/model-providers/cloud-secure/credential",
        headers=admin,
    )
    assert status == 200
    assert body["credential_configured"] is False
    assert get_provider("cloud-secure")["credential_ref"] is None
    assert not store.has_secret("cloud-secure")
    close_connection()


def test_deepseek_diagnostic_allows_reserved_proxy_address_but_not_generic_remote(monkeypatch):
    monkeypatch.setattr(
        model_management.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("198.18.0.47", 443))],
    )
    model_management._validate_runtime_target({
        "provider_type": "deepseek",
        "base_url": "https://api.deepseek.com",
    })
    try:
        model_management._validate_runtime_target({
            "provider_type": "openai_compatible",
            "base_url": "https://api.example.com",
        })
    except model_management.ModelDiagnosticError as exc:
        assert exc.code == "TARGET_BLOCKED"
    else:
        raise AssertionError("Generic remote provider must not bypass target validation")
    monkeypatch.setattr(
        model_management.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    try:
        model_management._validate_runtime_target({
            "provider_type": "deepseek",
            "base_url": "https://api.deepseek.com",
        })
    except model_management.ModelDiagnosticError as exc:
        assert exc.code == "TARGET_BLOCKED"
    else:
        raise AssertionError("Trusted provider host must not resolve to loopback")


def test_quick_cloud_setup_needs_only_url_and_key(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()

    class ReversibleTestProtector:
        def protect(self, value):
            return b"cipher:" + value[::-1]

        def unprotect(self, value):
            return value.removeprefix(b"cipher:")[::-1]

    store = credential_store.ModelCredentialStore(
        runtime_root / "app_data" / "model_credentials.json",
        ReversibleTestProtector(),
    )
    monkeypatch.setattr(credential_store, "get_model_credential_store", lambda: store)
    monkeypatch.setattr(
        model_registry_api,
        "discover_model_names",
        lambda provider, credential=None: ["deepseek-v4-flash", "deepseek-v4-pro"],
    )
    admin = {"X-API-Key": ADMIN_API_KEY}
    secret = "quick-setup-provider-key"
    assert request(
        "POST",
        "/api/model-providers/quick-setup",
        json_body={"base_url": "https://api.deepseek.com", "api_key": secret},
    )[0] == 401
    status, body = request(
        "POST",
        "/api/model-providers/quick-setup",
        headers=admin,
        json_body={"base_url": "https://api.deepseek.com", "api_key": secret},
    )
    assert status == 200
    assert body["provider"]["provider_type"] == "deepseek"
    assert body["provider"]["credential_ref"] == "secure:deepseek"
    assert body["model_profile"]["provider_model_name"] == "deepseek-v4-flash"
    assert body["model_profile"]["health_status"] == "healthy"
    assert body["discovered_model_count"] == 2
    assert body["configured_chat_model_count"] == 2
    assert {
        item["provider_model_name"]
        for item in body["model_profiles"]
    } == {"deepseek-v4-flash", "deepseek-v4-pro"}
    assert secret not in str(body)
    assert CredentialResolver(env={}, secure_store=store).resolve("secure:deepseek") == secret
    close_connection()


def test_quick_setup_adds_known_deepseek_models_and_default_routes(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()

    class ReversibleTestProtector:
        def protect(self, value):
            return b"cipher:" + value[::-1]

        def unprotect(self, value):
            return value.removeprefix(b"cipher:")[::-1]

    store = credential_store.ModelCredentialStore(
        runtime_root / "app_data" / "model_credentials.json",
        ReversibleTestProtector(),
    )
    monkeypatch.setattr(credential_store, "get_model_credential_store", lambda: store)
    monkeypatch.setattr(
        model_registry_api,
        "discover_model_names",
        lambda provider, credential=None: ["deepseek-v4-flash"],
    )
    admin = {"X-API-Key": ADMIN_API_KEY}
    status, body = request(
        "POST",
        "/api/model-providers/quick-setup",
        headers=admin,
        json_body={"base_url": "https://api.deepseek.com", "api_key": "quick-setup-provider-key"},
    )
    assert status == 200
    assert body["discovered_model_count"] == 1
    assert body["configured_chat_model_count"] == 2
    assert {
        item["provider_model_name"]
        for item in body["model_profiles"]
    } == {"deepseek-v4-flash", "deepseek-v4-pro"}
    assert {item["task_type"] for item in body["default_bindings"]} >= {
        "chapter_analysis",
        "chapter_extract",
        "changeset_build",
    }

    route = UniqueModelRouter().resolve(
        ModelTaskRequest(
            task_id="deepseek-analysis-route",
            task_type="chapter_analysis",
            database_id="default",
            book_id="default",
            messages=({"role": "user", "content": "青石村村长将受伤的修士带回村中。"},),
            requires_json=True,
            requires_streaming=False,
        )
    )
    assert route.selected_model_profile_id == body["model_profile"]["id"]
    close_connection()


def test_reconcile_repairs_existing_deepseek_provider_defaults(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(runtime_root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(runtime_root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()

    create_provider(
        {
            "id": "deepseek",
            "display_name": "DeepSeek",
            "provider_type": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "api_format": "openai_compatible",
            "credential_ref": "secure:deepseek",
            "models_endpoint": "/models",
            "enabled": True,
            "supports_model_discovery": True,
        }
    )
    create_model_profile(
        {
            "id": "deepseek:deepseek-v4-flash",
            "provider_id": "deepseek",
            "provider_model_name": "deepseek-v4-flash",
            "display_name": "deepseek-v4-flash",
            "model_type": "chat",
            "enabled": True,
            "supports_streaming": True,
            "supports_json_mode": True,
            "privacy_level": "cloud_upload",
        }
    )

    result = reconcile_known_cloud_provider_defaults()

    assert [item["provider_model_name"] for item in result["added_profiles"]] == [
        "deepseek-v4-pro"
    ]
    assert {
        item["provider_model_name"]
        for item in list_model_profiles("deepseek")
    } == {"deepseek-v4-flash", "deepseek-v4-pro"}
    assert {item["task_type"] for item in list_bindings()} >= {
        "chapter_analysis",
        "chapter_extract",
        "changeset_build",
    }
    route = UniqueModelRouter().resolve(
        ModelTaskRequest(
            task_id="deepseek-existing-route",
            task_type="chapter_analysis",
            database_id="default",
            book_id="default",
            messages=({"role": "user", "content": "青石村出现新的线索。"},),
            requires_json=True,
            requires_streaming=False,
        )
    )
    assert route.selected_model_profile_id == "deepseek:deepseek-v4-flash"
    close_connection()


def test_quick_cloud_setup_normalizes_full_openai_compatible_endpoints():
    from app.models import CloudProviderQuickSetup

    deepseek = CloudProviderQuickSetup(
        base_url="  https://api.deepseek.com/v1/chat/completions/  ",
        api_key="test-provider-key",
    )
    generic = CloudProviderQuickSetup(
        base_url="https://models.example.com/openai/v1/models",
        api_key="test-provider-key",
    )

    assert deepseek.base_url == "https://api.deepseek.com/v1"
    assert generic.base_url == "https://models.example.com/openai/v1"


def test_ai_management_overview_is_hierarchical_and_credential_free(tmp_path, monkeypatch):
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
        "credential_ref": "env:LOCAL_MODEL_TOKEN",
    }
    model = {
        "id": "local-main:qwen",
        "provider_id": "local-main",
        "provider_model_name": "qwen2.5:7b",
        "display_name": "Qwen 2.5 7B",
        "model_type": "text",
        "supports_streaming": True,
        "supports_json_mode": True,
        "privacy_level": "local_only",
    }
    assert request("POST", "/api/model-providers", headers=admin, json_body=provider)[0] == 200
    assert request("POST", "/api/model-profiles", headers=admin, json_body=model)[0] == 200
    assert request(
        "POST",
        "/api/model-routing/bindings",
        headers=admin,
        json_body={
            "id": "global-analysis",
            "scope_type": "global",
            "task_type": "chapter_analysis",
            "target_id": "local-main:qwen",
        },
    )[0] == 200
    record_model_usage(
        task_id="task-overview",
        task_type="chapter_analysis",
        provider_id="local-main",
        model_profile_id="local-main:qwen",
        provider_model_name="qwen2.5:7b",
        route_reason="global_binding",
        usage={"input_tokens": 10, "output_tokens": 4},
        success=True,
        attempt_id="attempt-1",
    )

    assert request("GET", "/api/ai-management/overview")[0] == 401
    status, body = request("GET", "/api/ai-management/overview", headers=admin)

    assert status == 200
    assert body["protocol_version"] == "1.0"
    assert body["summary"] == {
        "provider_count": 1,
        "enabled_provider_count": 1,
        "model_count": 1,
        "available_model_count": 1,
        "binding_count": 1,
        "enabled_binding_count": 1,
        "usage_calls_30d": 1,
    }
    nested_model = body["providers"][0]["models"][0]
    assert nested_model["id"] == "local-main:qwen"
    assert nested_model["capabilities"]["supports_streaming"] is True
    assert nested_model["usage_30d"]["calls"] == 1
    assert body["bindings"][0]["target_available"] is True
    serialized = str(body).lower()
    assert "credential_ref" not in serialized
    assert "local_model_token" not in serialized
    close_connection()
