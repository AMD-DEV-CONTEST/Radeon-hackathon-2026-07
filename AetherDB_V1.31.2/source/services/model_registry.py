"""Registry repository for provider connections and concrete model profiles."""

import ipaddress
import re
import sqlite3
import uuid
from urllib.parse import urlparse

from services.database_registry import _get_registry_conn


LOCAL_PROVIDER_TYPES = {"local", "local_ollama", "ollama"}
SYSTEM_PROVIDER_TYPES = {"aetherdb_worker"}
ALWAYS_BLOCKED_HOSTS = {"metadata.google.internal", "169.254.169.254"}
DEFAULT_CHAT_TASK_TYPES = (
    "chapter_analysis",
    "chapter_extract",
    "changeset_build",
    "changeset_review",
    "creative_assist",
)

PROVIDER_MUTABLE_FIELDS = {
    "display_name",
    "provider_type",
    "base_url",
    "api_format",
    "credential_ref",
    "models_endpoint",
    "enabled",
    "supports_model_discovery",
}
MODEL_MUTABLE_FIELDS = {
    "provider_model_name",
    "display_name",
    "model_type",
    "enabled",
    "context_length",
    "max_output_tokens",
    "supports_streaming",
    "supports_tools",
    "supports_json_mode",
    "cost_level",
    "privacy_level",
}


def _validate_provider_target(base_url: str, provider_type: str):
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Invalid provider URL")
    host = parsed.hostname.lower()
    allow_local = provider_type in LOCAL_PROVIDER_TYPES
    if host in ALWAYS_BLOCKED_HOSTS:
        raise ValueError("Provider target is blocked")
    if host == "localhost" and not allow_local:
        raise ValueError("Remote providers cannot target local or metadata hosts")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        raise ValueError("Provider target address is blocked")
    if allow_local and not (address.is_private or address.is_loopback):
        raise ValueError("Local providers must target loopback or private addresses")
    if (address.is_private or address.is_loopback) and not allow_local:
        raise ValueError("Remote providers cannot target non-public addresses")


def _row(row):
    return dict(row) if row else None


def list_providers():
    conn = _get_registry_conn()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM model_providers ORDER BY display_name, id")]
    finally:
        conn.close()


def get_provider(provider_id: str):
    conn = _get_registry_conn()
    try:
        return _row(conn.execute("SELECT * FROM model_providers WHERE id=?", (provider_id,)).fetchone())
    finally:
        conn.close()


