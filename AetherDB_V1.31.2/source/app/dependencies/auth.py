"""API key authentication.

V1.31.2 security policy:
- Accept API keys from the X-API-Key header only.
- Reject query-string keys to prevent URL, browser history, and log leakage.
- Load keys from ADMIN_API_KEY / USER_API_KEY, legacy NOVEL_* env vars, or
  .api_keys.json; generate local development keys if none exist.
"""

import json
import os
import secrets

from fastapi import Depends, HTTPException, Request

from app.config import get_runtime_path
from app.deployment import (
    Capability,
    DeploymentModeNotEnabled,
    EffectivePrincipal,
    get_deployment_profile,
    principal_for_credential_role,
)

# Local generated keys always belong to the writable runtime root.
_KEY_FILE = str(get_runtime_path(".api_keys.json"))


def _load_or_generate_keys() -> tuple[str, str]:
    """????????????????????????????

    ???????? > ???? > ????? > ????+????
    ?????? ADMIN ???????USER ??????????
    """
    admin_key = (
        os.environ.get("ADMIN_API_KEY")
        or os.environ.get("NOVEL_ADMIN_KEY")
    )
    user_key = (
        os.environ.get("USER_API_KEY")
        or os.environ.get("NOVEL_API_KEY")
    )

    # ???????????? -> ??????????
    if admin_key and user_key:
        return admin_key, user_key

    # ???????????????
    key_file = os.path.abspath(_KEY_FILE)
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not admin_key:
                admin_key = data.get("admin")
            if not user_key:
                user_key = data.get("user")
        except (json.JSONDecodeError, OSError):
            pass

    # ???? -> ????
    if not admin_key:
        admin_key = "nvk_admin_" + secrets.token_hex(16)
    if not user_key:
        user_key = "nvk_" + secrets.token_hex(16)

    # ?????????????????????????????
    try:
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        with open(key_file, "w", encoding="utf-8") as f:
            json.dump({"admin": admin_key, "user": user_key}, f, indent=2)
        try:
            os.chmod(key_file, 0o600)
        except (NotImplementedError, OSError):
            pass
    except OSError:
        pass

    return admin_key, user_key


ADMIN_API_KEY, USER_API_KEY = _load_or_generate_keys()


VALID_KEYS: dict[str, str] = {
    ADMIN_API_KEY: "admin",
    USER_API_KEY: "user",
}


def _desktop_owner_token() -> str | None:
    """Load the process-scoped Tauri owner token without persisting it."""
    token = os.environ.get("AETHERDB_DESKTOP_OWNER_TOKEN", "")
    if not token:
        return None
    if (
        token != token.strip()
        or not token.startswith("aether_owner_")
        or not 45 <= len(token) <= 128
    ):
        raise RuntimeError("AETHERDB_DESKTOP_OWNER_TOKEN is malformed")
    return token


DESKTOP_OWNER_TOKEN = _desktop_owner_token()
if DESKTOP_OWNER_TOKEN:
    VALID_KEYS[DESKTOP_OWNER_TOKEN] = "admin"


def _credential_role(provided: str) -> str | None:
    for candidate, candidate_role in VALID_KEYS.items():
        if secrets.compare_digest(provided, candidate):
            return candidate_role
    return None


def probe_api_key_status(request: Request) -> dict:
    """Return a non-sensitive authentication status for startup probes."""
    provided = request.headers.get("x-api-key", "")
    role = _credential_role(provided) if provided else None
    credential_status = "valid" if role is not None else ("invalid" if provided else "missing")
    profile = get_deployment_profile()
    principal = None
    if role is not None and profile.enabled:
        principal = principal_for_credential_role(role, mode=profile.mode)
    return {
        "protocol_version": "1.0",
        "status": credential_status,
        "valid": role is not None,
        "role": role,
        "deployment_mode": profile.mode.value,
        "deployment_enabled": profile.enabled,
        "deployment_stage": profile.stage.value,
        "data_authority": profile.authority,
        "authenticated": role is not None,
        "effective_role": principal.effective_role.value if principal else None,
        "capabilities": principal.public_capabilities() if principal else [],
        "credential_status": credential_status,
    }


def resolve_api_key(request: Request) -> str | None:
    """Resolve API key from the X-API-Key header only."""
    header_key = request.headers.get("x-api-key")
    if header_key and _credential_role(header_key) is not None:
        return header_key
    return None


async def get_effective_principal(request: Request) -> EffectivePrincipal:
    """Authenticate the request and resolve deployment-aware capabilities."""
    api_key = resolve_api_key(request)
    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "A valid X-API-Key is required"},
        )
    role = _credential_role(api_key)
    try:
        return principal_for_credential_role(role)
    except DeploymentModeNotEnabled as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DEPLOYMENT_MODE_NOT_ENABLED",
                "message": "The selected deployment mode is not enabled",
                "deployment_mode": exc.mode.value,
            },
        ) from exc


async def get_current_user_role(
    principal: EffectivePrincipal = Depends(get_effective_principal),
) -> str:
    """Return the legacy credential role for route compatibility."""
    return principal.credential_role


def require_capability(capability: Capability | str):
    requested = capability if isinstance(capability, Capability) else Capability(capability)

    async def dependency(
        principal: EffectivePrincipal = Depends(get_effective_principal),
    ) -> EffectivePrincipal:
        if not principal.has(requested):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "CAPABILITY_REQUIRED",
                    "message": "The current principal lacks the required capability",
                    "capability": requested.value,
                },
            )
        return principal

    dependency.__name__ = f"require_capability_{requested.value}"
    return dependency


async def require_admin(
    principal: EffectivePrincipal = Depends(get_effective_principal),
) -> None:
    """Compatibility dependency backed by the capability model."""
    if not principal.has(Capability.MANAGE_SYSTEM):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CAPABILITY_REQUIRED",
                "message": "Management capability is required",
                "capability": Capability.MANAGE_SYSTEM.value,
            },
        )
