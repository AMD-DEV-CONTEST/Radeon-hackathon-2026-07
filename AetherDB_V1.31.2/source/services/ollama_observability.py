"""Persistent, read-only observations of independently owned Ollama runtimes."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from services.database_registry import _get_registry_conn
from services.model_runtime.contracts import ExternalResourceOccupancy


OLLAMA_MODEL_STATES = {
    "DETECTED",
    "USER_CONFIGURED",
    "PROBED",
    "VERIFIED",
    "UNVERIFIED",
    "INCOMPATIBLE",
    "UNAVAILABLE",
    "DIGEST_CHANGED",
    "DISABLED_BY_USER",
}


def runtime_id_for(provider: dict) -> str:
    identity = provider.get("id") or provider["base_url"].rstrip("/")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"ollama:{digest}"


def _clean_text(value: Any, limit: int = 256) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return "".join(character for character in text if ord(character) >= 32)[:limit]


def _safe_capabilities(payload: dict | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    values = payload.get("capabilities")
    if not isinstance(values, list):
        return []
    return sorted(
        {
            value.strip().lower()
            for value in values
            if isinstance(value, str)
            and 0 < len(value.strip()) <= 64
            and all(ord(character) >= 32 for character in value)
        }
    )


def _context_length(payload: dict | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    direct = payload.get("context_length")
    if isinstance(direct, int) and 0 < direct <= 10_000_000:
        return direct
    model_info = payload.get("model_info")
    values = [
        value
        for key, value in (model_info.items() if isinstance(model_info, dict) else ())
        if str(key).endswith(".context_length")
        and isinstance(value, int)
        and 0 < value <= 10_000_000
    ]
    return max(values) if values else None


def _details(*payloads: dict | None) -> dict:
    merged = {}
    for payload in payloads:
        details = payload.get("details") if isinstance(payload, dict) else None
        if isinstance(details, dict):
            merged.update(details)
    return merged


def _serialize_runtime(row: dict) -> dict:
    for key in ("installed", "running", "api_compatible"):
        row[key] = bool(row.get(key))
    return row


def _serialize_model(row: dict) -> dict:
    row["user_configured"] = bool(row.get("user_configured"))
    row["installed"] = bool(row.get("installed"))
    row["loaded"] = bool(row.get("loaded"))
    try:
        row["reported_capabilities"] = json.loads(
            row.pop("reported_capabilities_json") or "[]"
        )
    except (TypeError, ValueError):
        row["reported_capabilities"] = []
    return row


def record_runtime_observation(
    provider: dict,
    *,
    ownership: str,
    state: str,
    installed: bool,
    running: bool,
    api_compatible: bool,
    version: str | None,
    compatibility: str,
    error: dict | None = None,
) -> dict:
    if ownership not in {"aetherdb_managed", "external"}:
        raise ValueError("Invalid Ollama runtime ownership")
    runtime_id = runtime_id_for(provider)
    conn = _get_registry_conn()
    try:
        conn.execute(
            "INSERT INTO ollama_runtime_observations "
            "(runtime_id,provider_id,base_url,ownership,state,installed,running,"
            "api_compatible,version,compatibility,error_code,error_message) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(runtime_id) DO UPDATE SET "
            "provider_id=excluded.provider_id,base_url=excluded.base_url,"
            "ownership=excluded.ownership,state=excluded.state,"
            "installed=excluded.installed,running=excluded.running,"
            "api_compatible=excluded.api_compatible,version=excluded.version,"
            "compatibility=excluded.compatibility,error_code=excluded.error_code,"
            "error_message=excluded.error_message,last_seen_at=CURRENT_TIMESTAMP",
            (
                runtime_id,
                provider.get("id"),
                provider["base_url"],
                ownership,
                state,
                int(installed),
                int(running),
                int(api_compatible),
                version,
                compatibility,
                (error or {}).get("code"),
                (error or {}).get("message"),
            ),
        )
        if not running:
            conn.execute(
                "UPDATE ollama_model_observations SET loaded=0,"
                "discovery_status='UNAVAILABLE',last_seen_at=CURRENT_TIMESTAMP "
                "WHERE runtime_id=?",
                (runtime_id,),
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ollama_runtime_observations WHERE runtime_id=?",
            (runtime_id,),
        ).fetchone()
        return _serialize_runtime(dict(row))
    finally:
        conn.close()


def _next_discovery_status(
    existing: dict | None,
    *,
    digest: str | None,
    profile: dict | None,
    capabilities: list[str],
) -> tuple[str, str | None, bool]:
    previous_digest = existing.get("previous_digest") if existing else None
    existing_digest = existing.get("digest") if existing else None
    changed = bool(existing_digest and digest and existing_digest != digest)
    user_configured = bool(existing and existing.get("user_configured"))
    if changed:
        return "DIGEST_CHANGED", existing_digest, user_configured
    if existing and existing.get("discovery_status") == "DIGEST_CHANGED":
        return "DIGEST_CHANGED", previous_digest, user_configured
    if profile and profile.get("health_status") == "healthy":
        return "VERIFIED", previous_digest, user_configured
    if user_configured:
        return (
            "USER_CONFIGURED"
            if profile and profile.get("enabled")
            else "DISABLED_BY_USER",
            previous_digest,
            True,
        )
    if existing and existing.get("discovery_status") in {
        "PROBED",
        "VERIFIED",
        "UNVERIFIED",
    } and not capabilities:
        return existing["discovery_status"], previous_digest, False
    if capabilities:
        return "PROBED", previous_digest, False
    if profile:
        return "UNVERIFIED", previous_digest, False
    return "DETECTED", previous_digest, False


def record_model_observation(
    provider: dict,
    model_name: str,
    *,
    tag_payload: dict | None = None,
    loaded_payload: dict | None = None,
    show_payload: dict | None = None,
    profile: dict | None = None,
) -> dict:
    runtime_id = runtime_id_for(provider)
    tag_payload = tag_payload if isinstance(tag_payload, dict) else {}
    loaded_payload = loaded_payload if isinstance(loaded_payload, dict) else None
    details = _details(tag_payload, loaded_payload, show_payload)
    digest = _clean_text(
        tag_payload.get("digest") or (loaded_payload or {}).get("digest"),
        160,
    )
    capabilities = _safe_capabilities(show_payload)
    conn = _get_registry_conn()
    try:
        old_row = conn.execute(
            "SELECT * FROM ollama_model_observations "
            "WHERE runtime_id=? AND model_name=?",
            (runtime_id, model_name),
        ).fetchone()
        existing = dict(old_row) if old_row else None
        status, previous_digest, user_configured = _next_discovery_status(
            existing,
            digest=digest,
            profile=profile,
            capabilities=capabilities,
        )
        loaded = (
            bool(loaded_payload)
            if loaded_payload is not None
            else bool(existing and existing.get("loaded"))
        )
        size_vram = (
            int((loaded_payload or {}).get("size_vram") or 0)
            if loaded_payload is not None
            else int((existing or {}).get("size_vram_bytes") or 0)
        )
        context_length = (
            _context_length(loaded_payload)
            or _context_length(show_payload)
            or (profile or {}).get("context_length")
            or (existing or {}).get("context_length")
        )
        conn.execute(
            "INSERT INTO ollama_model_observations "
            "(runtime_id,model_name,provider_id,model_profile_id,digest,"
            "previous_digest,discovery_status,user_configured,installed,loaded,"
            "size_bytes,size_vram_bytes,context_length,expires_at,model_format,"
            "model_family,parameter_size,quantization_level,"
            "reported_capabilities_json,source) "
            "VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(runtime_id,model_name) DO UPDATE SET "
            "provider_id=excluded.provider_id,"
            "model_profile_id=COALESCE(excluded.model_profile_id,model_profile_id),"
            "digest=COALESCE(excluded.digest,digest),"
            "previous_digest=excluded.previous_digest,"
            "discovery_status=excluded.discovery_status,"
            "user_configured=excluded.user_configured,installed=1,"
            "loaded=excluded.loaded,size_bytes=excluded.size_bytes,"
            "size_vram_bytes=excluded.size_vram_bytes,"
            "context_length=COALESCE(excluded.context_length,context_length),"
            "expires_at=excluded.expires_at,"
            "model_format=COALESCE(excluded.model_format,model_format),"
            "model_family=COALESCE(excluded.model_family,model_family),"
            "parameter_size=COALESCE(excluded.parameter_size,parameter_size),"
            "quantization_level=COALESCE(excluded.quantization_level,quantization_level),"
            "reported_capabilities_json=CASE "
            "WHEN excluded.reported_capabilities_json='[]' "
            "THEN reported_capabilities_json ELSE excluded.reported_capabilities_json END,"
            "last_seen_at=CURRENT_TIMESTAMP",
            (
                runtime_id,
                model_name,
                provider.get("id"),
                (profile or {}).get("id"),
                digest,
                previous_digest,
                status,
                int(user_configured),
                int(loaded),
                int(
                    tag_payload.get("size")
                    or (loaded_payload or {}).get("size")
                    or 0
                ),
                size_vram,
                context_length,
                _clean_text((loaded_payload or {}).get("expires_at"), 160),
                _clean_text(details.get("format"), 80),
                _clean_text(details.get("family"), 120),
                _clean_text(details.get("parameter_size"), 80),
                _clean_text(details.get("quantization_level"), 80),
                json.dumps(capabilities, ensure_ascii=True),
                "ollama_reported",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ollama_model_observations "
            "WHERE runtime_id=? AND model_name=?",
            (runtime_id, model_name),
        ).fetchone()
        return _serialize_model(dict(row))
    finally:
        conn.close()


def mark_unseen_models(
    provider: dict,
    observed_names: list[str],
    *,
    complete: bool,
) -> None:
    if not complete:
        return
    runtime_id = runtime_id_for(provider)
    conn = _get_registry_conn()
    try:
        if observed_names:
            placeholders = ",".join("?" for _ in observed_names)
            conn.execute(
                "UPDATE ollama_model_observations SET installed=0,loaded=0,"
                "discovery_status='UNAVAILABLE',last_seen_at=CURRENT_TIMESTAMP "
                f"WHERE runtime_id=? AND model_name NOT IN ({placeholders})",
                (runtime_id, *observed_names),
            )
        else:
            conn.execute(
                "UPDATE ollama_model_observations SET installed=0,loaded=0,"
                "discovery_status='UNAVAILABLE',last_seen_at=CURRENT_TIMESTAMP "
                "WHERE runtime_id=?",
                (runtime_id,),
            )
        conn.commit()
    finally:
        conn.close()


def mark_user_configured(profile_id: str) -> None:
    conn = _get_registry_conn()
    try:
        profile = conn.execute(
            "SELECT enabled FROM model_profiles WHERE id=?",
            (profile_id,),
        ).fetchone()
        if profile is None:
            return
        conn.execute(
            "UPDATE ollama_model_observations SET user_configured=1,"
            "discovery_status=CASE WHEN discovery_status='DIGEST_CHANGED' "
            "THEN discovery_status WHEN ?=1 THEN 'USER_CONFIGURED' "
            "ELSE 'DISABLED_BY_USER' END,last_seen_at=CURRENT_TIMESTAMP "
            "WHERE model_profile_id=?",
            (int(profile["enabled"]), profile_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_probe_result(
    profile_id: str,
    *,
    verified: bool,
    error_code: str | None = None,
) -> None:
    state = (
        "VERIFIED"
        if verified
        else "INCOMPATIBLE"
        if error_code in {"INVALID_RESPONSE", "UNSUPPORTED_TEST"}
        else "UNAVAILABLE"
    )
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE ollama_model_observations SET discovery_status=?,"
            "previous_digest=CASE WHEN ?='VERIFIED' THEN NULL ELSE previous_digest END,"
            "last_seen_at=CURRENT_TIMESTAMP WHERE model_profile_id=?",
            (state, state, profile_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_runtime_observations(provider_id: str | None = None) -> list[dict]:
    conn = _get_registry_conn()
    try:
        if provider_id:
            rows = conn.execute(
                "SELECT * FROM ollama_runtime_observations "
                "WHERE provider_id=? ORDER BY last_seen_at DESC",
                (provider_id,),
            )
        else:
            rows = conn.execute(
                "SELECT * FROM ollama_runtime_observations ORDER BY last_seen_at DESC"
            )
        return [_serialize_runtime(dict(row)) for row in rows]
    finally:
        conn.close()


def list_model_observations(
    provider_id: str | None = None,
    *,
    runtime_id: str | None = None,
) -> list[dict]:
    conditions = []
    values = []
    if provider_id:
        conditions.append("provider_id=?")
        values.append(provider_id)
    if runtime_id:
        conditions.append("runtime_id=?")
        values.append(runtime_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ollama_model_observations "
            f"{where} ORDER BY model_name",
            values,
        )
        return [_serialize_model(dict(row)) for row in rows]
    finally:
        conn.close()


def list_external_resource_occupancy() -> list[dict]:
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT m.*,r.ownership,r.running FROM ollama_model_observations m "
            "JOIN ollama_runtime_observations r ON r.runtime_id=m.runtime_id "
            "WHERE r.ownership='external' AND r.running=1 AND m.loaded=1"
        ).fetchall()
    finally:
        conn.close()
    now = datetime.now(timezone.utc)
    items = []
    for raw in rows:
        row = dict(raw)
        try:
            observed_at = datetime.fromisoformat(
                str(row["last_seen_at"]).replace("Z", "+00:00")
            )
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if (now - observed_at).total_seconds() > 300:
            continue
        size_vram_mb = math.ceil(
            int(row["size_vram_bytes"] or 0) / (1024 * 1024)
        )
        size_ram_mb = math.ceil(
            max(
                0,
                int(row["size_bytes"] or 0)
                - int(row["size_vram_bytes"] or 0),
            )
            / (1024 * 1024)
        )
        items.append(
            ExternalResourceOccupancy(
                occupancy_id=hashlib.sha256(
                    f"{row['runtime_id']}\0{row['model_name']}".encode("utf-8")
                ).hexdigest()[:32],
                source="external_runtime",
                runtime_id=row["runtime_id"],
                model_id=row["model_name"],
                device_id="external:unattributed",
                observed_vram_mb=size_vram_mb,
                observed_ram_mb=size_ram_mb,
                confidence="reported",
                observed_at=observed_at.isoformat(),
            ).model_dump(mode="json")
        )
    return items
