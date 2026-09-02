"""Local multimodal indexing for image assets.

The visual and caption channels remain separate vector spaces. BGE-VL handles
image/text similarity, while the core local BGE-M3 runtime preserves
multilingual caption retrieval.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import sqlite3
import struct
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import sqlite_vec

from services.database_registry import get_db_path, list_databases
from services.embedding import EmbeddingProvider
from services.media_assets import MediaAssetError, get_media_asset, get_media_content
from services.model_packages.registry import (
    get_installation,
    get_manifest,
    sync_catalog,
)
from services.vector_store import get_default_vector_store


VISUAL_PACKAGE_ID = "aetherdb.bge-vl-base"
VISUAL_VECTOR_SPACE = "bge-vl-base-512-v1"
CAPTION_VECTOR_SPACE = "bge-m3-media-caption-1024-v1"
VISUAL_DIMS = 512
CAPTION_DIMS = 1024
VISUAL_SPACE_SCHEMA_VERSION = "1"
VISUAL_IMAGE_PREPROCESS_VERSION = "clip-image-processor-v1"
VISUAL_QUERY_TEMPLATE_VERSION = "clip-text-query-v1"
VISUAL_POOLING_VERSION = "clip-projected-pooled-v1"
VISUAL_INDEX_PRECISION = "float32"
VISUAL_MIGRATION_ABSOLUTE_TIMEOUT_SECONDS = 30 * 60
VISUAL_MIGRATION_ITEM_TIMEOUT_SECONDS = 3 * 60
VISUAL_MIGRATION_TERMINAL = {
    "completed",
    "partial_failed",
    "failed",
    "cancelled",
}
_MIGRATION_QUEUE: queue.Queue[tuple[str, str]] = queue.Queue()
_MIGRATION_STATE_LOCK = threading.RLock()
_MIGRATION_RUNNING: set[tuple[str, str]] = set()
_MIGRATION_THREAD: threading.Thread | None = None
log = logging.getLogger(__name__)
SEARCHABLE_LIFECYCLES = {
    "temporary",
    "pending_review",
    "approved",
    "archived",
}
CAPTION_ANNOTATION_TYPES = {
    "caption",
    "description",
    "alt_text",
    "image_caption",
}


class MediaVisionError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


class VisionEmbeddingProvider(Protocol):
    is_aetherdb_local: bool

    def status(self) -> dict:
        ...

    def embed_image(
        self,
        path: Path,
        content_hash: str,
        *,
        requested_backend: str = "auto",
    ) -> list[float]:
        ...

    def embed_text(
        self,
        text: str,
        *,
        requested_backend: str = "auto",
    ) -> list[float]:
        ...


class WorkerBgeVLProvider:
    is_aetherdb_local = True

    @staticmethod
    def status() -> dict:
        try:
            sync_catalog()
            manifest = get_manifest(VISUAL_PACKAGE_ID, sync=False)
            installation = get_installation(VISUAL_PACKAGE_ID)
            files_by_role = {
                item.role: item
                for item in manifest.files
                if item.role in {"weights", "processor"}
            }
            return {
                "available": bool(
                    installation and installation["status"] == "installed"
                ),
                "package_id": VISUAL_PACKAGE_ID,
                "package_version": manifest.package_version,
                "model_id": manifest.model_family,
                "revision": manifest.source.revision,
                "model_hash": getattr(files_by_role.get("weights"), "sha256", ""),
                "dimensions": manifest.embedding.dimension,
                "vector_space_id": manifest.embedding.vector_space_id,
                "package_version": manifest.package_version,
                "runtime": manifest.runtime_adapter,
                "image_preprocess_version": (
                    getattr(files_by_role.get("processor"), "sha256", "")
                    or VISUAL_IMAGE_PREPROCESS_VERSION
                ),
                "query_template_version": VISUAL_QUERY_TEMPLATE_VERSION,
                "pooling": VISUAL_POOLING_VERSION,
                "precision": VISUAL_INDEX_PRECISION,
                "language_scope": "english_text_tower",
                "remote_code": False,
                "installation_status": (
                    installation["status"] if installation else "install_available"
                ),
            }
        except Exception as exc:
            return {
                "available": False,
                "package_id": VISUAL_PACKAGE_ID,
                "model_id": "BAAI/BGE-VL-base",
                "revision": None,
                "model_hash": "",
                "dimensions": VISUAL_DIMS,
                "vector_space_id": VISUAL_VECTOR_SPACE,
                "package_version": None,
                "runtime": "aetherdb_torch_bge_vl",
                "image_preprocess_version": VISUAL_IMAGE_PREPROCESS_VERSION,
                "query_template_version": VISUAL_QUERY_TEMPLATE_VERSION,
                "pooling": VISUAL_POOLING_VERSION,
                "precision": VISUAL_INDEX_PRECISION,
                "language_scope": "english_text_tower",
                "remote_code": False,
                "detail": type(exc).__name__,
            }

    @staticmethod
    def _execute(
        *,
        task_id: str,
        payload: dict,
        requested_backend: str,
    ) -> list[float]:
        from services.model_runtime.manager import get_worker_manager

        try:
            execution = get_worker_manager().execute(
                VISUAL_PACKAGE_ID,
                task_id=task_id,
                operation="vision",
                payload=payload,
                requested_backend=requested_backend,
                priority=55,
                timeout=VISUAL_MIGRATION_ITEM_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise MediaVisionError(
                getattr(exc, "code", "VISION_RUNTIME_FAILED"),
                getattr(exc, "safe_message", "Local visual embedding failed"),
                503,
            ) from exc
        result = execution["result"]
        vectors = result.get("vectors")
        if (
            not isinstance(vectors, list)
            or len(vectors) != 1
            or not isinstance(vectors[0], list)
        ):
            raise MediaVisionError(
                "VISION_RESULT_INVALID",
                "Local visual Worker returned an invalid result",
                503,
            )
        return vectors[0]

    def embed_image(
        self,
        path: Path,
        content_hash: str,
        *,
        requested_backend: str = "auto",
    ) -> list[float]:
        return self._execute(
            task_id=f"media-vision-image:{uuid.uuid4().hex}",
            payload={
                "mode": "image",
                "images": [{"path": str(path), "sha256": content_hash}],
            },
            requested_backend=requested_backend,
        )

    def embed_text(
        self,
        text: str,
        *,
        requested_backend: str = "auto",
    ) -> list[float]:
        return self._execute(
            task_id=f"media-vision-text:{uuid.uuid4().hex}",
            payload={"mode": "text", "texts": [text]},
            requested_backend=requested_backend,
        )


def _status_dict(status) -> dict:
    if isinstance(status, dict):
        return dict(status)
    if is_dataclass(status):
        return asdict(status)
    return {
        key: getattr(status, key)
        for key in (
            "available",
            "model_id",
            "revision",
            "dimensions",
            "execution_provider",
            "detail",
        )
        if hasattr(status, key)
    }


def _normalize(vector: list[float], dimensions: int) -> list[float]:
    if (
        not isinstance(vector, list)
        or len(vector) != dimensions
        or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector)
    ):
        raise MediaVisionError(
            "VECTOR_RESULT_INVALID",
            f"Embedding must contain {dimensions} finite values",
            503,
        )
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm <= 0:
        raise MediaVisionError("VECTOR_RESULT_INVALID", "Embedding cannot be zero", 503)
    return [float(value) / norm for value in vector]


def _deserialize_vector(blob: bytes, dimensions: int) -> list[float]:
    if len(blob) != dimensions * 4:
        raise MediaVisionError(
            "VECTOR_INDEX_CORRUPT",
            "Stored media vector has an invalid size",
            500,
        )
    return list(struct.unpack(f"<{dimensions}f", blob))


def _load_vec(conn: sqlite3.Connection) -> None:
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)


def delete_media_vector_rows(conn: sqlite3.Connection, asset_id: str) -> int:
    """Delete sqlite-vec rows before the owning metadata cascades away."""
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    if "media_vector_records" not in tables:
        return 0
    rows = conn.execute(
        "SELECT vector_id,channel FROM media_vector_records WHERE asset_id=?",
        (asset_id,),
    ).fetchall()
    if not rows:
        return 0
    _load_vec(conn)
    for row in rows:
        if row["channel"] == "visual":
            for table in (
                "media_visual_vectors_vec",
                "media_visual_vectors_vec_v2",
            ):
                if table in tables:
                    conn.execute(
                        f"DELETE FROM {table} WHERE vector_id=?",
                        (row["vector_id"],),
                    )
        elif "media_caption_vectors_vec" in tables:
            conn.execute(
                "DELETE FROM media_caption_vectors_vec WHERE vector_id=?",
                (row["vector_id"],),
            )
    return len(rows)


class MediaVisionIndex:
    def __init__(
        self,
        database_id: str,
        *,
        vision_provider: VisionEmbeddingProvider | None = None,
        caption_provider: EmbeddingProvider | None = None,
    ):
        self.database_id = database_id
        self.db_path = get_db_path(database_id)
        self.vision = vision_provider or WorkerBgeVLProvider()
        if caption_provider is None:
            store = get_default_vector_store()
            caption_provider = store.embedding if store is not None else None
        self.caption = caption_provider

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _load_vec(conn)
        return conn

    @staticmethod
    def _visual_scope_key(space_id: str, book_id: str) -> str:
        return f"{space_id}|{book_id}"

    @staticmethod
    def _visual_source_revision(conn: sqlite3.Connection) -> tuple[str, int]:
        rows = conn.execute(
            """SELECT a.asset_id,a.book_id,a.lifecycle_status,a.content_hash,
                      v.version_id,v.content_hash AS version_hash
                 FROM media_assets a
                 JOIN media_asset_versions v ON v.asset_id=a.asset_id
                WHERE a.modality='image'
                  AND a.lifecycle_status NOT IN ('soft_deleted','rejected')
                  AND v.version_number=(
                      SELECT MAX(v2.version_number)
                        FROM media_asset_versions v2
                       WHERE v2.asset_id=a.asset_id
                  )
                ORDER BY a.asset_id"""
        ).fetchall()
        digest = hashlib.sha256()
        for row in rows:
            digest.update(
                json.dumps(
                    list(row),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
        return digest.hexdigest(), len(rows)

    @staticmethod
    def _visual_manifest(status: dict) -> tuple[dict, str]:
        model_id = str(status.get("model_id") or "BAAI/BGE-VL-base")
        revision = str(status.get("revision") or "")
        model_hash = str(status.get("model_hash") or "").lower()
        if len(model_hash) != 64:
            model_hash = hashlib.sha256(
                f"{model_id}\0{revision}".encode("utf-8")
            ).hexdigest()
        manifest = {
            "space_kind": "visual",
            "model_id": model_id,
            "model_revision": revision,
            "model_hash": model_hash,
            "package_id": str(status.get("package_id") or VISUAL_PACKAGE_ID),
            "package_version": str(status.get("package_version") or ""),
            "image_preprocess_version": str(
                status.get("image_preprocess_version")
                or VISUAL_IMAGE_PREPROCESS_VERSION
            ),
            "query_template_version": str(
                status.get("query_template_version")
                or VISUAL_QUERY_TEMPLATE_VERSION
            ),
            "pooling": str(status.get("pooling") or VISUAL_POOLING_VERSION),
            "precision": str(status.get("precision") or VISUAL_INDEX_PRECISION),
            "dimensions": VISUAL_DIMS,
            "normalization": "l2",
            "distance_metric": "cosine",
            "runtime": str(status.get("runtime") or "aetherdb_torch_bge_vl"),
            "space_schema_version": VISUAL_SPACE_SCHEMA_VERSION,
        }
        digest = hashlib.sha256(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return manifest, digest

    def _bootstrap_visual_space(
        self,
        conn: sqlite3.Connection,
        status: dict,
    ) -> str:
        manifest, manifest_hash = self._visual_manifest(status)
        source_revision_hash, source_asset_count = self._visual_source_revision(conn)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            """INSERT OR IGNORE INTO media_visual_spaces(
                   space_id,model_id,model_revision,model_hash,package_id,
                   package_version,image_preprocess_version,
                   query_template_version,pooling,precision,dimensions,
                   normalization,distance_metric,runtime,manifest_hash,
                   source_revision_hash,source_asset_count,status,stale,
                   created_at,validated_at,activated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',0,?,?,?)""",
            (
                VISUAL_VECTOR_SPACE,
                manifest["model_id"],
                manifest["model_revision"],
                manifest["model_hash"],
                manifest["package_id"],
                manifest["package_version"],
                manifest["image_preprocess_version"],
                manifest["query_template_version"],
                manifest["pooling"],
                manifest["precision"],
                manifest["dimensions"],
                manifest["normalization"],
                manifest["distance_metric"],
                manifest["runtime"],
                manifest_hash,
                source_revision_hash,
                source_asset_count,
                now,
                now,
                now,
            ),
        )
        pointer = conn.execute(
            "SELECT active_space_id FROM media_visual_space_pointer WHERE id=1"
        ).fetchone()
        if pointer is None:
            conn.execute(
                """INSERT INTO media_visual_space_pointer(
                       id,active_space_id,rollback_space_id,updated_at
                   ) VALUES (1,?,NULL,?)""",
                (VISUAL_VECTOR_SPACE, now),
            )
        bootstrap = conn.execute(
            "SELECT model_revision FROM media_visual_spaces WHERE space_id=?",
            (VISUAL_VECTOR_SPACE,),
        ).fetchone()
        bootstrap_records = conn.execute(
            """SELECT COUNT(*) FROM media_vector_records
                WHERE channel='visual' AND vector_space_id=?""",
            (VISUAL_VECTOR_SPACE,),
        ).fetchone()[0]
        if (
            status.get("available")
            and bootstrap is not None
            and not bootstrap["model_revision"]
            and bootstrap_records == 0
        ):
            conn.execute(
                """UPDATE media_visual_spaces
                      SET model_id=?,model_revision=?,model_hash=?,package_id=?,
                          package_version=?,image_preprocess_version=?,
                          query_template_version=?,pooling=?,precision=?,
                          dimensions=?,normalization=?,distance_metric=?,
                          runtime=?,manifest_hash=?,source_revision_hash=?,
                          source_asset_count=?
                    WHERE space_id=?""",
                (
                    manifest["model_id"],
                    manifest["model_revision"],
                    manifest["model_hash"],
                    manifest["package_id"],
                    manifest["package_version"],
                    manifest["image_preprocess_version"],
                    manifest["query_template_version"],
                    manifest["pooling"],
                    manifest["precision"],
                    manifest["dimensions"],
                    manifest["normalization"],
                    manifest["distance_metric"],
                    manifest["runtime"],
                    manifest_hash,
                    source_revision_hash,
                    source_asset_count,
                    VISUAL_VECTOR_SPACE,
                ),
            )

        legacy_rows = conn.execute(
            """SELECT r.vector_id,v.embedding,r.vector_space_id,r.book_id
                 FROM media_vector_records r
                 JOIN media_visual_vectors_vec v ON v.vector_id=r.vector_id
                WHERE r.channel='visual'"""
        ).fetchall()
        for row in legacy_rows:
            if conn.execute(
                "SELECT 1 FROM media_visual_vectors_vec_v2 WHERE vector_id=?",
                (row["vector_id"],),
            ).fetchone():
                continue
            conn.execute(
                """INSERT INTO media_visual_vectors_vec_v2(
                       vector_id,embedding,scope_key
                   ) VALUES (?,?,?)""",
                (
                    row["vector_id"],
                    row["embedding"],
                    self._visual_scope_key(
                        row["vector_space_id"],
                        row["book_id"],
                    ),
                ),
            )
        return (
            pointer["active_space_id"]
            if pointer is not None
            else VISUAL_VECTOR_SPACE
        )

    def init_index(self) -> None:
        conn = self._conn()
        try:
            schemas = {
                row["name"]: (row["sql"] or "").lower()
                for row in conn.execute(
                    "SELECT name,sql FROM sqlite_master "
                    "WHERE name IN ('media_visual_vectors_vec','media_caption_vectors_vec')"
                )
            }
            if (
                "media_visual_vectors_vec" in schemas
                and "float[512]" not in schemas["media_visual_vectors_vec"]
            ):
                raise MediaVisionError(
                    "VISUAL_VECTOR_SCHEMA_MISMATCH",
                    "Existing visual media index has an incompatible dimension",
                    409,
                )
            if (
                "media_caption_vectors_vec" in schemas
                and "float[1024]" not in schemas["media_caption_vectors_vec"]
            ):
                raise MediaVisionError(
                    "CAPTION_VECTOR_SCHEMA_MISMATCH",
                    "Existing caption media index has an incompatible dimension",
                    409,
                )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS media_visual_vectors_vec USING vec0(
                    vector_id INTEGER PRIMARY KEY,
                    embedding float[512] distance_metric=cosine,
                    book_id TEXT PARTITION KEY
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS media_caption_vectors_vec USING vec0(
                    vector_id INTEGER PRIMARY KEY,
                    embedding float[1024] distance_metric=cosine,
                    book_id TEXT PARTITION KEY
                )
                """
            )
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS media_visual_spaces(
                    space_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    model_hash TEXT NOT NULL,
                    package_id TEXT NOT NULL,
                    package_version TEXT NOT NULL,
                    image_preprocess_version TEXT NOT NULL,
                    query_template_version TEXT NOT NULL,
                    pooling TEXT NOT NULL,
                    precision TEXT NOT NULL,
                    dimensions INTEGER NOT NULL CHECK(dimensions=512),
                    normalization TEXT NOT NULL,
                    distance_metric TEXT NOT NULL,
                    runtime TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    source_revision_hash TEXT NOT NULL,
                    source_asset_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN (
                        'building','validating','ready','active','retired','failed'
                    )),
                    source_space_id TEXT,
                    stale INTEGER NOT NULL DEFAULT 0,
                    failure_code TEXT,
                    created_at TEXT NOT NULL,
                    validated_at TEXT,
                    activated_at TEXT,
                    retired_at TEXT,
                    FOREIGN KEY(source_space_id)
                        REFERENCES media_visual_spaces(space_id)
                );
                CREATE INDEX IF NOT EXISTS idx_media_visual_spaces_status
                ON media_visual_spaces(status,created_at DESC);
                CREATE TABLE IF NOT EXISTS media_visual_space_pointer(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    active_space_id TEXT NOT NULL,
                    rollback_space_id TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(active_space_id)
                        REFERENCES media_visual_spaces(space_id),
                    FOREIGN KEY(rollback_space_id)
                        REFERENCES media_visual_spaces(space_id)
                );
                CREATE TABLE IF NOT EXISTS media_vision_migration_tasks(
                    task_id TEXT PRIMARY KEY,
                    target_space_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'queued','running','completed','partial_failed',
                        'failed','cancelled'
                    )),
                    requested_backend TEXT NOT NULL DEFAULT 'auto',
                    total_items INTEGER NOT NULL DEFAULT 0,
                    processed_items INTEGER NOT NULL DEFAULT 0,
                    successful_items INTEGER NOT NULL DEFAULT 0,
                    failed_items INTEGER NOT NULL DEFAULT 0,
                    stale_items INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    heartbeat_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(target_space_id)
                        REFERENCES media_visual_spaces(space_id)
                );
                CREATE INDEX IF NOT EXISTS idx_media_vision_migrations_status
                ON media_vision_migration_tasks(status,created_at DESC);
                CREATE TABLE IF NOT EXISTS media_vision_migration_items(
                    task_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    source_version_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'queued','running','completed','failed','stale','cancelled'
                    )),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(task_id,asset_id),
                    FOREIGN KEY(task_id)
                        REFERENCES media_vision_migration_tasks(task_id)
                        ON DELETE CASCADE
                );
                """
            )
            current_v2 = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE name='media_visual_vectors_vec_v2'"
            ).fetchone()
            if current_v2 and "float[512]" not in (
                current_v2["sql"] or ""
            ).lower():
                raise MediaVisionError(
                    "VISUAL_VECTOR_SCHEMA_MISMATCH",
                    "Existing versioned visual index has an incompatible dimension",
                    409,
                )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS media_visual_vectors_vec_v2
                USING vec0(
                    vector_id INTEGER PRIMARY KEY,
                    embedding float[512] distance_metric=cosine,
                    scope_key TEXT PARTITION KEY
                )
                """
            )
            self._bootstrap_visual_space(
                conn,
                _status_dict(self.vision.status()),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _caption_text(conn: sqlite3.Connection, asset_id: str) -> tuple[str, list[str]]:
        rows = conn.execute(
            "SELECT annotation_id,payload_json FROM media_annotations "
            "WHERE asset_id=? AND approval_status='approved' "
            "AND annotation_type IN ('caption','description','alt_text','image_caption') "
            "ORDER BY created_at,annotation_id",
            (asset_id,),
        ).fetchall()
        texts: list[str] = []
        annotation_ids: list[str] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                continue
            candidates = [
                payload.get("text"),
                payload.get("caption"),
                payload.get("description"),
                payload.get("alt_text"),
            ]
            if isinstance(payload.get("captions"), list):
                candidates.extend(payload["captions"])
            accepted = [
                value.strip()[:4000]
                for value in candidates
                if isinstance(value, str) and value.strip()
            ]
            if accepted:
                texts.extend(accepted)
                annotation_ids.append(row["annotation_id"])
            if sum(len(item) for item in texts) >= 12_000:
                break
        joined = "\n".join(texts)
        return joined[:12_000], annotation_ids

    @staticmethod
    def _latest_version(conn: sqlite3.Connection, asset_id: str) -> dict:
        row = conn.execute(
            "SELECT * FROM media_asset_versions WHERE asset_id=? "
            "ORDER BY version_number DESC LIMIT 1",
            (asset_id,),
        ).fetchone()
        if row is None:
            raise MediaVisionError(
                "MEDIA_VERSION_NOT_FOUND",
                "Media asset has no indexable version",
                409,
            )
        return dict(row)

    @staticmethod
    def _delete_existing(
        conn: sqlite3.Connection,
        asset_id: str,
        *,
        channel: str,
        vector_space_id: str,
    ) -> None:
        rows = conn.execute(
            """SELECT vector_id,channel,vector_space_id
                 FROM media_vector_records
                WHERE asset_id=? AND channel=? AND vector_space_id=?""",
            (asset_id, channel, vector_space_id),
        ).fetchall()
        for row in rows:
            if row["channel"] == "visual":
                conn.execute(
                    "DELETE FROM media_visual_vectors_vec_v2 WHERE vector_id=?",
                    (row["vector_id"],),
                )
                if row["vector_space_id"] == VISUAL_VECTOR_SPACE:
                    conn.execute(
                        "DELETE FROM media_visual_vectors_vec WHERE vector_id=?",
                        (row["vector_id"],),
                    )
            else:
                conn.execute(
                    "DELETE FROM media_caption_vectors_vec WHERE vector_id=?",
                    (row["vector_id"],),
                )
        conn.execute(
            """DELETE FROM media_vector_records
                WHERE asset_id=? AND channel=? AND vector_space_id=?""",
            (asset_id, channel, vector_space_id),
        )

    @staticmethod
    def _insert_vector(
        conn: sqlite3.Connection,
        *,
        asset: dict,
        version: dict,
        channel: str,
        vector_space_id: str,
        model_id: str,
        model_revision: str,
        source_hash: str,
        annotation_ids: list[str],
        vector: list[float],
    ) -> int:
        dimensions = VISUAL_DIMS if channel == "visual" else CAPTION_DIMS
        cursor = conn.execute(
            """
            INSERT INTO media_vector_records(
                asset_id,version_id,database_id,book_id,channel,vector_space_id,
                model_id,model_revision,source_hash,source_annotation_ids_json,
                dimensions,normalized
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                asset["asset_id"],
                version["version_id"],
                asset["database_id"],
                asset["book_id"],
                channel,
                vector_space_id,
                model_id,
                model_revision,
                source_hash,
                json.dumps(annotation_ids, ensure_ascii=True, separators=(",", ":")),
                dimensions,
            ),
        )
        serialized = sqlite_vec.serialize_float32(vector)
        if channel == "visual":
            conn.execute(
                """INSERT INTO media_visual_vectors_vec_v2(
                       vector_id,embedding,scope_key
                   ) VALUES (?,?,?)""",
                (
                    cursor.lastrowid,
                    serialized,
                    MediaVisionIndex._visual_scope_key(
                        vector_space_id,
                        asset["book_id"],
                    ),
                ),
            )
            if vector_space_id == VISUAL_VECTOR_SPACE:
                conn.execute(
                    """INSERT INTO media_visual_vectors_vec(
                           vector_id,embedding,book_id
                       ) VALUES (?,?,?)""",
                    (cursor.lastrowid, serialized, asset["book_id"]),
                )
        else:
            conn.execute(
                """INSERT INTO media_caption_vectors_vec(
                       vector_id,embedding,book_id
                   ) VALUES (?,?,?)""",
                (cursor.lastrowid, serialized, asset["book_id"]),
            )
        return int(cursor.lastrowid)

    def _require_local_caption_provider(self) -> EmbeddingProvider:
        if self.caption is None or not getattr(self.caption, "is_aetherdb_local", False):
            raise MediaVisionError(
                "LOCAL_CAPTION_EMBEDDING_UNAVAILABLE",
                "The local BGE-M3 caption embedding runtime is unavailable",
                503,
            )
        return self.caption

    @staticmethod
    def _require_visual_space(conn: sqlite3.Connection, space_id: str):
        row = conn.execute(
            "SELECT * FROM media_visual_spaces WHERE space_id=?",
            (space_id,),
        ).fetchone()
        if row is None:
            raise MediaVisionError(
                "VISUAL_SPACE_NOT_FOUND",
                "Visual vector space was not found",
                404,
            )
        return row

    def active_visual_space_id(self) -> str:
        self.init_index()
        conn = self._conn()
        try:
            pointer = conn.execute(
                "SELECT active_space_id FROM media_visual_space_pointer WHERE id=1"
            ).fetchone()
            if pointer is None:
                raise MediaVisionError(
                    "VISUAL_SPACE_POINTER_MISSING",
                    "Visual vector-space pointer is not initialized",
                    500,
                )
            return pointer["active_space_id"]
        finally:
            conn.close()

    def list_visual_spaces(self) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            pointer = conn.execute(
                "SELECT * FROM media_visual_space_pointer WHERE id=1"
            ).fetchone()
            current_revision, current_count = self._visual_source_revision(conn)
            rows = conn.execute(
                """SELECT s.*,
                          (SELECT COUNT(*)
                             FROM media_vector_records r
                            WHERE r.channel='visual'
                              AND r.vector_space_id=s.space_id) AS record_count,
                          (SELECT COUNT(*)
                             FROM media_visual_vectors_vec_v2 v
                             JOIN media_vector_records r
                               ON r.vector_id=v.vector_id
                            WHERE r.vector_space_id=s.space_id
                              AND r.channel='visual') AS vector_count
                     FROM media_visual_spaces s
                    ORDER BY s.created_at DESC,s.space_id DESC"""
            ).fetchall()
            spaces = []
            for row in rows:
                item = dict(row)
                item["is_source_current"] = bool(
                    item["source_revision_hash"] == current_revision
                    and int(item["source_asset_count"]) == current_count
                )
                item["stale"] = bool(item["stale"] or not item["is_source_current"])
                spaces.append(item)
            return {
                "active_space_id": pointer["active_space_id"] if pointer else None,
                "rollback_space_id": (
                    pointer["rollback_space_id"] if pointer else None
                ),
                "current_source_revision_hash": current_revision,
                "current_source_asset_count": current_count,
                "spaces": spaces,
            }
        finally:
            conn.close()

    def create_visual_space(self) -> dict:
        self.init_index()
        runtime = _status_dict(self.vision.status())
        if not runtime.get("available"):
            raise MediaVisionError(
                "VISION_PACKAGE_UNAVAILABLE",
                "The verified BGE-VL model package is not installed and enabled",
                503,
            )
        if int(runtime.get("dimensions") or 0) != VISUAL_DIMS:
            raise MediaVisionError(
                "VISUAL_VECTOR_SCHEMA_MISMATCH",
                "BGE-VL runtime dimensions do not match the visual index",
                409,
            )
        manifest, manifest_hash = self._visual_manifest(runtime)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            pointer = conn.execute(
                "SELECT active_space_id FROM media_visual_space_pointer WHERE id=1"
            ).fetchone()
            source_revision_hash, source_asset_count = self._visual_source_revision(
                conn
            )
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            space_id = f"vspace_visual_{uuid.uuid4().hex}"
            conn.execute(
                """INSERT INTO media_visual_spaces(
                       space_id,model_id,model_revision,model_hash,package_id,
                       package_version,image_preprocess_version,
                       query_template_version,pooling,precision,dimensions,
                       normalization,distance_metric,runtime,manifest_hash,
                       source_revision_hash,source_asset_count,status,
                       source_space_id,stale,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'building',?,0,?)""",
                (
                    space_id,
                    manifest["model_id"],
                    manifest["model_revision"],
                    manifest["model_hash"],
                    manifest["package_id"],
                    manifest["package_version"],
                    manifest["image_preprocess_version"],
                    manifest["query_template_version"],
                    manifest["pooling"],
                    manifest["precision"],
                    manifest["dimensions"],
                    manifest["normalization"],
                    manifest["distance_metric"],
                    manifest["runtime"],
                    manifest_hash,
                    source_revision_hash,
                    source_asset_count,
                    pointer["active_space_id"] if pointer else None,
                    now,
                ),
            )
            conn.commit()
            return dict(self._require_visual_space(conn, space_id))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_visual_space_failed(
        self,
        space_id: str,
        failure_code: str,
        *,
        stale: bool = False,
    ) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            space = self._require_visual_space(conn, space_id)
            if space["status"] in {"active", "retired"}:
                raise MediaVisionError(
                    "VISUAL_SPACE_STATE_INVALID",
                    "Active or retired visual spaces cannot be marked failed",
                    409,
                )
            conn.execute(
                """UPDATE media_visual_spaces
                      SET status='failed',failure_code=?,stale=?
                    WHERE space_id=?""",
                (failure_code[:96], int(stale), space_id),
            )
            conn.commit()
            return dict(self._require_visual_space(conn, space_id))
        finally:
            conn.close()

    def validate_visual_space(self, space_id: str) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            space = self._require_visual_space(conn, space_id)
            if space["status"] not in {"building", "ready", "failed"}:
                raise MediaVisionError(
                    "VISUAL_SPACE_STATE_INVALID",
                    "Visual space is not available for validation",
                    409,
                )
            conn.execute(
                """UPDATE media_visual_spaces
                      SET status='validating',failure_code=NULL
                    WHERE space_id=?""",
                (space_id,),
            )
            current_revision, current_count = self._visual_source_revision(conn)
            record_count = conn.execute(
                """SELECT COUNT(*) FROM media_vector_records
                    WHERE channel='visual' AND vector_space_id=?""",
                (space_id,),
            ).fetchone()[0]
            vector_count = conn.execute(
                """SELECT COUNT(*)
                     FROM media_visual_vectors_vec_v2 v
                     JOIN media_vector_records r ON r.vector_id=v.vector_id
                    WHERE r.channel='visual' AND r.vector_space_id=?""",
                (space_id,),
            ).fetchone()[0]
            current_record_count = conn.execute(
                """SELECT COUNT(*)
                     FROM media_vector_records r
                     JOIN media_assets a ON a.asset_id=r.asset_id
                     JOIN media_asset_versions v ON v.version_id=r.version_id
                    WHERE r.channel='visual' AND r.vector_space_id=?
                      AND a.modality='image'
                      AND a.lifecycle_status NOT IN ('soft_deleted','rejected')
                      AND r.source_hash=a.content_hash
                      AND v.content_hash=a.content_hash""",
                (space_id,),
            ).fetchone()[0]
            failure_code = None
            stale = False
            if record_count != vector_count:
                failure_code = "VECTOR_COUNT_MISMATCH"
            elif (
                current_revision != space["source_revision_hash"]
                or current_count != int(space["source_asset_count"])
            ):
                failure_code = "SOURCE_REVISION_CHANGED"
                stale = True
            elif record_count != current_count or current_record_count != current_count:
                failure_code = "ASSET_COVERAGE_MISMATCH"
            elif record_count:
                sample = conn.execute(
                    """SELECT v.embedding,r.book_id
                         FROM media_visual_vectors_vec_v2 v
                         JOIN media_vector_records r ON r.vector_id=v.vector_id
                        WHERE r.channel='visual' AND r.vector_space_id=?
                        LIMIT 1""",
                    (space_id,),
                ).fetchone()
                matched = conn.execute(
                    """SELECT vector_id
                         FROM media_visual_vectors_vec_v2
                        WHERE embedding MATCH ? AND k=1 AND scope_key=?""",
                    (
                        sample["embedding"],
                        self._visual_scope_key(space_id, sample["book_id"]),
                    ),
                ).fetchone()
                if matched is None:
                    failure_code = "VECTOR_SAMPLE_QUERY_FAILED"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if failure_code:
                conn.execute(
                    """UPDATE media_visual_spaces
                          SET status='failed',failure_code=?,stale=?
                        WHERE space_id=?""",
                    (failure_code, int(stale), space_id),
                )
            else:
                conn.execute(
                    """UPDATE media_visual_spaces
                          SET status='ready',failure_code=NULL,stale=0,
                              validated_at=?
                        WHERE space_id=?""",
                    (now, space_id),
                )
            conn.commit()
            result = dict(self._require_visual_space(conn, space_id))
            result.update(
                {
                    "valid": failure_code is None,
                    "record_count": record_count,
                    "vector_count": vector_count,
                    "current_record_count": current_record_count,
                    "current_source_revision_hash": current_revision,
                    "current_source_asset_count": current_count,
                }
            )
            return result
        except sqlite3.Error as exc:
            conn.rollback()
            raise MediaVisionError(
                "VISUAL_SPACE_VALIDATION_FAILED",
                "Visual vector-space validation could not complete",
                500,
            ) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def activate_visual_space(self, space_id: str) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = self._require_visual_space(conn, space_id)
            if target["status"] != "ready":
                raise MediaVisionError(
                    "VISUAL_SPACE_NOT_READY",
                    "Only a validated visual space can be activated",
                    409,
                )
            pointer = conn.execute(
                "SELECT * FROM media_visual_space_pointer WHERE id=1"
            ).fetchone()
            old_active = pointer["active_space_id"]
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                """UPDATE media_visual_spaces
                      SET status='retired',retired_at=?
                    WHERE space_id=? AND status='active'""",
                (now, old_active),
            )
            conn.execute(
                """UPDATE media_visual_spaces
                      SET status='active',activated_at=?,retired_at=NULL
                    WHERE space_id=?""",
                (now, space_id),
            )
            conn.execute(
                """UPDATE media_visual_space_pointer
                      SET active_space_id=?,rollback_space_id=?,updated_at=?
                    WHERE id=1""",
                (space_id, old_active, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.list_visual_spaces()

    def rollback_visual_space(self) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            pointer = conn.execute(
                "SELECT * FROM media_visual_space_pointer WHERE id=1"
            ).fetchone()
            if pointer is None or not pointer["rollback_space_id"]:
                raise MediaVisionError(
                    "VISUAL_SPACE_ROLLBACK_UNAVAILABLE",
                    "No rollback visual space is available",
                    409,
                )
            current_id = pointer["active_space_id"]
            rollback_id = pointer["rollback_space_id"]
            target = self._require_visual_space(conn, rollback_id)
            if target["status"] not in {"retired", "ready"}:
                raise MediaVisionError(
                    "VISUAL_SPACE_ROLLBACK_UNAVAILABLE",
                    "Rollback visual space is not available",
                    409,
                )
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                """UPDATE media_visual_spaces
                      SET status='retired',retired_at=?
                    WHERE space_id=?""",
                (now, current_id),
            )
            conn.execute(
                """UPDATE media_visual_spaces
                      SET status='active',activated_at=?,retired_at=NULL
                    WHERE space_id=?""",
                (now, rollback_id),
            )
            conn.execute(
                """UPDATE media_visual_space_pointer
                      SET active_space_id=?,rollback_space_id=?,updated_at=?
                    WHERE id=1""",
                (rollback_id, current_id, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.list_visual_spaces()

    def garbage_collect_visual_space(
        self,
        space_id: str,
        *,
        confirm_space_id: str,
    ) -> dict:
        if confirm_space_id != space_id:
            raise MediaVisionError(
                "VISUAL_SPACE_GC_CONFIRMATION_MISMATCH",
                "Visual space garbage-collection confirmation does not match",
                409,
            )
        self.init_index()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            pointer = conn.execute(
                "SELECT * FROM media_visual_space_pointer WHERE id=1"
            ).fetchone()
            if space_id in {
                pointer["active_space_id"],
                pointer["rollback_space_id"],
            }:
                raise MediaVisionError(
                    "VISUAL_SPACE_PROTECTED",
                    "Active or rollback visual spaces cannot be collected",
                    409,
                )
            task_ref = conn.execute(
                """SELECT task_id FROM media_vision_migration_tasks
                    WHERE target_space_id=?
                      AND status IN ('queued','running')
                    LIMIT 1""",
                (space_id,),
            ).fetchone()
            if task_ref is not None:
                raise MediaVisionError(
                    "VISUAL_SPACE_TASK_REFERENCE",
                    "A running migration task still references this visual space",
                    409,
                )
            space = self._require_visual_space(conn, space_id)
            if space["status"] not in {"retired", "failed"}:
                raise MediaVisionError(
                    "VISUAL_SPACE_STATE_INVALID",
                    "Only retired or failed visual spaces can be collected",
                    409,
                )
            vector_ids = [
                row[0]
                for row in conn.execute(
                    """SELECT vector_id FROM media_vector_records
                        WHERE channel='visual' AND vector_space_id=?""",
                    (space_id,),
                )
            ]
            conn.executemany(
                "DELETE FROM media_visual_vectors_vec_v2 WHERE vector_id=?",
                ((vector_id,) for vector_id in vector_ids),
            )
            if space_id == VISUAL_VECTOR_SPACE:
                conn.executemany(
                    "DELETE FROM media_visual_vectors_vec WHERE vector_id=?",
                    ((vector_id,) for vector_id in vector_ids),
                )
            conn.execute(
                """DELETE FROM media_vector_records
                    WHERE channel='visual' AND vector_space_id=?""",
                (space_id,),
            )
            conn.execute(
                "UPDATE media_visual_spaces SET source_space_id=NULL "
                "WHERE source_space_id=?",
                (space_id,),
            )
            conn.execute(
                "DELETE FROM media_vision_migration_tasks "
                "WHERE target_space_id=?",
                (space_id,),
            )
            conn.execute(
                "DELETE FROM media_visual_spaces WHERE space_id=?",
                (space_id,),
            )
            conn.commit()
            return {
                "space_id": space_id,
                "deleted": True,
                "deleted_vector_count": len(vector_ids),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _public_migration_task(
        conn: sqlite3.Connection,
        row,
        *,
        include_items: bool = False,
    ) -> dict:
        task = dict(row)
        task["cancel_requested"] = bool(task["cancel_requested"])
        if include_items:
            task["items"] = [
                dict(item)
                for item in conn.execute(
                    """SELECT asset_id,source_version_id,status,attempts,
                              error_code,updated_at
                         FROM media_vision_migration_items
                        WHERE task_id=?
                        ORDER BY asset_id""",
                    (task["task_id"],),
                )
            ]
        return task

    def get_migration_task(
        self,
        task_id: str,
        *,
        include_items: bool = True,
    ) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM media_vision_migration_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise MediaVisionError(
                    "VISUAL_MIGRATION_NOT_FOUND",
                    "Visual migration task was not found",
                    404,
                )
            return self._public_migration_task(
                conn,
                row,
                include_items=include_items,
            )
        finally:
            conn.close()

    def list_migration_tasks(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        self.init_index()
        conn = self._conn()
        try:
            where = " WHERE status=?" if status else ""
            params = (status,) if status else ()
            rows = conn.execute(
                "SELECT * FROM media_vision_migration_tasks"
                + where
                + " ORDER BY created_at DESC,task_id DESC LIMIT ?",
                (*params, max(1, min(limit, 500))),
            ).fetchall()
            return [
                self._public_migration_task(conn, row)
                for row in rows
            ]
        finally:
            conn.close()

    def create_migration_task(
        self,
        target_space_id: str,
        *,
        requested_backend: str = "auto",
        start: bool = True,
    ) -> dict:
        self.init_index()
        if requested_backend not in {"auto", "rocm_pytorch", "cuda", "cpu"}:
            raise MediaVisionError(
                "VISUAL_BACKEND_INVALID",
                "Visual migration backend is invalid",
                422,
            )
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = self._require_visual_space(conn, target_space_id)
            if target["status"] != "building":
                raise MediaVisionError(
                    "VISUAL_SPACE_NOT_BUILDABLE",
                    "Visual migration requires a building target space",
                    409,
                )
            current_revision, current_count = self._visual_source_revision(conn)
            if (
                current_revision != target["source_revision_hash"]
                or current_count != int(target["source_asset_count"])
            ):
                conn.execute(
                    """UPDATE media_visual_spaces
                          SET status='failed',failure_code='SOURCE_REVISION_CHANGED',
                              stale=1
                        WHERE space_id=?""",
                    (target_space_id,),
                )
                conn.commit()
                raise MediaVisionError(
                    "VISUAL_MIGRATION_SOURCE_STALE",
                    "Media sources changed before the migration could start",
                    409,
                )
            existing = conn.execute(
                """SELECT * FROM media_vision_migration_tasks
                    WHERE target_space_id=? AND status IN ('queued','running')
                    ORDER BY created_at DESC LIMIT 1""",
                (target_space_id,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                task = self._public_migration_task(conn, existing)
            else:
                assets = conn.execute(
                    """SELECT a.asset_id,a.content_hash,v.version_id
                         FROM media_assets a
                         JOIN media_asset_versions v ON v.asset_id=a.asset_id
                        WHERE a.modality='image'
                          AND a.lifecycle_status NOT IN ('soft_deleted','rejected')
                          AND v.version_number=(
                              SELECT MAX(v2.version_number)
                                FROM media_asset_versions v2
                               WHERE v2.asset_id=a.asset_id
                          )
                        ORDER BY a.asset_id"""
                ).fetchall()
                task_id = f"vision_migration_{uuid.uuid4().hex}"
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                conn.execute(
                    """INSERT INTO media_vision_migration_tasks(
                           task_id,target_space_id,status,requested_backend,
                           total_items,created_at,updated_at
                       ) VALUES (?,?,'queued',?,?,?,?)""",
                    (
                        task_id,
                        target_space_id,
                        requested_backend,
                        len(assets),
                        now,
                        now,
                    ),
                )
                conn.executemany(
                    """INSERT INTO media_vision_migration_items(
                           task_id,asset_id,source_version_id,source_hash,
                           status,updated_at
                       ) VALUES (?,?,?,?,'queued',?)""",
                    (
                        (
                            task_id,
                            row["asset_id"],
                            row["version_id"],
                            row["content_hash"],
                            now,
                        )
                        for row in assets
                    ),
                )
                conn.commit()
                task = self.get_migration_task(
                    task_id,
                    include_items=False,
                )
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
        if start:
            _submit_visual_migration(self.database_id, task["task_id"])
        return task

    def cancel_migration_task(self, task_id: str) -> dict:
        task = self.get_migration_task(task_id, include_items=False)
        if task["status"] in VISUAL_MIGRATION_TERMINAL:
            return self.get_migration_task(task_id)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = self._conn()
        try:
            conn.execute(
                """UPDATE media_vision_migration_tasks
                      SET cancel_requested=1,updated_at=?
                    WHERE task_id=?""",
                (now, task_id),
            )
            if task["status"] == "queued":
                conn.execute(
                    """UPDATE media_vision_migration_items
                          SET status='cancelled',updated_at=?
                        WHERE task_id=? AND status='queued'""",
                    (now, task_id),
                )
                conn.execute(
                    """UPDATE media_vision_migration_tasks
                          SET status='cancelled',processed_items=total_items,
                              error_code='USER_CANCELLED',completed_at=?,updated_at=?
                        WHERE task_id=?""",
                    (now, now, task_id),
                )
                conn.execute(
                    """UPDATE media_visual_spaces
                          SET status='failed',failure_code='BUILD_CANCELLED'
                        WHERE space_id=? AND status='building'""",
                    (task["target_space_id"],),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_migration_task(task_id)

    def retry_migration_task(
        self,
        task_id: str,
        *,
        start: bool = True,
    ) -> dict:
        task = self.get_migration_task(task_id, include_items=False)
        if task["status"] not in {"failed", "partial_failed", "cancelled"}:
            raise MediaVisionError(
                "VISUAL_MIGRATION_NOT_RETRYABLE",
                "Visual migration task is not retryable",
                409,
            )
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = self._require_visual_space(conn, task["target_space_id"])
            current_revision, current_count = self._visual_source_revision(conn)
            if (
                target["stale"]
                or current_revision != target["source_revision_hash"]
                or current_count != int(target["source_asset_count"])
            ):
                raise MediaVisionError(
                    "VISUAL_MIGRATION_SOURCE_STALE",
                    "A stale migration requires a new visual space",
                    409,
                )
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            retryable = conn.execute(
                """SELECT COUNT(*) FROM media_vision_migration_items
                    WHERE task_id=? AND status IN ('failed','cancelled')""",
                (task_id,),
            ).fetchone()[0]
            if not retryable:
                raise MediaVisionError(
                    "VISUAL_MIGRATION_NOT_RETRYABLE",
                    "Visual migration has no retryable items",
                    409,
                )
            conn.execute(
                """UPDATE media_vision_migration_items
                      SET status='queued',error_code=NULL,updated_at=?
                    WHERE task_id=? AND status IN ('failed','cancelled')""",
                (now, task_id),
            )
            conn.execute(
                """UPDATE media_vision_migration_tasks
                      SET status='queued',cancel_requested=0,error_code=NULL,
                          completed_at=NULL,updated_at=?
                    WHERE task_id=?""",
                (now, task_id),
            )
            conn.execute(
                """UPDATE media_visual_spaces
                      SET status='building',failure_code=NULL
                    WHERE space_id=? AND status='failed'""",
                (task["target_space_id"],),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if start:
            _submit_visual_migration(self.database_id, task_id)
        return self.get_migration_task(task_id)

    def run_migration_task(self, task_id: str) -> dict:
        task = self.get_migration_task(task_id, include_items=False)
        if task["status"] in VISUAL_MIGRATION_TERMINAL:
            return self.get_migration_task(task_id)
        started_monotonic = time.monotonic()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = self._conn()
        try:
            conn.execute(
                """UPDATE media_vision_migration_tasks
                      SET status='running',started_at=COALESCE(started_at,?),
                          heartbeat_at=?,updated_at=?
                    WHERE task_id=? AND status='queued'""",
                (now, now, now, task_id),
            )
            conn.commit()
        finally:
            conn.close()

        timed_out = False
        while True:
            task = self.get_migration_task(task_id, include_items=False)
            if task["cancel_requested"]:
                self.cancel_migration_task(task_id)
                break
            if (
                time.monotonic() - started_monotonic
                >= VISUAL_MIGRATION_ABSOLUTE_TIMEOUT_SECONDS
            ):
                timed_out = True
                break
            conn = self._conn()
            try:
                item = conn.execute(
                    """SELECT * FROM media_vision_migration_items
                        WHERE task_id=? AND status='queued'
                        ORDER BY asset_id LIMIT 1""",
                    (task_id,),
                ).fetchone()
                if item is not None:
                    heartbeat = datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    conn.execute(
                        """UPDATE media_vision_migration_items
                              SET status='running',attempts=attempts+1,updated_at=?
                            WHERE task_id=? AND asset_id=? AND status='queued'""",
                        (heartbeat, task_id, item["asset_id"]),
                    )
                    conn.execute(
                        """UPDATE media_vision_migration_tasks
                              SET heartbeat_at=?,updated_at=?
                            WHERE task_id=?""",
                        (heartbeat, heartbeat, task_id),
                    )
                    conn.commit()
            finally:
                conn.close()
            if item is None:
                break
            item_status = "completed"
            error_code = None
            try:
                self.index_asset(
                    item["asset_id"],
                    requested_backend=task["requested_backend"],
                    include_caption=False,
                    visual_space_id=task["target_space_id"],
                    expected_version_id=item["source_version_id"],
                    expected_source_hash=item["source_hash"],
                )
            except MediaVisionError as exc:
                item_status = (
                    "stale"
                    if exc.code == "VISUAL_MIGRATION_SOURCE_STALE"
                    else "failed"
                )
                error_code = exc.code
            except Exception as exc:
                item_status = "failed"
                error_code = type(exc).__name__[:96]
            update_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn = self._conn()
            try:
                conn.execute(
                    """UPDATE media_vision_migration_items
                          SET status=?,error_code=?,updated_at=?
                        WHERE task_id=? AND asset_id=?""",
                    (
                        item_status,
                        error_code,
                        update_time,
                        task_id,
                        item["asset_id"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        conn = self._conn()
        try:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if timed_out:
                conn.execute(
                    """UPDATE media_vision_migration_items
                          SET status='failed',error_code='MIGRATION_TIMEOUT',
                              updated_at=?
                        WHERE task_id=? AND status IN ('queued','running')""",
                    (now, task_id),
                )
            task = conn.execute(
                "SELECT * FROM media_vision_migration_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if task["cancel_requested"]:
                conn.execute(
                    """UPDATE media_vision_migration_items
                          SET status='cancelled',updated_at=?
                        WHERE task_id=? AND status IN ('queued','running')""",
                    (now, task_id),
                )
            counts = dict(
                conn.execute(
                    """SELECT status,COUNT(*)
                         FROM media_vision_migration_items
                        WHERE task_id=? GROUP BY status""",
                    (task_id,),
                )
            )
            if task["cancel_requested"]:
                final_status = "cancelled"
                final_code = "USER_CANCELLED"
            elif timed_out:
                final_status = "failed"
                final_code = "MIGRATION_TIMEOUT"
            elif counts.get("failed", 0) or counts.get("stale", 0):
                final_status = (
                    "partial_failed"
                    if counts.get("completed", 0)
                    else "failed"
                )
                final_code = (
                    "SOURCE_REVISION_CHANGED"
                    if counts.get("stale", 0)
                    else "ITEM_FAILURES"
                )
            else:
                final_status = "completed"
                final_code = None
            processed = sum(
                counts.get(name, 0)
                for name in (
                    "completed",
                    "failed",
                    "stale",
                    "cancelled",
                )
            )
            conn.execute(
                """UPDATE media_vision_migration_tasks
                      SET status=?,processed_items=?,successful_items=?,
                          failed_items=?,stale_items=?,error_code=?,
                          heartbeat_at=?,completed_at=?,updated_at=?
                    WHERE task_id=?""",
                (
                    final_status,
                    processed,
                    counts.get("completed", 0),
                    counts.get("failed", 0),
                    counts.get("stale", 0),
                    final_code,
                    now,
                    now,
                    now,
                    task_id,
                ),
            )
            if final_status != "completed":
                conn.execute(
                    """UPDATE media_visual_spaces
                          SET status='failed',failure_code=?,stale=?
                        WHERE space_id=?
                          AND status IN ('building','validating','ready','failed')""",
                    (
                        final_code or "BUILD_FAILED",
                        int(bool(counts.get("stale", 0))),
                        task["target_space_id"],
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_migration_task(task_id)

    def index_asset(
        self,
        asset_id: str,
        *,
        requested_backend: str = "auto",
        include_caption: bool = True,
        visual_space_id: str | None = None,
        expected_version_id: str | None = None,
        expected_source_hash: str | None = None,
    ) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            pointer = conn.execute(
                "SELECT active_space_id FROM media_visual_space_pointer WHERE id=1"
            ).fetchone()
            selected_space_id = visual_space_id or pointer["active_space_id"]
            selected_space = dict(
                self._require_visual_space(conn, selected_space_id)
            )
        finally:
            conn.close()
        if selected_space["status"] not in {"building", "active"}:
            raise MediaVisionError(
                "VISUAL_SPACE_NOT_WRITABLE",
                "Visual vectors can only be written to a building or active space",
                409,
            )
        try:
            asset = get_media_asset(self.database_id, asset_id, include_related=False)
            path, _ = get_media_content(self.database_id, asset_id)
        except MediaAssetError as exc:
            raise MediaVisionError(exc.code, exc.message, exc.status_code) from exc
        if asset["modality"] != "image":
            raise MediaVisionError(
                "ASSET_NOT_IMAGE",
                "Only image assets can enter the visual index",
                409,
            )
        if asset["lifecycle_status"] in {"soft_deleted", "rejected"}:
            raise MediaVisionError(
                "ASSET_NOT_INDEXABLE",
                "Deleted or rejected assets cannot enter the visual index",
                409,
            )

        visual_status = _status_dict(self.vision.status())
        if not visual_status.get("available"):
            raise MediaVisionError(
                "VISION_PACKAGE_UNAVAILABLE",
                "The verified BGE-VL model package is not installed and enabled",
                503,
            )
        runtime_manifest, runtime_manifest_hash = self._visual_manifest(visual_status)
        if (
            selected_space["manifest_hash"] != runtime_manifest_hash
            or selected_space["model_id"] != runtime_manifest["model_id"]
            or selected_space["model_revision"]
            != runtime_manifest["model_revision"]
        ):
            raise MediaVisionError(
                "VISUAL_SPACE_RUNTIME_MISMATCH",
                "BGE-VL runtime does not match the target visual space",
                409,
            )
        visual = _normalize(
            self.vision.embed_image(
                path,
                asset["content_hash"],
                requested_backend=requested_backend,
            ),
            VISUAL_DIMS,
        )

        conn = self._conn()
        try:
            version = self._latest_version(conn, asset_id)
            caption_text, annotation_ids = self._caption_text(conn, asset_id)
        finally:
            conn.close()
        if (
            (expected_version_id and version["version_id"] != expected_version_id)
            or (
                expected_source_hash
                and asset["content_hash"] != expected_source_hash
            )
        ):
            raise MediaVisionError(
                "VISUAL_MIGRATION_SOURCE_STALE",
                "Media source changed while the visual migration was running",
                409,
            )

        caption_vector = None
        caption_status = {"used": False, "reason": "no_approved_caption"}
        caption_runtime = None
        if include_caption and caption_text:
            provider = self._require_local_caption_provider()
            runtime_status = _status_dict(provider.status())
            if not runtime_status.get("available"):
                raise MediaVisionError(
                    "LOCAL_CAPTION_EMBEDDING_UNAVAILABLE",
                    "The local BGE-M3 caption embedding runtime is unavailable",
                    503,
                )
            caption_vector = _normalize(provider.embed(caption_text), CAPTION_DIMS)
            caption_runtime = runtime_status
            caption_status = {
                "used": True,
                "annotation_count": len(annotation_ids),
            }
        elif not include_caption:
            caption_status = {"used": False, "reason": "disabled_by_request"}

        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current_asset = conn.execute(
                "SELECT content_hash,lifecycle_status FROM media_assets WHERE asset_id=?",
                (asset_id,),
            ).fetchone()
            current_version = self._latest_version(conn, asset_id)
            if (
                current_asset is None
                or current_asset["lifecycle_status"] in {"soft_deleted", "rejected"}
                or current_asset["content_hash"] != asset["content_hash"]
                or current_version["version_id"] != version["version_id"]
                or (
                    expected_version_id
                    and current_version["version_id"] != expected_version_id
                )
                or (
                    expected_source_hash
                    and current_asset["content_hash"] != expected_source_hash
                )
            ):
                raise MediaVisionError(
                    "VISUAL_MIGRATION_SOURCE_STALE",
                    "Media source changed while the visual migration was running",
                    409,
                )
            target = self._require_visual_space(conn, selected_space_id)
            if target["status"] not in {"building", "active"}:
                raise MediaVisionError(
                    "VISUAL_SPACE_NOT_WRITABLE",
                    "Target visual space changed state before the write completed",
                    409,
                )
            self._delete_existing(
                conn,
                asset_id,
                channel="visual",
                vector_space_id=selected_space_id,
            )
            visual_id = self._insert_vector(
                conn,
                asset=asset,
                version=version,
                channel="visual",
                vector_space_id=selected_space_id,
                model_id=str(visual_status.get("model_id") or "BAAI/BGE-VL-base"),
                model_revision=str(visual_status.get("revision") or ""),
                source_hash=asset["content_hash"],
                annotation_ids=[],
                vector=visual,
            )
            caption_id = None
            if visual_space_id is None:
                self._delete_existing(
                    conn,
                    asset_id,
                    channel="caption",
                    vector_space_id=CAPTION_VECTOR_SPACE,
                )
            if visual_space_id is None and caption_vector is not None:
                caption_hash = hashlib.sha256(
                    (
                        caption_text
                        + "\0"
                        + "\0".join(annotation_ids)
                    ).encode("utf-8")
                ).hexdigest()
                caption_id = self._insert_vector(
                    conn,
                    asset=asset,
                    version=version,
                    channel="caption",
                    vector_space_id=CAPTION_VECTOR_SPACE,
                    model_id=str(caption_runtime.get("model_id") or "BAAI/bge-m3"),
                    model_revision=str(caption_runtime.get("revision") or ""),
                    source_hash=caption_hash,
                    annotation_ids=annotation_ids,
                    vector=caption_vector,
                )
            if target["status"] == "active":
                source_revision_hash, source_asset_count = (
                    self._visual_source_revision(conn)
                )
                conn.execute(
                    """UPDATE media_visual_spaces
                          SET source_revision_hash=?,source_asset_count=?,stale=0
                        WHERE space_id=?""",
                    (
                        source_revision_hash,
                        source_asset_count,
                        selected_space_id,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {
            "asset_id": asset_id,
            "book_id": asset["book_id"],
            "visual": {
                "indexed": True,
                "vector_record_id": visual_id,
                "vector_space_id": selected_space_id,
                "dimensions": VISUAL_DIMS,
            },
            "caption": {
                **caption_status,
                "indexed": caption_id is not None,
                "vector_record_id": caption_id,
                "vector_space_id": CAPTION_VECTOR_SPACE,
                "dimensions": CAPTION_DIMS,
            },
        }

    def remove_asset(self, asset_id: str) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            count = delete_media_vector_rows(conn, asset_id)
            conn.execute("DELETE FROM media_vector_records WHERE asset_id=?", (asset_id,))
            conn.commit()
            return {"asset_id": asset_id, "removed_vector_records": count}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _channel_search(
        conn: sqlite3.Connection,
        *,
        table: str,
        vector: list[float],
        book_id: str,
        channel: str,
        vector_space_id: str,
        top_k: int,
        lifecycle_statuses: tuple[str, ...],
        target_type: str | None,
        target_id: str | None,
        exclude_asset_id: str | None = None,
    ) -> list[dict]:
        placeholders = ",".join("?" for _ in lifecycle_statuses)
        join = ""
        clauses = [
            "r.channel=?",
            "r.vector_space_id=?",
            f"a.lifecycle_status IN ({placeholders})",
        ]
        if channel == "visual":
            partition_column = "scope_key"
            partition_value = MediaVisionIndex._visual_scope_key(
                vector_space_id,
                book_id,
            )
        else:
            partition_column = "book_id"
            partition_value = book_id
        params: list[object] = [
            sqlite_vec.serialize_float32(vector),
            max(top_k * 3, top_k),
            partition_value,
            channel,
            vector_space_id,
            *lifecycle_statuses,
        ]
        if target_type and target_id:
            join = (
                " JOIN media_asset_bindings b ON b.asset_id=a.asset_id "
                "AND b.database_id=a.database_id AND b.book_id=a.book_id "
            )
            clauses.extend(["b.target_type=?", "b.target_id=?"])
            params.extend([target_type, target_id])
        if exclude_asset_id:
            clauses.append("a.asset_id<>?")
            params.append(exclude_asset_id)
        rows = conn.execute(
            f"""
            WITH knn AS (
                SELECT vector_id,distance FROM {table}
                WHERE embedding MATCH ? AND k=? AND {partition_column}=?
            )
            SELECT r.asset_id,a.original_filename,a.mime_type,a.lifecycle_status,
                   a.book_id,a.content_hash,knn.distance
            FROM knn
            JOIN media_vector_records r ON r.vector_id=knn.vector_id
            JOIN media_assets a ON a.asset_id=r.asset_id
            {join}
            WHERE {' AND '.join(clauses)}
            ORDER BY knn.distance
            """,
            params,
        ).fetchall()
        return [
            {
                "asset_id": row["asset_id"],
                "original_filename": row["original_filename"],
                "mime_type": row["mime_type"],
                "lifecycle_status": row["lifecycle_status"],
                "book_id": row["book_id"],
                "content_hash": row["content_hash"],
                "similarity": max(0.0, 1.0 - float(row["distance"])),
            }
            for row in rows
        ]

    @staticmethod
    def _merge(
        channel_results: dict[str, list[dict]],
        *,
        top_k: int,
        weights: dict[str, float],
    ) -> list[dict]:
        scores: dict[str, float] = {}
        data: dict[str, dict] = {}
        channels: dict[str, dict] = {}
        used = [name for name, rows in channel_results.items() if rows]
        maximum = sum(weights[name] / 61 for name in used) or 1.0
        for channel, rows in channel_results.items():
            seen: set[str] = set()
            for rank, row in enumerate(rows, start=1):
                asset_id = row["asset_id"]
                if asset_id in seen:
                    continue
                seen.add(asset_id)
                data.setdefault(asset_id, row)
                scores[asset_id] = scores.get(asset_id, 0.0) + (
                    weights[channel] / (60 + rank)
                )
                channels.setdefault(asset_id, {})[channel] = {
                    "rank": rank,
                    "similarity": row["similarity"],
                }
        ordered = sorted(scores, key=lambda key: (-scores[key], key))[:top_k]
        return [
            {
                **{
                    key: value
                    for key, value in data[asset_id].items()
                    if key != "similarity"
                },
                "score": round(scores[asset_id] / maximum, 8),
                "channels": channels[asset_id],
            }
            for asset_id in ordered
        ]

    @staticmethod
    def _validate_filters(
        lifecycle_statuses: tuple[str, ...] | None,
        target_type: str | None,
        target_id: str | None,
    ) -> tuple[str, ...]:
        if bool(target_type) != bool(target_id):
            raise MediaVisionError(
                "INCOMPLETE_TARGET_FILTER",
                "Both target_type and target_id are required",
            )
        statuses = lifecycle_statuses or ("approved", "archived")
        if not statuses or not set(statuses) <= SEARCHABLE_LIFECYCLES:
            raise MediaVisionError(
                "INVALID_LIFECYCLE_FILTER",
                "Media vision lifecycle filter is invalid",
            )
        return tuple(dict.fromkeys(statuses))

    def search_text(
        self,
        *,
        book_id: str,
        query: str,
        top_k: int = 20,
        lifecycle_statuses: tuple[str, ...] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        requested_backend: str = "auto",
    ) -> dict:
        if not query.strip() or len(query) > 4000:
            raise MediaVisionError("INVALID_QUERY", "Media search query is invalid")
        statuses = self._validate_filters(
            lifecycle_statuses,
            target_type,
            target_id,
        )
        self.init_index()
        active_space_id = self.active_visual_space_id()
        channel_vectors: dict[str, list[float]] = {}
        channel_status: dict[str, dict] = {}

        vision_status = _status_dict(self.vision.status())
        runtime_manifest_hash = self._visual_manifest(vision_status)[1]
        conn = self._conn()
        try:
            active_space = dict(
                self._require_visual_space(conn, active_space_id)
            )
        finally:
            conn.close()
        if (
            vision_status.get("available")
            and active_space["manifest_hash"] == runtime_manifest_hash
        ):
            channel_vectors["visual"] = _normalize(
                self.vision.embed_text(
                    query,
                    requested_backend=requested_backend,
                ),
                VISUAL_DIMS,
            )
            channel_status["visual"] = {
                "used": True,
                "vector_space_id": active_space_id,
                "language_scope": "english_text_tower",
            }
        else:
            channel_status["visual"] = {
                "used": False,
                "reason": (
                    "vision_runtime_space_mismatch"
                    if vision_status.get("available")
                    else "vision_package_unavailable"
                ),
                "language_scope": "english_text_tower",
            }

        try:
            caption = self._require_local_caption_provider()
            runtime = _status_dict(caption.status())
            if runtime.get("available"):
                channel_vectors["caption"] = _normalize(
                    caption.embed(query),
                    CAPTION_DIMS,
                )
                channel_status["caption"] = {
                    "used": True,
                    "vector_space_id": CAPTION_VECTOR_SPACE,
                    "language_scope": "multilingual",
                    "model_id": runtime.get("model_id"),
                }
            else:
                channel_status["caption"] = {
                    "used": False,
                    "reason": "local_bge_m3_unavailable",
                    "language_scope": "multilingual",
                }
        except MediaVisionError:
            channel_status["caption"] = {
                "used": False,
                "reason": "local_bge_m3_unavailable",
                "language_scope": "multilingual",
            }

        if not channel_vectors:
            raise MediaVisionError(
                "MEDIA_SEARCH_RUNTIME_UNAVAILABLE",
                "No local media search embedding channel is available",
                503,
            )
        conn = self._conn()
        try:
            results = {}
            if "visual" in channel_vectors:
                results["visual"] = self._channel_search(
                    conn,
                    table="media_visual_vectors_vec_v2",
                    vector=channel_vectors["visual"],
                    book_id=book_id,
                    channel="visual",
                    vector_space_id=active_space_id,
                    top_k=top_k,
                    lifecycle_statuses=statuses,
                    target_type=target_type,
                    target_id=target_id,
                )
            if "caption" in channel_vectors:
                results["caption"] = self._channel_search(
                    conn,
                    table="media_caption_vectors_vec",
                    vector=channel_vectors["caption"],
                    book_id=book_id,
                    channel="caption",
                    vector_space_id=CAPTION_VECTOR_SPACE,
                    top_k=top_k,
                    lifecycle_statuses=statuses,
                    target_type=target_type,
                    target_id=target_id,
                )
        finally:
            conn.close()
        multilingual_query = any(ord(character) > 127 for character in query)
        weights = (
            {"visual": 0.25, "caption": 0.75}
            if multilingual_query
            else {"visual": 0.55, "caption": 0.45}
        )
        return {
            "query_type": "text",
            "results": self._merge(results, top_k=top_k, weights=weights),
            "channels": channel_status,
            "degraded": any(not item.get("used") for item in channel_status.values()),
            "query_persisted": False,
        }

    def search_image(
        self,
        *,
        book_id: str,
        query_asset_id: str,
        top_k: int = 20,
        lifecycle_statuses: tuple[str, ...] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> dict:
        statuses = self._validate_filters(
            lifecycle_statuses,
            target_type,
            target_id,
        )
        self.init_index()
        active_space_id = self.active_visual_space_id()
        conn = self._conn()
        try:
            record = conn.execute(
                "SELECT vector_id FROM media_vector_records "
                "WHERE asset_id=? AND book_id=? AND channel='visual' "
                "AND vector_space_id=? ORDER BY updated_at DESC LIMIT 1",
                (query_asset_id, book_id, active_space_id),
            ).fetchone()
            if record is None:
                raise MediaVisionError(
                    "QUERY_ASSET_NOT_INDEXED",
                    "Query image must be indexed before image search",
                    409,
                )
            row = conn.execute(
                "SELECT embedding FROM media_visual_vectors_vec_v2 WHERE vector_id=?",
                (record["vector_id"],),
            ).fetchone()
            if row is None:
                raise MediaVisionError(
                    "VECTOR_INDEX_CORRUPT",
                    "Query image vector is missing",
                    500,
                )
            vector = _normalize(
                _deserialize_vector(row["embedding"], VISUAL_DIMS),
                VISUAL_DIMS,
            )
            visual_results = self._channel_search(
                conn,
                table="media_visual_vectors_vec_v2",
                vector=vector,
                book_id=book_id,
                channel="visual",
                vector_space_id=active_space_id,
                top_k=top_k,
                lifecycle_statuses=statuses,
                target_type=target_type,
                target_id=target_id,
                exclude_asset_id=query_asset_id,
            )
        finally:
            conn.close()
        return {
            "query_type": "image",
            "query_asset_id": query_asset_id,
            "results": self._merge(
                {"visual": visual_results},
                top_k=top_k,
                weights={"visual": 1.0},
            ),
            "channels": {
                "visual": {
                    "used": True,
                    "vector_space_id": active_space_id,
                }
            },
            "degraded": False,
            "query_persisted": False,
        }

    def status(self, *, book_id: str | None = None) -> dict:
        self.init_index()
        conn = self._conn()
        try:
            pointer = conn.execute(
                "SELECT * FROM media_visual_space_pointer WHERE id=1"
            ).fetchone()
            active_space_id = pointer["active_space_id"]
            visual_params: list[object] = [active_space_id]
            visual_where = (
                "channel='visual' AND vector_space_id=?"
            )
            caption_params: list[object] = [CAPTION_VECTOR_SPACE]
            caption_where = (
                "channel='caption' AND vector_space_id=?"
            )
            if book_id:
                visual_where += " AND book_id=?"
                caption_where += " AND book_id=?"
                visual_params.append(book_id)
                caption_params.append(book_id)
            counts = {
                "visual": conn.execute(
                    f"SELECT COUNT(*) FROM media_vector_records WHERE {visual_where}",
                    visual_params,
                ).fetchone()[0],
                "caption": conn.execute(
                    f"SELECT COUNT(*) FROM media_vector_records WHERE {caption_where}",
                    caption_params,
                ).fetchone()[0],
            }
            stale_visual = conn.execute(
                "SELECT COUNT(*) FROM media_vector_records r "
                "JOIN media_assets a ON a.asset_id=r.asset_id "
                "WHERE r.channel='visual' AND r.vector_space_id=? "
                "AND r.source_hash<>a.content_hash"
                + (" AND r.book_id=?" if book_id else ""),
                (
                    (active_space_id, book_id)
                    if book_id
                    else (active_space_id,)
                ),
            ).fetchone()[0]
        finally:
            conn.close()
        caption_status = (
            _status_dict(self.caption.status())
            if self.caption is not None
            and getattr(self.caption, "is_aetherdb_local", False)
            else {
                "available": False,
                "detail": "AetherDB local BGE-M3 is not initialized",
            }
        )
        return {
            "database_id": self.database_id,
            "book_id": book_id,
            "counts": {
                "visual": int(counts.get("visual", 0)),
                "caption": int(counts.get("caption", 0)),
            },
            "stale_visual": int(stale_visual),
            "visual_runtime": _status_dict(self.vision.status()),
            "caption_runtime": {
                **caption_status,
                "required_model": "BAAI/bge-m3",
                "language_scope": "multilingual",
                "external_embedding_allowed": False,
            },
            "vector_spaces": {
                "visual": {
                    "id": active_space_id,
                    "dimensions": VISUAL_DIMS,
                    "rollback_id": pointer["rollback_space_id"],
                },
                "caption": {
                    "id": CAPTION_VECTOR_SPACE,
                    "dimensions": CAPTION_DIMS,
                },
            },
            "visual_space_lifecycle": self.list_visual_spaces(),
        }


def default_media_vision_index(database_id: str) -> MediaVisionIndex:
    return MediaVisionIndex(database_id)


def _submit_visual_migration(database_id: str, task_id: str) -> None:
    global _MIGRATION_THREAD
    key = (database_id, task_id)
    with _MIGRATION_STATE_LOCK:
        if key in _MIGRATION_RUNNING:
            return
        _MIGRATION_RUNNING.add(key)
        _MIGRATION_QUEUE.put(key)
        if _MIGRATION_THREAD is None or not _MIGRATION_THREAD.is_alive():
            _MIGRATION_THREAD = threading.Thread(
                target=_visual_migration_worker_loop,
                name="media-vision-migration-worker",
                daemon=True,
            )
            _MIGRATION_THREAD.start()


def _visual_migration_worker_loop() -> None:
    while True:
        database_id, task_id = _MIGRATION_QUEUE.get()
        try:
            default_media_vision_index(database_id).run_migration_task(task_id)
        except MediaVisionError as exc:
            if exc.code != "VISUAL_MIGRATION_NOT_FOUND":
                log.warning(
                    "Visual migration %s stopped: %s",
                    task_id,
                    exc.code,
                )
        except Exception:
            log.exception("Visual migration %s crashed", task_id)
        finally:
            with _MIGRATION_STATE_LOCK:
                _MIGRATION_RUNNING.discard((database_id, task_id))
            _MIGRATION_QUEUE.task_done()


def wait_for_visual_migrations(timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        with _MIGRATION_STATE_LOCK:
            idle = (
                not _MIGRATION_RUNNING
                and _MIGRATION_QUEUE.unfinished_tasks == 0
            )
        if idle:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def recover_interrupted_visual_migrations() -> dict:
    recovered = 0
    queued_keys: list[tuple[str, str]] = []
    for database in list_databases():
        database_id = database["database_id"]
        try:
            index = default_media_vision_index(database_id)
            index.init_index()
            conn = index._conn()
            try:
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                conn.execute(
                    """UPDATE media_vision_migration_items
                          SET status='queued',error_code='INTERRUPTED',updated_at=?
                        WHERE status='running'""",
                    (now,),
                )
                cursor = conn.execute(
                    """UPDATE media_vision_migration_tasks
                          SET status='queued',error_code='INTERRUPTED',updated_at=?
                        WHERE status='running' AND cancel_requested=0""",
                    (now,),
                )
                recovered += cursor.rowcount
                cancelled = [
                    row["task_id"]
                    for row in conn.execute(
                        """SELECT task_id FROM media_vision_migration_tasks
                            WHERE status IN ('queued','running')
                              AND cancel_requested=1"""
                    )
                ]
                conn.commit()
            finally:
                conn.close()
            for task_id in cancelled:
                index.cancel_migration_task(task_id)
            queued_keys.extend(
                (database_id, task["task_id"])
                for task in index.list_migration_tasks(status="queued", limit=500)
                if not task["cancel_requested"]
            )
        except (OSError, sqlite3.Error, MediaVisionError, KeyError):
            log.warning(
                "Could not recover visual migrations for database %s",
                database_id,
            )
    for database_id, task_id in queued_keys:
        _submit_visual_migration(database_id, task_id)
    return {"recovered": recovered, "queued": len(queued_keys)}