def create_provider(data: dict):
    if data["provider_type"] in SYSTEM_PROVIDER_TYPES:
        raise ValueError("System model providers are managed by AetherDB")
    _validate_provider_target(data["base_url"], data["provider_type"])
    conn = _get_registry_conn()
    try:
        conn.execute(
            "INSERT INTO model_providers "
            "(id,display_name,provider_type,base_url,api_format,credential_ref,models_endpoint,enabled,supports_model_discovery) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                data["id"], data["display_name"], data["provider_type"], data["base_url"],
                data["api_format"], data.get("credential_ref"), data.get("models_endpoint"),
                int(data.get("enabled", True)), int(data.get("supports_model_discovery", False)),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_provider(data["id"])


def update_provider(provider_id: str, updates: dict):
    current = get_provider(provider_id)
    if not current:
        raise KeyError(provider_id)
    if current["provider_type"] in SYSTEM_PROVIDER_TYPES:
        raise ValueError("System model providers are read-only")
    clean = {
        key: value
        for key, value in updates.items()
        if key in PROVIDER_MUTABLE_FIELDS and (value is not None or key == "credential_ref")
    }
    provider_type = clean.get("provider_type", current["provider_type"])
    base_url = clean.get("base_url", current["base_url"])
    _validate_provider_target(base_url, provider_type)
    if not clean:
        return current
    columns = ",".join(f"{key}=?" for key in clean)
    values = [int(value) if isinstance(value, bool) else value for value in clean.values()]
    conn = _get_registry_conn()
    try:
        health_reset = ",health_status='unknown'" if "credential_ref" in clean else ""
        conn.execute(
            f"UPDATE model_providers SET {columns}{health_reset},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (*values, provider_id),
        )
        if "credential_ref" in clean:
            conn.execute(
                "UPDATE model_profiles SET health_status='unknown',remote_status='unknown',"
                "updated_at=CURRENT_TIMESTAMP WHERE provider_id=?",
                (provider_id,),
            )
        conn.commit()
    finally:
        conn.close()
    return get_provider(provider_id)


def delete_provider(provider_id: str):
    current = get_provider(provider_id)
    if current and current["provider_type"] in SYSTEM_PROVIDER_TYPES:
        raise ValueError("System model providers are read-only")
    conn = _get_registry_conn()
    try:
        cursor = conn.execute("DELETE FROM model_providers WHERE id=?", (provider_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(provider_id)
    finally:
        conn.close()


def list_model_profiles(provider_id: str | None = None):
    conn = _get_registry_conn()
    try:
        if provider_id:
            rows = conn.execute(
                "SELECT * FROM model_profiles WHERE provider_id=? ORDER BY display_name, id",
                (provider_id,),
            )
        else:
            rows = conn.execute("SELECT * FROM model_profiles ORDER BY display_name, id")
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_eligible_model_profiles():
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT m.* FROM model_profiles m JOIN model_providers p ON p.id=m.provider_id "
            "WHERE m.enabled=1 AND p.enabled=1 ORDER BY m.display_name, m.id"
        )
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_model_profile(profile_id: str):
    conn = _get_registry_conn()
    try:
        return _row(conn.execute("SELECT * FROM model_profiles WHERE id=?", (profile_id,)).fetchone())
    finally:
        conn.close()


def get_model_management_overview():
    """Return the credential-free hierarchy consumed by AI management clients."""
    conn = _get_registry_conn()
    try:
        providers = [
            dict(row)
            for row in conn.execute(
                "SELECT id,display_name,provider_type,enabled,health_status "
                "FROM model_providers ORDER BY display_name,id"
            )
        ]
        profiles = [
            dict(row)
            for row in conn.execute(
                "SELECT id,provider_id,provider_model_name,display_name,model_type,enabled,"
                "health_status,remote_status,supports_streaming,supports_tools,supports_json_mode,"
                "cost_level,privacy_level FROM model_profiles ORDER BY display_name,id"
            )
        ]
        bindings = [
            dict(row)
            for row in conn.execute(
                "SELECT id,scope_type,scope_id,task_type,target_id,priority,enabled "
                "FROM model_task_bindings ORDER BY task_type,scope_type,priority DESC,id"
            )
        ]
        usage_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT model_profile_id,COUNT(*) AS calls,"
                "SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS successful_calls,"
                "COALESCE(SUM(input_tokens),0) AS input_tokens,"
                "COALESCE(SUM(output_tokens),0) AS output_tokens,"
                "MAX(created_at) AS last_used_at FROM model_usage_log "
                "WHERE created_at >= datetime('now','-30 days') GROUP BY model_profile_id"
            )
        ]
    finally:
        conn.close()

    usage_by_model = {row["model_profile_id"]: row for row in usage_rows}
    profiles_by_provider = {provider["id"]: [] for provider in providers}
    profile_enabled = {}
    for profile in profiles:
        provider = next(
            (item for item in providers if item["id"] == profile["provider_id"]),
            None,
        )
        provider_is_enabled = bool(provider and provider["enabled"])
        model_is_enabled = bool(profile["enabled"])
        profile["enabled"] = model_is_enabled
        profile["available"] = (
            provider_is_enabled
            and model_is_enabled
            and profile["health_status"] != "unhealthy"
            and profile["remote_status"] not in {"missing", "unavailable"}
        )
        profile["capabilities"] = {
            "supports_streaming": bool(profile.pop("supports_streaming")),
            "supports_tools": bool(profile.pop("supports_tools")),
            "supports_json": bool(profile.pop("supports_json_mode")),
            "supports_embedding": profile["model_type"] == "embedding",
        }
        profile["usage_30d"] = usage_by_model.get(
            profile["id"],
            {
                "model_profile_id": profile["id"],
                "calls": 0,
                "successful_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "last_used_at": None,
            },
        )
        profile_enabled[profile["id"]] = profile["available"]
        profiles_by_provider.setdefault(profile["provider_id"], []).append(profile)

    for provider in providers:
        provider["enabled"] = bool(provider["enabled"])
        provider["models"] = profiles_by_provider.get(provider["id"], [])
        provider["model_count"] = len(provider["models"])
        provider["available_model_count"] = sum(
            1 for profile in provider["models"] if profile["available"]
        )

    for binding in bindings:
        binding["enabled"] = bool(binding["enabled"])
        binding["target_available"] = profile_enabled.get(binding["target_id"], False)

    from services.model_execution.task_types import task_type_catalog

    return {
        "protocol_version": "1.0",
        "summary": {
            "provider_count": len(providers),
            "enabled_provider_count": sum(1 for item in providers if item["enabled"]),
            "model_count": len(profiles),
            "available_model_count": sum(1 for item in profiles if item["available"]),
            "binding_count": len(bindings),
            "enabled_binding_count": sum(1 for item in bindings if item["enabled"]),
            "usage_calls_30d": sum(int(item["calls"]) for item in usage_rows),
        },
        "providers": providers,
        "bindings": bindings,
        "task_types": task_type_catalog(),
    }


