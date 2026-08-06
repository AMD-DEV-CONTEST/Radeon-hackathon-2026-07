"""Admin API for provider connections and concrete model profiles."""

import sqlite3
import logging
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import require_admin
from app.models import (
    ModelProfileCreate,
    ModelProfileUpdate,
    ModelTaskBindingCreate,
    ModelTaskBindingUpdate,
    CloudProviderQuickSetup,
    ProviderCredentialUpdate,
    ProviderCreate,
    ProviderUpdate,
)
from services.audit_log import log_event
from services.db import get_db
from services.model_registry import (
    create_binding,
    create_model_profile,
    create_provider,
    delete_model_profile,
    delete_binding,
    delete_provider,
    get_model_profile,
    get_model_management_overview,
    get_provider,
    find_bindings,
    list_model_profiles,
    list_bindings,
    list_providers,
    mark_provider_model_available,
    update_model_profile,
    update_binding,
    update_provider,
)
from services.model_management import (
    ModelDiagnosticError,
    discover_model_names,
    list_test_results,
    test_model_profile,
    test_provider_connection,
)

router = APIRouter(tags=["model_registry"])
log = logging.getLogger(__name__)


def _audit(event_type: str, target: str):
    db = get_db()
    try:
        log_event(db, event_type, f"Model registry operation: {event_type}", target=target)
    finally:
        db.close()


def _conflict_or_invalid(exc: Exception):
    if isinstance(exc, sqlite3.IntegrityError):
        raise HTTPException(409, "Model registry constraint conflict")
    if isinstance(exc, KeyError):
        raise HTTPException(404, "Model registry item not found")
    raise HTTPException(400, "Invalid model registry request")


def _quick_provider_identity(base_url: str) -> tuple[str, str, str]:
    host = (urlparse(base_url).hostname or "cloud-model").lower()
    if host == "api.deepseek.com" or host.endswith(".deepseek.com"):
        return "deepseek", "DeepSeek", "deepseek"
    if host == "api.openai.com" or host.endswith(".openai.com"):
        return "openai", "OpenAI", "openai_compatible"
    label = host.removeprefix("api.").split(".")[0] or "cloud"
    base_id = re.sub(r"[^a-z0-9._-]+", "-", label).strip("-.") or "cloud"
    return f"{base_id}-cloud", label.title(), "openai_compatible"


def _available_provider_id(base_id: str, base_url: str) -> str:
    existing = next((item for item in list_providers() if item["base_url"] == base_url), None)
    if existing:
        return existing["id"]
    provider_id = base_id
    suffix = 2
    while get_provider(provider_id):
        provider_id = f"{base_id}-{suffix}"
        suffix += 1
    return provider_id


def _preferred_model_name(names: list[str], provider_type: str) -> str:
    preferred = [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-chat",
        "gpt-4.1-mini",
        "gpt-4o-mini",
    ]
    for name in preferred:
        if name in names:
            return name
    chat_names = [
        name for name in names
        if not any(marker in name.lower() for marker in ("embed", "rerank", "image", "audio", "tts", "whisper"))
    ]
    return (chat_names or names)[0]


def _chat_model_names(names: list[str]) -> list[str]:
    non_chat_markers = ("embed", "rerank", "image", "audio", "tts", "whisper")
    chat_names = [
        name
        for name in names
        if not any(marker in name.lower() for marker in non_chat_markers)
    ]
    return chat_names or [_preferred_model_name(names, "openai_compatible")]


def _provider_known_chat_models(provider_type: str, base_url: str) -> list[str]:
    host = (urlparse(base_url).hostname or "").lower()
    if provider_type == "deepseek" or host == "api.deepseek.com" or host.endswith(".deepseek.com"):
        return ["deepseek-v4-flash", "deepseek-v4-pro"]
    return []


def _merged_chat_model_names(discovered_names: list[str], provider_type: str, base_url: str) -> list[str]:
    names = _chat_model_names(discovered_names)
    for name in _provider_known_chat_models(provider_type, base_url):
        if name not in names:
            names.append(name)
    return names


def _ensure_default_bindings(provider_id: str, profile_id: str) -> list[dict]:
    created = []
    default_task_types = (
        "chapter_analysis",
        "chapter_extract",
        "changeset_build",
        "changeset_review",
        "creative_assist",
    )
    for task_type in default_task_types:
        if find_bindings("global", None, task_type):
            continue
        binding_id = f"auto_{provider_id}_{task_type}"[:128]
        suffix = 2
        while True:
            try:
                created.append(
                    create_binding(
                        {
                            "id": binding_id,
                            "scope_type": "global",
                            "scope_id": None,
                            "task_type": task_type,
                            "target_id": profile_id,
                            "priority": -100,
                            "enabled": True,
                        },
                        created_by="quick_setup",
                    )
                )
                break
            except sqlite3.IntegrityError:
                binding_id = f"auto_{provider_id}_{task_type}_{suffix}"[:128]
                suffix += 1
    return created


@router.get("/api/ai-management/overview")
def api_model_management_overview(_: None = Depends(require_admin)):
    return get_model_management_overview()


