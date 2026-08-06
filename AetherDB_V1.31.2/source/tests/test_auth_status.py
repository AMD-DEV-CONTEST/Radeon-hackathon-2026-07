import json
import asyncio

import pytest

from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY, require_admin
from app.deployment import (
    Capability,
    DeploymentConfigurationError,
    DeploymentMode,
    DeploymentModeNotEnabled,
    get_deployment_mode,
    principal_for_credential_role,
)
from main import app
from tests.asgi_client import asgi_request


def _probe(headers=None):
    status, payload = asgi_request(app, "GET", "/api/auth/status", headers=headers)
    assert status == 200
    assert set(payload) == {
        "protocol_version",
        "status",
        "valid",
        "role",
        "deployment_mode",
        "deployment_enabled",
        "deployment_stage",
        "data_authority",
        "authenticated",
        "effective_role",
        "capabilities",
        "credential_status",
    }
    return payload


@pytest.fixture(autouse=True)
def local_desktop_mode(monkeypatch):
    monkeypatch.delenv("AETHERDB_DEPLOYMENT_MODE", raising=False)
    monkeypatch.delenv("AETHERDB_EXECUTION_MODE", raising=False)


def _anonymous_status(status):
    return {
        "protocol_version": "1.0",
        "status": status,
        "valid": False,
        "role": None,
        "deployment_mode": "local_desktop",
        "deployment_enabled": True,
        "deployment_stage": "enabled",
        "data_authority": "local",
        "authenticated": False,
        "effective_role": None,
        "capabilities": [],
        "credential_status": status,
    }


def test_auth_status_probe_reports_missing_and_invalid_without_echo():
    missing = _probe()
    assert missing == _anonymous_status("missing")

    supplied = "invalid-probe-credential-123"
    invalid = _probe({"x-api-key": supplied})
    assert invalid == _anonymous_status("invalid")
    assert supplied not in json.dumps(invalid)


def test_local_credentials_resolve_to_owner_capabilities_without_echo():
    user = _probe({"x-api-key": USER_API_KEY})
    admin = _probe({"x-api-key": ADMIN_API_KEY})

    for payload, legacy_role in ((user, "user"), (admin, "admin")):
        assert payload["status"] == payload["credential_status"] == "valid"
        assert payload["valid"] is payload["authenticated"] is True
        assert payload["role"] == legacy_role
        assert payload["deployment_mode"] == "local_desktop"
        assert payload["deployment_enabled"] is True
        assert payload["deployment_stage"] == "enabled"
        assert payload["data_authority"] == "local"
        assert payload["effective_role"] == "owner"
        assert Capability.MANAGE_MODELS.value in payload["capabilities"]
        assert Capability.MANAGE_SYSTEM.value in payload["capabilities"]
    serialized = json.dumps({"user": user, "admin": admin})
    assert USER_API_KEY not in serialized
    assert ADMIN_API_KEY not in serialized


def test_competition_environment_maps_to_local_owner(monkeypatch):
    monkeypatch.setenv("AETHERDB_EXECUTION_MODE", "competition")
    payload = _probe({"x-api-key": USER_API_KEY})
    assert payload["deployment_mode"] == "competition_local"
    assert payload["effective_role"] == "owner"
    assert payload["deployment_enabled"] is True
    assert payload["deployment_stage"] == "enabled"
    assert payload["data_authority"] == "local"


@pytest.mark.parametrize("mode", ["hosted_bridge", "full_server_deployment"])
def test_planned_server_modes_are_visible_but_not_enabled(monkeypatch, mode):
    monkeypatch.setenv("AETHERDB_DEPLOYMENT_MODE", mode)
    payload = _probe({"x-api-key": ADMIN_API_KEY})
    assert payload["deployment_mode"] == mode
    assert payload["deployment_enabled"] is False
    assert payload["deployment_stage"] == "planned"
    assert payload["data_authority"] == (
        "local" if mode == "hosted_bridge" else "server"
    )
    assert payload["authenticated"] is True
    assert payload["effective_role"] is None
    assert payload["capabilities"] == []
    with pytest.raises(DeploymentModeNotEnabled):
        principal_for_credential_role("admin")


def test_unknown_deployment_mode_fails_closed():
    with pytest.raises(DeploymentConfigurationError):
        get_deployment_mode({"AETHERDB_DEPLOYMENT_MODE": "hosted_server"})


def test_local_user_satisfies_legacy_admin_dependency_through_capability():
    principal = principal_for_credential_role("user", mode=DeploymentMode.LOCAL_DESKTOP)
    assert principal.effective_role.value == "owner"
    assert principal.has(Capability.MANAGE_SYSTEM)
    asyncio.run(require_admin(principal))