def known_chat_model_names(provider: dict) -> list[str]:
    host = (urlparse(provider.get("base_url") or "").hostname or "").lower()
    provider_type = str(provider.get("provider_type") or "").lower()
    if provider_type == "deepseek" or host == "api.deepseek.com" or host.endswith(".deepseek.com"):
        return ["deepseek-v4-flash", "deepseek-v4-pro"]
    return []


def preferred_chat_profile_id(provider_id: str) -> str | None:
    profiles = [
        profile
        for profile in list_model_profiles(provider_id)
        if profile["enabled"] and profile["model_type"] in {"chat", "text"}
    ]
    if not profiles:
        return None
    preferred_order = (
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-chat",
        "gpt-4.1-mini",
        "gpt-4o-mini",
    )
    for name in preferred_order:
        for profile in profiles:
            if profile["provider_model_name"] == name:
                return profile["id"]
    return profiles[0]["id"]


def ensure_default_task_bindings(provider_id: str, profile_id: str) -> list[dict]:
    created = []
    for task_type in DEFAULT_CHAT_TASK_TYPES:
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
                        created_by="system_reconcile",
                    )
                )
                break
            except sqlite3.IntegrityError:
                binding_id = f"auto_{provider_id}_{task_type}_{suffix}"[:128]
                suffix += 1
    return created


def reconcile_known_cloud_provider_defaults() -> dict:
    """Repair safe local registry metadata for already configured cloud providers."""
    added_profiles = []
    enabled_profiles = []
    created_bindings = []
    for provider in list_providers():
        if not provider["enabled"]:
            continue
        known_names = known_chat_model_names(provider)
        if not known_names:
            continue
        profiles_by_name = {
            profile["provider_model_name"]: profile
            for profile in list_model_profiles(provider["id"])
        }
        for model_name in known_names:
            existing = profiles_by_name.get(model_name)
            if existing:
                if not existing["enabled"]:
                    enabled_profiles.append(update_model_profile(existing["id"], {"enabled": True}))
                continue
            profile_suffix = re.sub(r"[^a-z0-9._-]+", "-", model_name.lower()).strip("-.")
            profile_id = f"{provider['id']}:{profile_suffix}"[:128]
            added_profiles.append(
                create_model_profile(
                    {
                        "id": profile_id,
                        "provider_id": provider["id"],
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
                    }
                )
            )
        preferred = preferred_chat_profile_id(provider["id"])
        if preferred:
            created_bindings.extend(ensure_default_task_bindings(provider["id"], preferred))
    return {
        "added_profiles": added_profiles,
        "enabled_profiles": enabled_profiles,
        "created_bindings": created_bindings,
    }