@router.get("/api/model-providers")
def api_list_providers(_: None = Depends(require_admin)):
    return {"providers": list_providers()}


@router.post("/api/model-providers/quick-setup")
def api_quick_setup_cloud_provider(
    payload: CloudProviderQuickSetup,
    _: None = Depends(require_admin),
):
    base_url = payload.base_url.rstrip("/")
    base_id, display_name, provider_type = _quick_provider_identity(base_url)
    provider_id = _available_provider_id(base_id, base_url)
    provider_data = {
        "id": provider_id,
        "display_name": display_name,
        "provider_type": provider_type,
        "base_url": base_url,
        "api_format": "openai_compatible",
        "credential_ref": f"secure:{provider_id}",
        "models_endpoint": "/models",
        "enabled": True,
        "supports_model_discovery": True,
    }
    secret = payload.api_key.get_secret_value()
    try:
        model_names = discover_model_names(provider_data, credential=secret)
    except ModelDiagnosticError as exc:
        raise HTTPException(
            400,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from exc

    from services.credential_store import CredentialStoreError, get_model_credential_store

    store = get_model_credential_store()
    created_provider = get_provider(provider_id) is None
    try:
        store.set_secret(provider_id, secret)
        if created_provider:
            provider = create_provider(provider_data)
        else:
            provider = update_provider(provider_id, provider_data)
        discovered_chat_models = _merged_chat_model_names(model_names, provider_type, base_url)
        preferred_model_name = _preferred_model_name(discovered_chat_models, provider_type)
        existing_profiles = {
            item["provider_model_name"]: item
            for item in list_model_profiles(provider_id)
        }
        profiles = []
        for model_name in discovered_chat_models:
            existing_profile = existing_profiles.get(model_name)
            if existing_profile:
                discovered_profile = update_model_profile(
                    existing_profile["id"],
                    {"enabled": True},
                )
            else:
                profile_suffix = re.sub(
                    r"[^a-z0-9._-]+",
                    "-",
                    model_name.lower(),
                ).strip("-.")
                profile_id = f"{provider_id}:{profile_suffix}"[:128]
                discovered_profile = create_model_profile({
                    "id": profile_id,
                    "provider_id": provider_id,
                    "provider_model_name": model_name,
                    "display_name": model_name,
                    "model_type": "chat",
                    "enabled": True,
                    "context_length": 65536,
                    "max_output_tokens": 4096,
                    "supports_streaming": True,
                    "supports_tools": False,
                    "supports_json_mode": True,
                    "cost_level": "unknown",
                    "privacy_level": "cloud_upload",
                })
            mark_provider_model_available(provider_id, discovered_profile["id"])
            profiles.append(discovered_profile)
        profile = next(
            item
            for item in profiles
            if item["provider_model_name"] == preferred_model_name
        )
        default_bindings = _ensure_default_bindings(provider_id, profile["id"])
    except CredentialStoreError as exc:
        raise HTTPException(
            503,
            detail={"code": "CREDENTIAL_STORE_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except Exception:
        if created_provider:
            try:
                delete_provider(provider_id)
                store.delete_secret(provider_id)
            except Exception:
                log.warning("Quick setup rollback was incomplete for %s", provider_id)
        raise
    _audit("model_provider.quick_setup", provider_id)
    return {
        "status": "ok",
        "provider": get_provider(provider_id),
        "model_profile": get_model_profile(profile["id"]),
        "model_profiles": [
            get_model_profile(item["id"])
            for item in profiles
        ],
        "discovered_model_count": len(model_names),
        "configured_chat_model_count": len(profiles),
        "default_bindings": default_bindings,
    }


@router.post("/api/model-providers")
def api_create_provider(payload: ProviderCreate, _: None = Depends(require_admin)):
    try:
        result = create_provider(payload.model_dump())
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    _audit("model_provider.create", payload.id)
    return {"status": "ok", "provider": result}


@router.get("/api/model-providers/{provider_id}")
def api_get_provider(provider_id: str, _: None = Depends(require_admin)):
    result = get_provider(provider_id)
    if not result:
        raise HTTPException(404, "Model provider not found")
    return {"provider": result}


@router.put("/api/model-providers/{provider_id}")
def api_update_provider(provider_id: str, payload: ProviderUpdate, _: None = Depends(require_admin)):
    try:
        result = update_provider(provider_id, payload.model_dump(exclude_unset=True))
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    _audit("model_provider.update", provider_id)
    return {"status": "ok", "provider": result}


@router.put("/api/model-providers/{provider_id}/credential")
def api_set_provider_credential(
    provider_id: str,
    payload: ProviderCredentialUpdate,
    _: None = Depends(require_admin),
):
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(404, "Model provider not found")
    try:
        from services.credential_store import CredentialStoreError, get_model_credential_store

        store = get_model_credential_store()
        store.set_secret(provider_id, payload.api_key.get_secret_value())
        update_provider(provider_id, {"credential_ref": f"secure:{provider_id}"})
    except CredentialStoreError as exc:
        raise HTTPException(
            503,
            detail={"code": "CREDENTIAL_STORE_UNAVAILABLE", "message": str(exc)},
        ) from exc
    _audit("model_provider.credential_update", provider_id)
    return {"status": "ok", "provider_id": provider_id, "credential_configured": True}


@router.delete("/api/model-providers/{provider_id}/credential")
def api_delete_provider_credential(provider_id: str, _: None = Depends(require_admin)):
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(404, "Model provider not found")
    try:
        from services.credential_store import CredentialStoreError, get_model_credential_store

        reference = provider.get("credential_ref") or ""
        if reference.startswith("secure:"):
            get_model_credential_store().delete_secret(reference.removeprefix("secure:"))
        update_provider(provider_id, {"credential_ref": None})
    except CredentialStoreError as exc:
        raise HTTPException(
            503,
            detail={"code": "CREDENTIAL_STORE_UNAVAILABLE", "message": str(exc)},
        ) from exc
    _audit("model_provider.credential_delete", provider_id)
    return {"status": "ok", "provider_id": provider_id, "credential_configured": False}


@router.delete("/api/model-providers/{provider_id}")
def api_delete_provider(provider_id: str, _: None = Depends(require_admin)):
    provider = get_provider(provider_id)
    try:
        delete_provider(provider_id)
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    reference = (provider or {}).get("credential_ref") or ""
    if reference.startswith("secure:"):
        try:
            from services.credential_store import get_model_credential_store

            get_model_credential_store().delete_secret(reference.removeprefix("secure:"))
        except Exception:
            log.warning("Could not remove credential for deleted provider %s", provider_id)
    _audit("model_provider.delete", provider_id)
    return {"status": "ok", "deleted": provider_id}


@router.post("/api/model-providers/{provider_id}/test-connection")
def api_test_provider_connection(provider_id: str, _: None = Depends(require_admin)):
    if not get_provider(provider_id):
        raise HTTPException(404, "Model provider not found")
    result = test_provider_connection(provider_id)
    _audit("model_provider.test", provider_id)
    return result


@router.get("/api/model-profiles")
def api_list_model_profiles(provider_id: str = None, _: None = Depends(require_admin)):
    return {"model_profiles": list_model_profiles(provider_id)}


@router.post("/api/model-profiles")
def api_create_model_profile(payload: ModelProfileCreate, _: None = Depends(require_admin)):
    try:
        result = create_model_profile(payload.model_dump())
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    _audit("model_profile.create", payload.id)
    return {"status": "ok", "model_profile": result}


@router.get("/api/model-profiles/{profile_id}")
def api_get_model_profile(profile_id: str, _: None = Depends(require_admin)):
    result = get_model_profile(profile_id)
    if not result:
        raise HTTPException(404, "Model profile not found")
    return {"model_profile": result}


@router.put("/api/model-profiles/{profile_id}")
def api_update_model_profile(profile_id: str, payload: ModelProfileUpdate, _: None = Depends(require_admin)):
    try:
        result = update_model_profile(profile_id, payload.model_dump(exclude_unset=True))
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    _audit("model_profile.update", profile_id)
    return {"status": "ok", "model_profile": result}


@router.delete("/api/model-profiles/{profile_id}")
def api_delete_model_profile(profile_id: str, _: None = Depends(require_admin)):
    try:
        delete_model_profile(profile_id)
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    _audit("model_profile.delete", profile_id)
    return {"status": "ok", "deleted": profile_id}


@router.post("/api/model-profiles/{profile_id}/test")
def api_test_model_profile(profile_id: str, _: None = Depends(require_admin)):
    if not get_model_profile(profile_id):
        raise HTTPException(404, "Model profile not found")
    result = test_model_profile(profile_id)
    _audit("model_profile.test", profile_id)
    return result


@router.get("/api/model-tests")
def api_list_model_tests(
    provider_id: str = None,
    model_profile_id: str = None,
    limit: int = 20,
    _: None = Depends(require_admin),
):
    return {
        "tests": list_test_results(
            provider_id=provider_id,
            model_profile_id=model_profile_id,
            limit=limit,
        )
    }


@router.get("/api/model-routing/bindings")
def api_list_bindings(_: None = Depends(require_admin)):
    return {"bindings": list_bindings()}


@router.post("/api/model-routing/bindings")
def api_create_binding(payload: ModelTaskBindingCreate, _: None = Depends(require_admin)):
    try:
        result = create_binding(payload.model_dump(), created_by="admin")
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    _audit("model_binding.create", payload.id)
    return {"status": "ok", "binding": result}


@router.put("/api/model-routing/bindings/{binding_id}")
def api_update_binding(binding_id: str, payload: ModelTaskBindingUpdate, _: None = Depends(require_admin)):
    try:
        result = update_binding(binding_id, payload.model_dump(exclude_unset=True))
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    _audit("model_binding.update", binding_id)
    return {"status": "ok", "binding": result}


@router.delete("/api/model-routing/bindings/{binding_id}")
def api_delete_binding(binding_id: str, _: None = Depends(require_admin)):
    try:
        delete_binding(binding_id)
    except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
        _conflict_or_invalid(exc)
    _audit("model_binding.delete", binding_id)
    return {"status": "ok", "deleted": binding_id}
