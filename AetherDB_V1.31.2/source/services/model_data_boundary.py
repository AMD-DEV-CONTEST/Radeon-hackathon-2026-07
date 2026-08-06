"""Server-owned model data policies and short-lived cloud-send manifests."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Mapping, Sequence

from services.database_registry import _get_registry_conn
from services.db import get_db
from services.model_registry import LOCAL_PROVIDER_TYPES, get_model_profile, get_provider


DEFAULT_MANIFEST_TTL_SECONDS = 600
MAX_MANIFEST_TTL_SECONDS = 900
DEFAULT_MAX_PAYLOAD_BYTES = 2 * 1024 * 1024


class PermissionTier(str, Enum):
    A_PURE_CREATION = "A_PURE_CREATION"
    B_CONTEXT_ENHANCED = "B_CONTEXT_ENHANCED"
    C_RESTRICTED_TOOLS = "C_RESTRICTED_TOOLS"


class ModelDataBoundaryError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def is_cloud_provider(provider: Mapping[str, object]) -> bool:
    return str(provider.get("provider_type", "")).lower() not in LOCAL_PROVIDER_TYPES


def _default_policy(model_profile_id: str, provider: Mapping[str, object]) -> dict:
    local = not is_cloud_provider(provider)
    return {
        "model_profile_id": model_profile_id,
        "permission_tier": (
            PermissionTier.B_CONTEXT_ENHANCED.value
            if local
            else PermissionTier.A_PURE_CREATION.value
        ),
        "allow_original_text": True,
        "allow_approved_context": local,
        "allow_selected_media": local,
        "max_payload_bytes": DEFAULT_MAX_PAYLOAD_BYTES,
        "updated_by": "system-default",
        "is_default": True,
    }


def get_model_data_policy(model_profile_id: str) -> dict:
    profile = get_model_profile(model_profile_id)
    if not profile:
        raise ModelDataBoundaryError("MODEL_NOT_FOUND", "Model profile was not found.", 404)
    provider = get_provider(profile["provider_id"])
    if not provider:
        raise ModelDataBoundaryError("PROVIDER_NOT_FOUND", "Model provider was not found.", 404)
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT * FROM model_data_policies WHERE model_profile_id=?",
            (model_profile_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return _default_policy(model_profile_id, provider)
    result = dict(row)
    for key in (
        "allow_original_text",
        "allow_approved_context",
        "allow_selected_media",
    ):
        result[key] = bool(result[key])
    result["is_default"] = False
    return result


def set_model_data_policy(
    model_profile_id: str,
    *,
    permission_tier: str,
    allow_original_text: bool,
    allow_approved_context: bool,
    allow_selected_media: bool,
    max_payload_bytes: int,
    updated_by: str,
) -> dict:
    try:
        tier = PermissionTier(permission_tier)
    except ValueError as exc:
        raise ModelDataBoundaryError(
            "INVALID_PERMISSION_TIER",
            "Unknown model data permission tier.",
            400,
        ) from exc
    if not get_model_profile(model_profile_id):
        raise ModelDataBoundaryError("MODEL_NOT_FOUND", "Model profile was not found.", 404)
    if tier is PermissionTier.A_PURE_CREATION and (
        allow_approved_context or allow_selected_media
    ):
        raise ModelDataBoundaryError(
            "POLICY_TIER_CONFLICT",
            "Tier A cannot receive approved context or selected media.",
            400,
        )
    bounded_size = max(1024, min(int(max_payload_bytes), 16 * 1024 * 1024))
    conn = _get_registry_conn()
    try:
        conn.execute(
            """INSERT INTO model_data_policies(
                   model_profile_id,permission_tier,allow_original_text,
                   allow_approved_context,allow_selected_media,max_payload_bytes,updated_by
               ) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(model_profile_id) DO UPDATE SET
                   permission_tier=excluded.permission_tier,
                   allow_original_text=excluded.allow_original_text,
                   allow_approved_context=excluded.allow_approved_context,
                   allow_selected_media=excluded.allow_selected_media,
                   max_payload_bytes=excluded.max_payload_bytes,
                   updated_by=excluded.updated_by,
                   updated_at=CURRENT_TIMESTAMP""",
            (
                model_profile_id,
                tier.value,
                int(allow_original_text),
                int(allow_approved_context),
                int(allow_selected_media),
                bounded_size,
                updated_by,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_model_data_policy(model_profile_id)


def validate_selected_assets(
    database_id: str,
    book_id: str | None,
    asset_ids: Iterable[str],
) -> tuple[str, ...]:
    unique_ids = tuple(dict.fromkeys(str(item) for item in asset_ids))
    if not unique_ids:
        return ()
    if not book_id:
        raise ModelDataBoundaryError(
            "ASSET_BOOK_SCOPE_REQUIRED",
            "Selected media requires a server-validated book scope.",
            400,
        )
    placeholders = ",".join("?" for _ in unique_ids)
    db = get_db(database_id)
    try:
        rows = db.execute(
            f"""SELECT asset_id FROM media_assets
                  WHERE database_id=? AND book_id=?
                    AND lifecycle_status IN ('approved','archived')
                    AND asset_id IN ({placeholders})""",
            (database_id, book_id, *unique_ids),
        ).fetchall()
    finally:
        db.close()
    found = {row["asset_id"] for row in rows}
    if found != set(unique_ids):
        raise ModelDataBoundaryError(
            "ASSET_SCOPE_INVALID",
            "One or more selected media assets are outside the approved server scope.",
            409,
        )
    return tuple(sorted(found))


def enforce_model_data_policy(
    model_profile_id: str,
    *,
    contains_original_text: bool,
    approved_context_ids: Sequence[str],
    selected_asset_ids: Sequence[str],
    estimated_payload_size: int,
) -> dict:
    policy = get_model_data_policy(model_profile_id)
    if contains_original_text and not policy["allow_original_text"]:
        raise ModelDataBoundaryError(
            "ORIGINAL_TEXT_BLOCKED",
            "The selected model is not permitted to receive original text.",
        )
    if approved_context_ids and not policy["allow_approved_context"]:
        raise ModelDataBoundaryError(
            "APPROVED_CONTEXT_BLOCKED",
            "The selected model is not permitted to receive approved context.",
        )
    if selected_asset_ids and not policy["allow_selected_media"]:
        raise ModelDataBoundaryError(
            "SELECTED_MEDIA_BLOCKED",
            "The selected model is not permitted to receive selected media.",
        )
    if estimated_payload_size > int(policy["max_payload_bytes"]):
        raise ModelDataBoundaryError(
            "MODEL_PAYLOAD_TOO_LARGE",
            "The server-generated payload exceeds the model data policy.",
            413,
        )
    return policy


def payload_fingerprint(
    *,
    task_id: str,
    task_type: str,
    database_id: str,
    book_id: str | None,
    chapter_id: str | None,
    messages: Sequence[Mapping[str, object]],
    approved_context_ids: Sequence[str],
    selected_asset_ids: Sequence[str],
) -> str:
    return content_hash(
        {
            "task_id": task_id,
            "task_type": task_type,
            "database_id": database_id,
            "book_id": book_id,
            "chapter_id": chapter_id,
            "messages": list(messages),
            "approved_context_ids": sorted(approved_context_ids),
            "selected_asset_ids": sorted(selected_asset_ids),
        }
    )


def selected_text_fingerprint(messages: Sequence[Mapping[str, object]]) -> str:
    return content_hash(list(messages))


def estimate_payload_size(
    messages: Sequence[Mapping[str, object]],
    approved_context_ids: Sequence[str],
    selected_asset_ids: Sequence[str],
) -> int:
    return len(
        _canonical_bytes(
            {
                "messages": list(messages),
                "approved_context_ids": sorted(approved_context_ids),
                "selected_asset_ids": sorted(selected_asset_ids),
            }
        )
    )


def _public_manifest(row: Mapping[str, object]) -> dict:
    result = dict(row)
    result["approved_context_ids"] = json.loads(
        str(result.pop("approved_context_ids_json"))
    )
    result["selected_asset_ids"] = json.loads(
        str(result.pop("selected_asset_ids_json"))
    )
    result["contains_original_text"] = bool(result["contains_original_text"])
    result["contains_media"] = bool(result["contains_media"])
    return result


def create_data_manifest(
    *,
    owner_id: str,
    task_id: str,
    task_type: str,
    database_id: str,
    book_id: str | None,
    chapter_id: str | None,
    provider_id: str,
    model_id: str,
    original_messages: Sequence[Mapping[str, object]],
    final_messages: Sequence[Mapping[str, object]],
    approved_context_ids: Sequence[str],
    selected_asset_ids: Sequence[str],
    ttl_seconds: int = DEFAULT_MANIFEST_TTL_SECONDS,
) -> dict:
    profile = get_model_profile(model_id)
    provider = get_provider(provider_id)
    if not profile or not provider or profile["provider_id"] != provider_id:
        raise ModelDataBoundaryError(
            "MANIFEST_ROUTE_INVALID",
            "The resolved provider and model do not form a valid route.",
            409,
        )
    normalized_context_ids = tuple(sorted(dict.fromkeys(approved_context_ids)))
    normalized_asset_ids = validate_selected_assets(
        database_id,
        book_id,
        selected_asset_ids,
    )
    contains_original_text = any(
        bool(str(message.get("content", "")).strip()) for message in original_messages
    )
    size = estimate_payload_size(
        final_messages,
        normalized_context_ids,
        normalized_asset_ids,
    )
    policy = enforce_model_data_policy(
        model_id,
        contains_original_text=contains_original_text,
        approved_context_ids=normalized_context_ids,
        selected_asset_ids=normalized_asset_ids,
        estimated_payload_size=size,
    )
    created_at = _now()
    expires_at = created_at + timedelta(
        seconds=max(30, min(int(ttl_seconds), MAX_MANIFEST_TTL_SECONDS))
    )
    cloud_confirmation_required = is_cloud_provider(provider)
    initial_status = "pending" if cloud_confirmation_required else "confirmed"
    confirmed_at = None if cloud_confirmation_required else _iso(created_at)
    manifest_id = uuid.uuid4().hex
    values = (
        manifest_id,
        task_id,
        owner_id,
        database_id,
        book_id,
        chapter_id,
        provider_id,
        model_id,
        payload_fingerprint(
            task_id=task_id,
            task_type=task_type,
            database_id=database_id,
            book_id=book_id,
            chapter_id=chapter_id,
            messages=final_messages,
            approved_context_ids=normalized_context_ids,
            selected_asset_ids=normalized_asset_ids,
        ),
        selected_text_fingerprint(original_messages),
        json.dumps(normalized_context_ids, separators=(",", ":")),
        json.dumps(normalized_asset_ids, separators=(",", ":")),
        size,
        int(contains_original_text),
        int(bool(normalized_asset_ids)),
        initial_status,
        _iso(created_at),
        _iso(expires_at),
        confirmed_at,
    )
    conn = _get_registry_conn()
    try:
        conn.execute(
            """INSERT INTO model_data_manifests(
                   data_manifest_id,task_id,owner_id,database_id,book_id,chapter_id,
                   provider_id,model_id,payload_hash,selected_text_hash,
                   approved_context_ids_json,selected_asset_ids_json,
                   estimated_payload_size,contains_original_text,contains_media,
                   status,created_at,expires_at,confirmed_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            values,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM model_data_manifests WHERE data_manifest_id=?",
            (manifest_id,),
        ).fetchone()
    finally:
        conn.close()
    result = _public_manifest(row)
    result["permission_tier"] = policy["permission_tier"]
    result["cloud_confirmation_required"] = cloud_confirmation_required
    return result