def create_model_profile(data: dict):
    provider = get_provider(data["provider_id"])
    if not provider:
        raise KeyError(data["provider_id"])
    if provider["provider_type"] in SYSTEM_PROVIDER_TYPES:
        raise ValueError("System model profiles are managed by AetherDB")
    conn = _get_registry_conn()
    try:
        conn.execute(
            "INSERT INTO model_profiles "
            "(id,provider_id,provider_model_name,display_name,model_type,enabled,context_length,max_output_tokens,"
            "supports_streaming,supports_tools,supports_json_mode,cost_level,privacy_level) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["id"], data["provider_id"], data["provider_model_name"], data["display_name"],
                data["model_type"], int(data.get("enabled", True)), data.get("context_length"),
                data.get("max_output_tokens"), int(data.get("supports_streaming", False)),
                int(data.get("supports_tools", False)), int(data.get("supports_json_mode", False)),
                data.get("cost_level", "unknown"), data.get("privacy_level", "cloud_upload"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_model_profile(data["id"])


def update_model_profile(profile_id: str, updates: dict):
    current = get_model_profile(profile_id)
    if not current:
        raise KeyError(profile_id)
    provider = get_provider(current["provider_id"])
    if provider and provider["provider_type"] in SYSTEM_PROVIDER_TYPES:
        raise ValueError("System model profiles are read-only")
    clean = {key: value for key, value in updates.items() if key in MODEL_MUTABLE_FIELDS and value is not None}
    if not clean:
        return current
    columns = ",".join(f"{key}=?" for key in clean)
    values = [int(value) if isinstance(value, bool) else value for value in clean.values()]
    conn = _get_registry_conn()
    try:
        conn.execute(
            f"UPDATE model_profiles SET {columns},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (*values, profile_id),
        )
        conn.commit()
    finally:
        conn.close()
    provider = get_provider(current["provider_id"])
    if provider and provider["provider_type"] in LOCAL_PROVIDER_TYPES:
        from services.ollama_observability import mark_user_configured

        mark_user_configured(profile_id)
    return get_model_profile(profile_id)


def delete_model_profile(profile_id: str):
    current = get_model_profile(profile_id)
    provider = get_provider(current["provider_id"]) if current else None
    if provider and provider["provider_type"] in SYSTEM_PROVIDER_TYPES:
        raise ValueError("System model profiles are read-only")
    conn = _get_registry_conn()
    try:
        cursor = conn.execute("DELETE FROM model_profiles WHERE id=?", (profile_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(profile_id)
    finally:
        conn.close()


def mark_provider_model_available(provider_id: str, profile_id: str):
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE model_providers SET health_status='healthy',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (provider_id,),
        )
        conn.execute(
            "UPDATE model_profiles SET health_status='healthy',remote_status='available',"
            "updated_at=CURRENT_TIMESTAMP WHERE id=? AND provider_id=?",
            (profile_id, provider_id),
        )
        conn.commit()
    finally:
        conn.close()


def _validate_binding_scope(scope_type: str, scope_id: str | None):
    if scope_type == "global":
        if scope_id not in (None, ""):
            raise ValueError("Global binding cannot have scope_id")
        return None
    if not scope_id:
        raise ValueError("Scoped binding requires scope_id")
    if scope_type == "database":
        from services.database_registry import get_database

        if not get_database(scope_id):
            raise ValueError("Database scope not found")
    elif scope_type == "book":
        if "/" not in scope_id:
            raise ValueError("Book scope must be database_id/book_id")
        database_id, book_id = scope_id.split("/", 1)
        from services.database_registry import get_db_path

        with sqlite3.connect(get_db_path(database_id)) as conn:
            if not conn.execute("SELECT 1 FROM books WHERE book_id=?", (book_id,)).fetchone():
                raise ValueError("Book scope not found")
    elif scope_type != "session":
        raise ValueError("Unsupported binding scope")
    return scope_id


def list_bindings():
    conn = _get_registry_conn()
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM model_task_bindings ORDER BY task_type, scope_type, priority DESC, id"
            )
        ]
    finally:
        conn.close()


def find_bindings(scope_type: str, scope_id: str | None, task_type: str):
    conn = _get_registry_conn()
    try:
        if scope_id is None:
            rows = conn.execute(
                "SELECT * FROM model_task_bindings WHERE enabled=1 AND scope_type=? "
                "AND scope_id IS NULL AND task_type=? ORDER BY priority DESC, id",
                (scope_type, task_type),
            )
        else:
            rows = conn.execute(
                "SELECT * FROM model_task_bindings WHERE enabled=1 AND scope_type=? "
                "AND scope_id=? AND task_type=? ORDER BY priority DESC, id",
                (scope_type, scope_id, task_type),
            )
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_binding(data: dict, created_by: str = "admin"):
    scope_id = _validate_binding_scope(data["scope_type"], data.get("scope_id"))
    if not get_model_profile(data["target_id"]):
        raise KeyError(data["target_id"])
    conn = _get_registry_conn()
    try:
        conn.execute(
            "INSERT INTO model_task_bindings "
            "(id,scope_type,scope_id,task_type,target_type,target_id,priority,enabled,created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                data["id"], data["scope_type"], scope_id, data["task_type"], "model_profile",
                data["target_id"], data.get("priority", 0), int(data.get("enabled", True)), created_by,
            ),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM model_task_bindings WHERE id=?", (data["id"],)).fetchone())
    finally:
        conn.close()


def update_binding(binding_id: str, updates: dict):
    clean = {key: value for key, value in updates.items() if key in {"target_id", "priority", "enabled"} and value is not None}
    if "target_id" in clean and not get_model_profile(clean["target_id"]):
        raise KeyError(clean["target_id"])
    conn = _get_registry_conn()
    try:
        current = conn.execute("SELECT * FROM model_task_bindings WHERE id=?", (binding_id,)).fetchone()
        if not current:
            raise KeyError(binding_id)
        if clean:
            columns = ",".join(f"{key}=?" for key in clean)
            values = [int(value) if isinstance(value, bool) else value for value in clean.values()]
            conn.execute(
                f"UPDATE model_task_bindings SET {columns},updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (*values, binding_id),
            )
            conn.commit()
        return dict(conn.execute("SELECT * FROM model_task_bindings WHERE id=?", (binding_id,)).fetchone())
    finally:
        conn.close()


def delete_binding(binding_id: str):
    conn = _get_registry_conn()
    try:
        cursor = conn.execute("DELETE FROM model_task_bindings WHERE id=?", (binding_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(binding_id)
    finally:
        conn.close()


def record_model_usage(
    *, task_id: str, task_type: str, provider_id: str, model_profile_id: str,
    provider_model_name: str, route_reason: str, usage: dict, success: bool,
    attempt_id: str, fallback_used: bool = False, error_code: str | None = None,
):
    conn = _get_registry_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO model_usage_log "
            "(id,task_id,attempt_id,task_type,provider_id,model_profile_id,provider_model_name,"
            "route_reason,input_tokens,output_tokens,fallback_used,success,error_code) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex, task_id, attempt_id, task_type, provider_id, model_profile_id,
                provider_model_name, route_reason, int(usage.get("input_tokens") or 0),
                int(usage.get("output_tokens") or 0), int(fallback_used), int(success), error_code,
            ),
        )
        conn.commit()
    finally:
        conn.close()
