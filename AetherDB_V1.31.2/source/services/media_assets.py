"""Unified local media asset storage and lifecycle service."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from services.database_registry import get_database, get_db_path
from services.db import get_db


MAX_MEDIA_UPLOAD_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
DEFAULT_RETENTION_DAYS = 7
SOURCE_TYPES = {"imported", "generated", "captured", "derived"}
LIFECYCLE_STATUSES = {
    "temporary",
    "pending_review",
    "approved",
    "archived",
    "soft_deleted",
    "rejected",
}
TARGET_TYPES = {
    "database",
    "book",
    "content_group",
    "chapter",
    "entity",
    "entity_state_segment",
    "event",
    "relation",
    "timeline",
    "temporal_anchor",
    "branch",
}
EXTENSIONS = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/gif": {".gif"},
    "image/webp": {".webp"},
    "audio/wav": {".wav"},
    "audio/flac": {".flac"},
    "audio/ogg": {".ogg", ".oga"},
    "audio/mpeg": {".mp3"},
    "video/mp4": {".mp4", ".m4v"},
    "video/webm": {".webm"},
}
MODALITY_LIMITS = {
    "image": 64 * 1024 * 1024,
    "audio": 256 * 1024 * 1024,
    "video": MAX_MEDIA_UPLOAD_BYTES,
}


class MediaAssetError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(filename: str | None) -> str:
    candidate = Path(filename or "media").name
    candidate = "".join(ch for ch in candidate if ch >= " " and ch not in "\x7f")
    candidate = candidate.strip(" .")
    if not candidate:
        candidate = "media"
    return candidate[:255]


def _detect_mime(header: bytes) -> str | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"fLaC"):
        return "audio/flac"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
    ):
        return "audio/mpeg"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return None


def _modality(mime_type: str) -> str:
    return mime_type.split("/", 1)[0]


def _validate_declared_type(
    detected_mime: str | None, declared_mime: str | None, filename: str
) -> tuple[str, str]:
    if detected_mime not in EXTENSIONS:
        raise MediaAssetError(
            "UNSUPPORTED_MEDIA_TYPE",
            "The file signature is not a supported image, audio, or video format.",
            415,
        )
    declared = (declared_mime or "").lower().split(";", 1)[0].strip()
    if declared and declared != "application/octet-stream" and declared != detected_mime:
        aliases = {("audio/x-wav", "audio/wav"), ("image/jpg", "image/jpeg")}
        if (declared, detected_mime) not in aliases:
            raise MediaAssetError(
                "MEDIA_TYPE_MISMATCH",
                "The declared media type does not match the file signature.",
                415,
            )
    suffix = Path(filename).suffix.lower()
    if suffix and suffix not in EXTENSIONS[detected_mime]:
        raise MediaAssetError(
            "FILE_EXTENSION_MISMATCH",
            "The filename extension does not match the file signature.",
            415,
        )
    return detected_mime, _modality(detected_mime)


def _media_root(database_id: str) -> Path:
    database = get_database(database_id)
    if not database:
        raise MediaAssetError("DATABASE_NOT_FOUND", "Database not found.", 404)
    db_path = Path(get_db_path(database_id)).resolve()
    root = db_path.parent / "assets"
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise MediaAssetError("UNSAFE_STORAGE_ROOT", "Media storage root cannot be a symlink.", 409)
    return root.resolve()


def _storage_path(root: Path, relative_path: str, *, require_file: bool = True) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise MediaAssetError("UNSAFE_STORAGE_PATH", "Invalid media storage path.", 409)
    target = root.joinpath(*pure.parts)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise MediaAssetError("UNSAFE_STORAGE_PATH", "Invalid media storage path.", 409) from exc
    current = root
    for part in pure.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise MediaAssetError("UNSAFE_STORAGE_PATH", "Symlinks are not allowed in media storage.", 409)
    if require_file and (not resolved.is_file() or resolved.is_symlink()):
        raise MediaAssetError("MEDIA_FILE_MISSING", "Media file is unavailable.", 410)
    return resolved


def _json_object(value: dict | None) -> str:
    try:
        encoded = json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise MediaAssetError("INVALID_METADATA", "Metadata must be JSON serializable.") from exc
    if len(encoded.encode("utf-8")) > 32 * 1024:
        raise MediaAssetError("METADATA_TOO_LARGE", "Metadata exceeds 32 KiB.")
    return encoded


def _extract_metadata(path: Path, mime_type: str) -> dict:
    metadata: dict[str, int | float] = {}
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
        if mime_type == "image/png" and len(header) >= 24:
            metadata.update(width=struct.unpack(">I", header[16:20])[0], height=struct.unpack(">I", header[20:24])[0])
        elif mime_type == "image/gif" and len(header) >= 10:
            metadata.update(width=struct.unpack("<H", header[6:8])[0], height=struct.unpack("<H", header[8:10])[0])
        elif mime_type == "image/jpeg":
            metadata.update(_jpeg_dimensions(path))
        elif mime_type == "audio/wav":
            with wave.open(str(path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                metadata.update(
                    duration_seconds=round(frames / rate, 6) if rate else 0,
                    sample_rate=rate,
                    channels=wav.getnchannels(),
                )
    except (OSError, EOFError, wave.Error, struct.error):
        return {}
    return metadata


def _jpeg_dimensions(path: Path) -> dict:
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            return {}
        while True:
            marker_start = handle.read(1)
            if not marker_start:
                return {}
            if marker_start != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if marker in {b"\xd8", b"\xd9"}:
                continue
            length_raw = handle.read(2)
            if len(length_raw) != 2:
                return {}
            length = struct.unpack(">H", length_raw)[0]
            if marker and marker[0] in range(0xC0, 0xC4):
                payload = handle.read(5)
                if len(payload) == 5:
                    return {
                        "height": struct.unpack(">H", payload[1:3])[0],
                        "width": struct.unpack(">H", payload[3:5])[0],
                    }
                return {}
            handle.seek(max(0, length - 2), os.SEEK_CUR)


def _row_to_asset(row) -> dict:
    item = dict(row)
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    item["file_size_bytes"] = int(item["file_size_bytes"])
    return item


def _row_to_annotation(row) -> dict:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json") or "{}")
    item["is_stale"] = bool(item.get("is_stale"))
    return item


def import_media_asset(
    database_id: str,
    book_id: str,
    stream: BinaryIO,
    *,
    filename: str,
    declared_mime: str | None,
    source_type: str = "imported",
    created_by_task_id: str | None = None,
) -> dict:
    if source_type not in SOURCE_TYPES:
        raise MediaAssetError("INVALID_SOURCE_TYPE", "Unsupported media source type.")
    safe_name = _safe_filename(filename)
    root = _media_root(database_id)
    incoming = root / ".incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    if incoming.is_symlink():
        raise MediaAssetError("UNSAFE_STORAGE_ROOT", "Media staging root cannot be a symlink.", 409)

    digest = hashlib.sha256()
    total = 0
    header = b""
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=incoming, prefix="upload-", delete=False) as temp:
            temp_path = Path(temp.name)
            while True:
                chunk = stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise MediaAssetError("INVALID_MEDIA_STREAM", "Media stream must provide bytes.")
                total += len(chunk)
                if total > MAX_MEDIA_UPLOAD_BYTES:
                    raise MediaAssetError("MEDIA_TOO_LARGE", "Media exceeds the 512 MiB upload limit.", 413)
                if len(header) < 64:
                    header += chunk[: 64 - len(header)]
                digest.update(chunk)
                temp.write(chunk)
        if total == 0:
            raise MediaAssetError("EMPTY_MEDIA", "Media file is empty.")

        mime_type, modality = _validate_declared_type(_detect_mime(header), declared_mime, safe_name)
        if total > MODALITY_LIMITS[modality]:
            raise MediaAssetError(
                "MEDIA_TOO_LARGE",
                f"{modality.capitalize()} file exceeds its upload limit.",
                413,
            )
        content_hash = digest.hexdigest()
        relative_path = f"objects/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}"
        object_path = _storage_path(root, relative_path, require_file=False)
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if object_path.exists():
            if not object_path.is_file() or object_path.is_symlink():
                raise MediaAssetError("UNSAFE_STORAGE_PATH", "Media object path is unsafe.", 409)
            temp_path.unlink()
            temp_path = None
        else:
            os.replace(temp_path, object_path)
            temp_path = None

        metadata = _extract_metadata(object_path, mime_type)
        asset_id = _id("asset")
        version_id = _id("mver")
        metadata_json = _json_object(metadata)
        conn = get_db(database_id)
        try:
            if not conn.execute("SELECT 1 FROM books WHERE book_id=?", (book_id,)).fetchone():
                raise MediaAssetError("BOOK_NOT_FOUND", "Book not found.", 404)
            conn.execute("BEGIN")
            conn.execute(
                """INSERT INTO media_assets(
                    asset_id,database_id,book_id,modality,mime_type,relative_path,
                    original_filename,content_hash,file_size_bytes,source_type,
                    lifecycle_status,metadata_json,created_by_task_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    asset_id,
                    database_id,
                    book_id,
                    modality,
                    mime_type,
                    relative_path,
                    safe_name,
                    content_hash,
                    total,
                    source_type,
                    "temporary",
                    metadata_json,
                    created_by_task_id,
                ),
            )
            conn.execute(
                """INSERT INTO media_asset_versions(
                    version_id,asset_id,database_id,book_id,version_number,mime_type,
                    relative_path,content_hash,file_size_bytes,metadata_json
                ) VALUES (?,?,?,?,1,?,?,?,?,?)""",
                (
                    version_id,
                    asset_id,
                    database_id,
                    book_id,
                    mime_type,
                    relative_path,
                    content_hash,
                    total,
                    metadata_json,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM media_assets WHERE asset_id=?", (asset_id,)).fetchone()
            return _row_to_asset(row)
        except Exception:
            conn.rollback()
            # Keep a newly written content-addressed object on failure. Removing
            # it here could race a concurrent logical import of the same hash;
            # the retention-based orphan sweep below reclaims it safely.
            raise
        finally:
            conn.close()
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def list_media_assets(
    database_id: str,
    *,
    book_id: str,
    modality: str | None = None,
    lifecycle_status: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    _media_root(database_id)
    clauses = ["a.database_id=?", "a.book_id=?"]
    params: list[object] = [database_id, book_id]
    if modality:
        if modality not in MODALITY_LIMITS:
            raise MediaAssetError("INVALID_MODALITY", "Unsupported media modality.")
        clauses.append("a.modality=?")
        params.append(modality)
    if lifecycle_status:
        if lifecycle_status not in LIFECYCLE_STATUSES:
            raise MediaAssetError("INVALID_LIFECYCLE", "Unsupported lifecycle status.")
        clauses.append("a.lifecycle_status=?")
        params.append(lifecycle_status)
    join = ""
    if target_type or target_id:
        if not target_type or not target_id:
            raise MediaAssetError("INCOMPLETE_TARGET_FILTER", "Both target type and target id are required.")
        join = " JOIN media_asset_bindings b ON b.asset_id=a.asset_id "
        clauses.extend(["b.database_id=?", "b.book_id=?", "b.target_type=?", "b.target_id=?"])
        params.extend([database_id, book_id, target_type, target_id])
    where = " AND ".join(clauses)
    conn = get_db(database_id)
    try:
        total = conn.execute(
            f"SELECT COUNT(DISTINCT a.asset_id) FROM media_assets a {join} WHERE {where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT DISTINCT a.* FROM media_assets a {join}
                WHERE {where} ORDER BY a.created_at DESC,a.asset_id LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        return {"total": total, "assets": [_row_to_asset(row) for row in rows]}
    finally:
        conn.close()


def list_effective_chapter_media(
    database_id: str,
    *,
    book_id: str,
    chapter_id: str,
    language_code: str | None = None,
    modality: str | None = None,
    lifecycle_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Resolve chapter media with language override before group-wide assets."""
    _media_root(database_id)
    if modality and modality not in MODALITY_LIMITS:
        raise MediaAssetError("INVALID_MODALITY", "Unsupported media modality.")
    if lifecycle_status and lifecycle_status not in LIFECYCLE_STATUSES:
        raise MediaAssetError("INVALID_LIFECYCLE", "Unsupported lifecycle status.")

    conn = get_db(database_id)
    try:
        chapter = _chapter_binding_scope(conn, database_id, book_id, chapter_id)
        requested_language = _normalize_media_language(
            language_code or chapter["language_code"]
        )
        localized = conn.execute(
            """SELECT l.chapter_id
                 FROM chapter_localizations l
                 JOIN chapters c ON c.chapter_id=l.chapter_id
                WHERE l.content_group_id=? AND l.language_code=?
                  AND c.book_id=? AND c.is_active=1""",
            (chapter["content_group_id"], requested_language, book_id),
        ).fetchone()
        localized_chapter_id = (
            localized["chapter_id"]
            if localized
            else chapter_id if requested_language == chapter["language_code"] else None
        )

        clauses = [
            "a.database_id=?",
            "a.book_id=?",
            """(
                (
                    b.target_type='chapter' AND b.target_id=?
                    AND (b.language_code=? OR b.language_code IS NULL)
                )
                OR
                (
                    b.target_type='content_group' AND b.target_id=?
                    AND b.language_code IS NULL
                )
            )""",
        ]
        params: list[object] = [
            database_id,
            book_id,
            localized_chapter_id or "",
            requested_language,
            chapter["content_group_id"],
        ]
        if modality:
            clauses.append("a.modality=?")
            params.append(modality)
        if lifecycle_status:
            clauses.append("a.lifecycle_status=?")
            params.append(lifecycle_status)
        rows = conn.execute(
            f"""SELECT a.*,b.binding_id,b.target_type AS binding_target_type,
                       b.target_id AS binding_target_id,
                       b.language_code AS binding_language_code,b.binding_type,
                       b.sort_order,
                       CASE WHEN b.target_type='chapter' THEN 0 ELSE 1 END AS scope_priority
                  FROM media_assets a
                  JOIN media_asset_bindings b ON b.asset_id=a.asset_id
                 WHERE {' AND '.join(clauses)}
                 ORDER BY scope_priority,b.sort_order,a.created_at DESC,a.asset_id""",
            params,
        ).fetchall()
        deduped: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if row["asset_id"] in seen:
                continue
            seen.add(row["asset_id"])
            item = _row_to_asset(row)
            binding = {
                "binding_id": item.pop("binding_id"),
                "target_type": item.pop("binding_target_type"),
                "target_id": item.pop("binding_target_id"),
                "language_code": item.pop("binding_language_code"),
                "binding_type": item.pop("binding_type"),
                "sort_order": item.pop("sort_order"),
                "scope": "language_specific"
                if item.pop("scope_priority") == 0
                else "content_group",
            }
            item["effective_binding"] = binding
            deduped.append(item)
        page = deduped[offset : offset + limit]
        return {
            "total": len(deduped),
            "assets": page,
            "content_group_id": chapter["content_group_id"],
            "language_code": requested_language,
            "localized_chapter_id": localized_chapter_id,
            "resolution_order": ["language_specific", "content_group"],
        }
    finally:
        conn.close()


def get_media_asset(database_id: str, asset_id: str, *, include_related: bool = True) -> dict:
    _media_root(database_id)
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT * FROM media_assets WHERE database_id=? AND asset_id=?",
            (database_id, asset_id),
        ).fetchone()
        if not row:
            raise MediaAssetError("ASSET_NOT_FOUND", "Media asset not found.", 404)
        asset = _row_to_asset(row)
        if include_related:
            asset["versions"] = [
                {**dict(item), "metadata": json.loads(item["metadata_json"] or "{}")}
                for item in conn.execute(
                    "SELECT * FROM media_asset_versions WHERE asset_id=? ORDER BY version_number DESC",
                    (asset_id,),
                ).fetchall()
            ]
            for item in asset["versions"]:
                item.pop("metadata_json", None)
            asset["derivatives"] = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM media_asset_derivatives WHERE asset_id=? ORDER BY created_at",
                    (asset_id,),
                ).fetchall()
            ]
            asset["annotations"] = [
                _row_to_annotation(item)
                for item in conn.execute(
                    "SELECT * FROM media_annotations WHERE asset_id=? ORDER BY created_at",
                    (asset_id,),
                ).fetchall()
            ]
            asset["bindings"] = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM media_asset_bindings WHERE asset_id=? ORDER BY sort_order,created_at",
                    (asset_id,),
                ).fetchall()
            ]
        return asset
    finally:
        conn.close()


def update_media_asset(
    database_id: str,
    asset_id: str,
    *,
    original_filename: str | None = None,
    metadata: dict | None = None,
) -> dict:
    asset = get_media_asset(database_id, asset_id, include_related=False)
    if asset["lifecycle_status"] == "soft_deleted":
        raise MediaAssetError("ASSET_DELETED", "Deleted assets cannot be updated.", 409)
    changes = []
    params: list[object] = []
    if original_filename is not None:
        changes.append("original_filename=?")
        params.append(_safe_filename(original_filename))
    if metadata is not None:
        changes.append("metadata_json=?")
        params.append(_json_object(metadata))
    if not changes:
        return asset
    changes.append("updated_at=CURRENT_TIMESTAMP")
    conn = get_db(database_id)
    try:
        conn.execute(
            f"UPDATE media_assets SET {','.join(changes)} WHERE database_id=? AND asset_id=?",
            [*params, database_id, asset_id],
        )
        conn.commit()
    finally:
        conn.close()
    return get_media_asset(database_id, asset_id, include_related=False)


def transition_media_asset(database_id: str, asset_id: str, action: str) -> dict:
    transitions = {
        "submit": ({"temporary"}, "pending_review"),
        "approve": ({"temporary", "pending_review"}, "approved"),
        "reject": ({"temporary", "pending_review"}, "rejected"),
        "archive": ({"approved"}, "archived"),
    }
    if action not in transitions:
        raise MediaAssetError("INVALID_LIFECYCLE_ACTION", "Unsupported lifecycle action.")
    allowed, target = transitions[action]
    asset = get_media_asset(database_id, asset_id, include_related=False)
    if asset["lifecycle_status"] not in allowed:
        raise MediaAssetError(
            "INVALID_LIFECYCLE_TRANSITION",
            f"Cannot {action} an asset in {asset['lifecycle_status']} state.",
            409,
        )
    timestamp_column = "approved_at" if target == "approved" else "archived_at" if target == "archived" else None
    conn = get_db(database_id)
    try:
        extra = f",{timestamp_column}=CURRENT_TIMESTAMP" if timestamp_column else ""
        conn.execute(
            f"""UPDATE media_assets SET lifecycle_status=?,updated_at=CURRENT_TIMESTAMP{extra}
                WHERE database_id=? AND asset_id=?""",
            (target, database_id, asset_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_media_asset(database_id, asset_id, include_related=False)


def _scoped_exists(conn, query: str, params: tuple) -> bool:
    return conn.execute(query, params).fetchone() is not None


def _normalize_media_language(value: str | None, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    from services.chapter_localization import normalize_language_code

    try:
        return normalize_language_code(value or "und")
    except ValueError as exc:
        raise MediaAssetError("INVALID_LANGUAGE_CODE", str(exc)) from exc


def _chapter_binding_scope(
    conn,
    database_id: str,
    book_id: str,
    chapter_id: str,
) -> dict:
    from services.chapter_localization import (
        chapter_with_localization,
        ensure_chapter_localizations,
    )

    ensure_chapter_localizations(conn, database_id=database_id)
    chapter = chapter_with_localization(conn, chapter_id)
    if not chapter or chapter["book_id"] != book_id or not chapter["is_active"]:
        raise MediaAssetError(
            "BINDING_TARGET_NOT_FOUND",
            "Binding target was not found in this scope.",
            404,
        )
    return chapter


def _validate_binding_target(conn, database_id: str, book_id: str, target_type: str, target_id: str):
    if target_type not in TARGET_TYPES:
        raise MediaAssetError("UNSUPPORTED_BINDING_TARGET", "Unsupported binding target type.")
    checks = {
        "book": ("SELECT 1 FROM books WHERE book_id=?", (target_id,)),
        "content_group": (
            "SELECT 1 FROM content_groups WHERE book_id=? AND content_group_id=?",
            (book_id, target_id),
        ),
        "chapter": ("SELECT 1 FROM chapters WHERE book_id=? AND chapter_id=?", (book_id, target_id)),
        "entity": ("SELECT 1 FROM entities WHERE book_id=? AND entity_id=? AND is_active=1", (book_id, target_id)),
        "entity_state_segment": (
            "SELECT 1 FROM entity_state_segments WHERE book_id=? AND id=?",
            (book_id, target_id),
        ),
        "relation": ("SELECT 1 FROM relations WHERE book_id=? AND CAST(id AS TEXT)=?", (book_id, target_id)),
        "timeline": ("SELECT 1 FROM timelines WHERE book_id=? AND id=?", (book_id, target_id)),
        "temporal_anchor": (
            "SELECT 1 FROM temporal_anchors WHERE book_id=? AND id=?",
            (book_id, target_id),
        ),
        "event": (
            """SELECT 1 FROM timeline_events WHERE book_id=? AND CAST(id AS TEXT)=?
               UNION SELECT 1 FROM temporal_event_metadata WHERE book_id=? AND event_id=?""",
            (book_id, target_id, book_id, target_id),
        ),
        "branch": (
            """SELECT 1 FROM temporal_anchors WHERE book_id=? AND branch_id=?
               UNION SELECT 1 FROM entity_state_segments WHERE book_id=? AND branch_id=?""",
            (book_id, target_id, book_id, target_id),
        ),
    }
    if target_type == "database":
        exists = target_id == database_id
    else:
        query, params = checks[target_type]
        exists = _scoped_exists(conn, query, params)
    if not exists:
        raise MediaAssetError("BINDING_TARGET_NOT_FOUND", "Binding target was not found in this scope.", 404)


def create_media_binding(database_id: str, asset_id: str, payload: dict) -> dict:
    asset = get_media_asset(database_id, asset_id, include_related=False)
    if asset["lifecycle_status"] != "approved":
        raise MediaAssetError("ASSET_NOT_APPROVED", "Only approved assets may be bound.", 409)
    book_id = payload["book_id"]
    if asset["book_id"] != book_id:
        raise MediaAssetError("CROSS_BOOK_BINDING", "Asset and target must belong to the same book.", 409)
    conn = get_db(database_id)
    try:
        _validate_binding_target(conn, database_id, book_id, payload["target_type"], payload["target_id"])
        language_code = _normalize_media_language(
            payload.get("language_code"),
            allow_none=True,
        )
        if payload["target_type"] == "chapter":
            chapter = _chapter_binding_scope(
                conn,
                database_id,
                book_id,
                payload["target_id"],
            )
            chapter_language = chapter["language_code"]
            if language_code is not None and language_code != chapter_language:
                raise MediaAssetError(
                    "LANGUAGE_BINDING_MISMATCH",
                    "A chapter-specific media binding must use the chapter content language.",
                    409,
                )
            language_code = chapter_language
        elif payload["target_type"] == "content_group":
            if language_code is not None:
                raise MediaAssetError(
                    "GENERIC_BINDING_HAS_LANGUAGE",
                    "A content-group media binding applies to every language and cannot set language_code.",
                    409,
                )
        elif language_code is not None:
            raise MediaAssetError(
                "UNSUPPORTED_LANGUAGE_BINDING",
                "Language-specific media binding is currently supported only for chapters.",
                409,
            )
        timeline_id = payload.get("timeline_id")
        branch_id = payload.get("branch_id")
        from_anchor = payload.get("valid_from_anchor_id")
        to_anchor = payload.get("valid_to_anchor_id")
        state_id = payload.get("entity_state_segment_id")
        if timeline_id and not _scoped_exists(
            conn, "SELECT 1 FROM timelines WHERE book_id=? AND id=?", (book_id, timeline_id)
        ):
            raise MediaAssetError("TIMELINE_NOT_FOUND", "Timeline not found in this book.", 404)
        for anchor_id in (from_anchor, to_anchor):
            if anchor_id and not _scoped_exists(
                conn,
                "SELECT 1 FROM temporal_anchors WHERE book_id=? AND id=?",
                (book_id, anchor_id),
            ):
                raise MediaAssetError("ANCHOR_NOT_FOUND", "Temporal anchor not found in this book.", 404)
        if state_id and not _scoped_exists(
            conn,
            "SELECT 1 FROM entity_state_segments WHERE book_id=? AND id=?",
            (book_id, state_id),
        ):
            raise MediaAssetError("STATE_SEGMENT_NOT_FOUND", "Entity state segment not found.", 404)
        binding_id = _id("mbind")
        try:
            conn.execute(
                """INSERT INTO media_asset_bindings(
                    binding_id,asset_id,database_id,book_id,target_type,target_id,
                    binding_type,timeline_id,branch_id,valid_from_anchor_id,
                    valid_to_anchor_id,entity_state_segment_id,sort_order,notes,
                    language_code
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    binding_id,
                    asset_id,
                    database_id,
                    book_id,
                    payload["target_type"],
                    payload["target_id"],
                    payload["binding_type"],
                    timeline_id,
                    branch_id,
                    from_anchor,
                    to_anchor,
                    state_id,
                    payload.get("sort_order", 0),
                    payload.get("notes", ""),
                    language_code,
                ),
            )
            conn.commit()
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise MediaAssetError("BINDING_EXISTS", "This media binding already exists.", 409) from exc
            raise
        row = conn.execute(
            "SELECT * FROM media_asset_bindings WHERE binding_id=?", (binding_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_media_binding(database_id: str, asset_id: str, binding_id: str) -> None:
    conn = get_db(database_id)
    try:
        cursor = conn.execute(
            """DELETE FROM media_asset_bindings
               WHERE database_id=? AND asset_id=? AND binding_id=?""",
            (database_id, asset_id, binding_id),
        )
        if cursor.rowcount == 0:
            raise MediaAssetError("BINDING_NOT_FOUND", "Media binding not found.", 404)
        conn.commit()
    finally:
        conn.close()


def add_media_annotation(database_id: str, asset_id: str, payload: dict) -> dict:
    asset = get_media_asset(database_id, asset_id, include_related=False)
    if asset["lifecycle_status"] == "soft_deleted":
        raise MediaAssetError("ASSET_DELETED", "Deleted assets cannot be annotated.", 409)
    annotation_id = _id("mann")
    conn = get_db(database_id)
    try:
        version_id = payload.get("version_id")
        if version_id:
            version = conn.execute(
                "SELECT version_id,content_hash FROM media_asset_versions "
                "WHERE asset_id=? AND version_id=?",
                (asset_id, version_id),
            ).fetchone()
        else:
            version = conn.execute(
                "SELECT version_id,content_hash FROM media_asset_versions "
                "WHERE asset_id=? ORDER BY version_number DESC LIMIT 1",
                (asset_id,),
            ).fetchone()
        if not version:
            raise MediaAssetError("VERSION_NOT_FOUND", "Media version not found.", 404)
        version_id = version["version_id"]
        language_code = _normalize_media_language(payload.get("language_code"))
        conn.execute(
            """INSERT INTO media_annotations(
                annotation_id,asset_id,version_id,database_id,book_id,
                annotation_type,payload_json,source_type,approval_status,
                model_profile_id,source_task_id,language_code,
                source_revision_hash,is_stale
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (
                annotation_id,
                asset_id,
                version_id,
                database_id,
                asset["book_id"],
                payload["annotation_type"],
                _json_object(payload["payload"]),
                payload.get("source_type", "manual"),
                payload.get("approval_status", "pending"),
                payload.get("model_profile_id"),
                payload.get("source_task_id"),
                language_code,
                version["content_hash"],
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM media_annotations WHERE annotation_id=?", (annotation_id,)
        ).fetchone()
        return _row_to_annotation(row)
    finally:
        conn.close()


def review_media_annotation(
    database_id: str,
    asset_id: str,
    annotation_id: str,
    *,
    approved: bool,
) -> dict:
    asset = get_media_asset(database_id, asset_id, include_related=False)
    if asset["lifecycle_status"] == "soft_deleted":
        raise MediaAssetError("ASSET_DELETED", "Deleted assets cannot be reviewed.", 409)
    target = "approved" if approved else "rejected"
    conn = get_db(database_id)
    try:
        row = conn.execute(
            "SELECT * FROM media_annotations WHERE annotation_id=? AND asset_id=? "
            "AND database_id=? AND book_id=?",
            (annotation_id, asset_id, database_id, asset["book_id"]),
        ).fetchone()
        if not row:
            raise MediaAssetError("ANNOTATION_NOT_FOUND", "Media annotation not found.", 404)
        conn.execute(
            "UPDATE media_annotations SET approval_status=?,updated_at=CURRENT_TIMESTAMP "
            "WHERE annotation_id=?",
            (target, annotation_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM media_annotations WHERE annotation_id=?",
            (annotation_id,),
        ).fetchone()
        return _row_to_annotation(row)
    finally:
        conn.close()


def soft_delete_media_asset(database_id: str, asset_id: str) -> dict:
    asset = get_media_asset(database_id, asset_id, include_related=False)
    conn = get_db(database_id)
    try:
        if conn.execute(
            "SELECT 1 FROM media_asset_bindings WHERE asset_id=? LIMIT 1", (asset_id,)
        ).fetchone():
            raise MediaAssetError("ASSET_HAS_BINDINGS", "Remove media bindings before deletion.", 409)
        if conn.execute(
            "SELECT 1 FROM audio_voice_profiles WHERE reference_asset_id=? LIMIT 1",
            (asset_id,),
        ).fetchone():
            raise MediaAssetError(
                "ASSET_IS_VOICE_REFERENCE",
                "Remove the voice profile reference before deleting this audio asset.",
                409,
            )
        if asset["lifecycle_status"] == "soft_deleted":
            return asset
        conn.execute(
            """UPDATE media_assets
               SET lifecycle_status='soft_deleted',deleted_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP
               WHERE database_id=? AND asset_id=?""",
            (database_id, asset_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_media_asset(database_id, asset_id, include_related=False)


def get_media_content(database_id: str, asset_id: str) -> tuple[Path, dict]:
    asset = get_media_asset(database_id, asset_id, include_related=False)
    if asset["lifecycle_status"] == "soft_deleted":
        raise MediaAssetError("ASSET_DELETED", "Deleted media content is unavailable.", 410)
    return _storage_path(_media_root(database_id), asset["relative_path"]), asset


def cleanup_media_assets(database_id: str, *, retention_days: int = DEFAULT_RETENTION_DAYS) -> dict:
    from services.media_vision import delete_media_vector_rows

    root = _media_root(database_id)
    conn = get_db(database_id)
    removed_assets: list[str] = []
    candidate_paths: set[str] = set()
    try:
        rows = conn.execute(
            """SELECT a.asset_id,a.relative_path FROM media_assets a
               WHERE a.lifecycle_status IN ('temporary','rejected','soft_deleted')
                 AND CASE a.lifecycle_status
                       WHEN 'temporary' THEN a.created_at
                       WHEN 'rejected' THEN a.updated_at
                       ELSE COALESCE(a.deleted_at,a.updated_at)
                     END
                     <= datetime('now',?)
                 AND NOT EXISTS(
                     SELECT 1 FROM media_asset_bindings b WHERE b.asset_id=a.asset_id
                 )
                 AND NOT EXISTS(
                     SELECT 1 FROM audio_voice_profiles v WHERE v.reference_asset_id=a.asset_id
                 )""",
            (f"-{retention_days} days",),
        ).fetchall()
        conn.execute("BEGIN")
        for row in rows:
            version_paths = conn.execute(
                "SELECT relative_path FROM media_asset_versions WHERE asset_id=?",
                (row["asset_id"],),
            ).fetchall()
            derivative_paths = conn.execute(
                "SELECT relative_path FROM media_asset_derivatives WHERE asset_id=?",
                (row["asset_id"],),
            ).fetchall()
            candidate_paths.update(item["relative_path"] for item in version_paths)
            candidate_paths.update(item["relative_path"] for item in derivative_paths)
            candidate_paths.add(row["relative_path"])
            delete_media_vector_rows(conn, row["asset_id"])
            conn.execute("DELETE FROM media_assets WHERE asset_id=?", (row["asset_id"],))
            removed_assets.append(row["asset_id"])
        conn.commit()
        removed_objects = 0
        for relative_path in candidate_paths:
            referenced = conn.execute(
                """SELECT 1 FROM media_assets WHERE relative_path=?
                   UNION SELECT 1 FROM media_asset_versions WHERE relative_path=?
                   UNION SELECT 1 FROM media_asset_derivatives WHERE relative_path=?
                   LIMIT 1""",
                (relative_path, relative_path, relative_path),
            ).fetchone()
            if referenced:
                continue
            try:
                path = _storage_path(root, relative_path)
            except MediaAssetError as exc:
                if exc.code == "MEDIA_FILE_MISSING":
                    continue
                raise
            path.unlink()
            removed_objects += 1
        incoming = root / ".incoming"
        if incoming.exists() and incoming.is_dir() and not incoming.is_symlink():
            for stale in incoming.iterdir():
                if stale.is_file() and not stale.is_symlink():
                    age = datetime.now(timezone.utc).timestamp() - stale.stat().st_mtime
                    if age >= retention_days * 86400:
                        stale.unlink()
        objects = root / "objects"
        if objects.exists() and objects.is_dir() and not objects.is_symlink():
            for candidate in objects.rglob("*"):
                if not candidate.is_file() or candidate.is_symlink():
                    continue
                relative_path = candidate.relative_to(root).as_posix()
                referenced = conn.execute(
                    """SELECT 1 FROM media_assets WHERE relative_path=?
                       UNION SELECT 1 FROM media_asset_versions WHERE relative_path=?
                       UNION SELECT 1 FROM media_asset_derivatives WHERE relative_path=?
                       LIMIT 1""",
                    (relative_path, relative_path, relative_path),
                ).fetchone()
                age = datetime.now(timezone.utc).timestamp() - candidate.stat().st_mtime
                if not referenced and age >= retention_days * 86400:
                    candidate.unlink()
                    removed_objects += 1
        return {
            "removed_assets": len(removed_assets),
            "removed_objects": removed_objects,
            "asset_ids": removed_assets,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