def get_data_manifest(data_manifest_id: str, owner_id: str) -> dict:
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT * FROM model_data_manifests WHERE data_manifest_id=? AND owner_id=?",
            (data_manifest_id, owner_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ModelDataBoundaryError(
            "DATA_MANIFEST_NOT_FOUND",
            "Data manifest was not found.",
            404,
        )
    result = _public_manifest(row)
    if result["status"] in {"pending", "confirmed"} and _parse(result["expires_at"]) <= _now():
        _expire_manifest(data_manifest_id)
        result["status"] = "expired"
    return result


def _expire_manifest(data_manifest_id: str) -> None:
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE model_data_manifests SET status='expired' "
            "WHERE data_manifest_id=? AND status IN ('pending','confirmed')",
            (data_manifest_id,),
        )
        conn.commit()
    finally:
        conn.close()


def confirm_data_manifest(data_manifest_id: str, owner_id: str) -> dict:
    conn = _get_registry_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM model_data_manifests WHERE data_manifest_id=? AND owner_id=?",
            (data_manifest_id, owner_id),
        ).fetchone()
        if not row:
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_NOT_FOUND",
                "Data manifest was not found.",
                404,
            )
        if _parse(row["expires_at"]) <= _now():
            conn.execute(
                "UPDATE model_data_manifests SET status='expired' WHERE data_manifest_id=?",
                (data_manifest_id,),
            )
            conn.commit()
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_EXPIRED",
                "Data manifest has expired.",
            )
        if row["status"] == "confirmed":
            conn.commit()
            return _public_manifest(row)
        if row["status"] != "pending":
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_NOT_CONFIRMABLE",
                "Data manifest cannot be confirmed in its current state.",
            )
        confirmed_at = _iso(_now())
        conn.execute(
            "UPDATE model_data_manifests SET status='confirmed',confirmed_at=? "
            "WHERE data_manifest_id=?",
            (confirmed_at, data_manifest_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM model_data_manifests WHERE data_manifest_id=?",
            (data_manifest_id,),
        ).fetchone()
        return _public_manifest(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_data_manifest(
    data_manifest_id: str,
    *,
    owner_id: str,
    task_id: str,
    task_type: str,
    database_id: str,
    book_id: str | None,
    chapter_id: str | None,
    provider_id: str,
    model_id: str,
    original_messages: Sequence[Mapping[str, object]],
    final_messages: Sequence[Mapping[str, object]],
    approved_context_ids: Sequence[str],
    selected_asset_ids: Sequence[str],
) -> dict:
    normalized_context_ids = tuple(sorted(dict.fromkeys(approved_context_ids)))
    normalized_asset_ids = validate_selected_assets(
        database_id,
        book_id,
        selected_asset_ids,
    )
    expected_payload_hash = payload_fingerprint(
        task_id=task_id,
        task_type=task_type,
        database_id=database_id,
        book_id=book_id,
        chapter_id=chapter_id,
        messages=final_messages,
        approved_context_ids=normalized_context_ids,
        selected_asset_ids=normalized_asset_ids,
    )
    expected_text_hash = selected_text_fingerprint(original_messages)
    expected_size = estimate_payload_size(
        final_messages,
        normalized_context_ids,
        normalized_asset_ids,
    )
    enforce_model_data_policy(
        model_id,
        contains_original_text=any(
            bool(str(message.get("content", "")).strip())
            for message in original_messages
        ),
        approved_context_ids=normalized_context_ids,
        selected_asset_ids=normalized_asset_ids,
        estimated_payload_size=expected_size,
    )
    conn = _get_registry_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM model_data_manifests WHERE data_manifest_id=? AND owner_id=?",
            (data_manifest_id, owner_id),
        ).fetchone()
        if not row:
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_NOT_FOUND",
                "Data manifest was not found.",
                404,
            )
        if _parse(row["expires_at"]) <= _now():
            conn.execute(
                "UPDATE model_data_manifests SET status='expired' WHERE data_manifest_id=?",
                (data_manifest_id,),
            )
            conn.commit()
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_EXPIRED",
                "Data manifest has expired.",
            )
        if row["status"] == "consumed":
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_ALREADY_USED",
                "Data manifest has already been consumed.",
            )
        if row["status"] != "confirmed":
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_CONFIRMATION_REQUIRED",
                "Data manifest must be confirmed before cloud execution.",
            )
        expected = {
            "task_id": task_id,
            "database_id": database_id,
            "book_id": book_id,
            "chapter_id": chapter_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "payload_hash": expected_payload_hash,
            "selected_text_hash": expected_text_hash,
            "approved_context_ids_json": json.dumps(
                normalized_context_ids, separators=(",", ":")
            ),
            "selected_asset_ids_json": json.dumps(
                normalized_asset_ids, separators=(",", ":")
            ),
            "estimated_payload_size": expected_size,
        }
        if any(row[key] != value for key, value in expected.items()):
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_MISMATCH",
                "The current server payload does not match the confirmed manifest.",
            )
        consumed_at = _iso(_now())
        cursor = conn.execute(
            "UPDATE model_data_manifests SET status='consumed',consumed_at=? "
            "WHERE data_manifest_id=? AND owner_id=? AND status='confirmed'",
            (consumed_at, data_manifest_id, owner_id),
        )
        if cursor.rowcount != 1:
            raise ModelDataBoundaryError(
                "DATA_MANIFEST_ALREADY_USED",
                "Data manifest has already been consumed.",
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM model_data_manifests WHERE data_manifest_id=?",
            (data_manifest_id,),
        ).fetchone()
        return _public_manifest(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
