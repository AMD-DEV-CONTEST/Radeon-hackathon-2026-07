import json
import hashlib
import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

import sqlite_vec

from services.embedding import EmbeddingProvider


VECTOR_DIMS = 1024
CHUNK_SIZE = 512
CHUNK_OVERLAP = 128
VECTOR_SCHEMA_VERSION = "2"
VECTOR_SPACE_SCHEMA_VERSION = "1"
TEXT_PREPROCESS_VERSION = "bge-m3-dense-l2-v1"
TEXT_CHUNKING_VERSION = f"char-{CHUNK_SIZE}-overlap-{CHUNK_OVERLAP}-v1"


@dataclass
class SearchResult:
    entity_id: str
    title: str
    entity_type: str
    importance: int
    chunk_text: str
    score: float
    book_id: str
    translated_title: str = ""
    translated_content: str = ""


class VectorStore:
    def __init__(self, db_path, embedding_provider: EmbeddingProvider):
        self.db_path = db_path
        self.embedding = embedding_provider

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _ensure_column(conn, table: str, name: str, declaration: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @staticmethod
    def _space_manifest(
        *,
        model_id: str,
        model_revision: str,
        model_hash: str,
        runtime: str,
        dimension: int = VECTOR_DIMS,
        normalization: str = "l2",
        distance_metric: str = "cosine",
    ) -> tuple[dict, str]:
        manifest = {
            "space_kind": "text",
            "model_id": model_id,
            "model_revision": model_revision,
            "model_hash": model_hash,
            "preprocess_version": TEXT_PREPROCESS_VERSION,
            "chunking_version": TEXT_CHUNKING_VERSION,
            "dimension": dimension,
            "normalization": normalization,
            "distance_metric": distance_metric,
            "runtime": runtime,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "vector_schema_version": VECTOR_SCHEMA_VERSION,
            "space_schema_version": VECTOR_SPACE_SCHEMA_VERSION,
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

    def _runtime_identity(
        self,
        runtime_status,
        *,
        model_id: str | None = None,
        model_revision: str | None = None,
    ) -> tuple[str, str]:
        manifest = getattr(self.embedding, "manifest", None)
        if manifest is None:
            runtime = getattr(self.embedding, "runtime", None)
            manifest = getattr(runtime, "manifest", None)
        artifacts = getattr(manifest, "artifacts", ()) if manifest is not None else ()
        artifact_hashes = [
            getattr(artifact, "sha256", "")
            for artifact in artifacts
            if getattr(artifact, "sha256", "")
        ]
        model_hash = (
            hashlib.sha256("|".join(artifact_hashes).encode("ascii")).hexdigest()
            if artifact_hashes
            else hashlib.sha256(
                (
                    f"{model_id or runtime_status.model_id}\0"
                    f"{model_revision or runtime_status.revision}"
                ).encode("utf-8")
            ).hexdigest()
        )
        runtime = (
            "aetherdb-native-onnxruntime"
            if runtime_status.model_id == "BAAI/bge-m3"
            else type(self.embedding).__name__
        )
        return model_hash, runtime

    @staticmethod
    def _source_revision(conn) -> tuple[str, int]:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entities'"
        ).fetchone()
        if not table:
            return hashlib.sha256(b"").hexdigest(), 0
        rows = conn.execute(
            """SELECT entity_id,title,content,full_content,ai_summary,
                      entity_type,importance,tags,book_id,is_active
                 FROM entities
                WHERE is_active=1
                ORDER BY entity_id"""
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

    def _bootstrap_vector_space(self, conn, runtime_status) -> str:
        pointer = conn.execute(
            "SELECT active_space_id FROM vector_space_pointers "
            "WHERE space_kind='text'"
        ).fetchone()
        if pointer:
            return pointer["active_space_id"]

        legacy_metadata = dict(
            conn.execute("SELECT key,value FROM vector_index_metadata")
        )
        legacy_identity = conn.execute(
            "SELECT embedding_model_id,embedding_revision FROM vector_chunks "
            "WHERE embedding_model_id!='' ORDER BY chunk_id LIMIT 1"
        ).fetchone()
        model_id = (
            legacy_identity["embedding_model_id"]
            if legacy_identity
            else legacy_metadata.get("model_id") or runtime_status.model_id
        )
        model_revision = (
            legacy_identity["embedding_revision"]
            if legacy_identity
            else legacy_metadata.get("model_revision") or runtime_status.revision
        )
        model_hash, runtime = self._runtime_identity(
            runtime_status,
            model_id=model_id,
            model_revision=model_revision,
        )
        manifest, manifest_hash = self._space_manifest(
            model_id=model_id,
            model_revision=model_revision,
            model_hash=model_hash,
            runtime=runtime,
        )
        source_revision_hash, source_entity_count = self._source_revision(conn)
        space_id = f"vspace_text_{manifest_hash[:24]}"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            """INSERT OR IGNORE INTO vector_spaces(
                   space_id,space_kind,model_id,model_revision,dimension,
                   normalization,distance_metric,chunk_size,chunk_overlap,
                   vector_schema_version,manifest_hash,status,created_at,
                   validated_at,activated_at,model_hash,preprocess_version,
                   chunking_version,runtime,source_revision_hash,
                   source_entity_count,stale
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                space_id,
                "text",
                model_id,
                model_revision,
                VECTOR_DIMS,
                "l2",
                "cosine",
                CHUNK_SIZE,
                CHUNK_OVERLAP,
                VECTOR_SCHEMA_VERSION,
                manifest_hash,
                "active",
                now,
                now,
                now,
                model_hash,
                manifest["preprocess_version"],
                manifest["chunking_version"],
                runtime,
                source_revision_hash,
                source_entity_count,
                0,
            ),
        )
        conn.execute(
            "UPDATE vector_chunks SET embedding_space_id=? "
            "WHERE embedding_space_id IS NULL OR embedding_space_id=''",
            (space_id,),
        )
        legacy_rows = conn.execute(
            """SELECT c.chunk_id,v.embedding,c.book_id,c.entity_type,c.importance
                 FROM vector_chunks_vec v
                 JOIN vector_chunks c ON c.chunk_id=v.chunk_id
                WHERE c.embedding_space_id=?""",
            (space_id,),
        ).fetchall()
        for row in legacy_rows:
            conn.execute(
                """INSERT OR IGNORE INTO vector_chunks_vec_v3(
                       chunk_id,embedding,embedding_space_id,book_id,
                       entity_type,importance
                   ) VALUES (?,?,?,?,?,?)""",
                (
                    row["chunk_id"],
                    row["embedding"],
                    space_id,
                    row["book_id"],
                    row["entity_type"],
                    row["importance"],
                ),
            )
        conn.execute(
            """INSERT INTO vector_space_pointers(
                   space_kind,active_space_id,rollback_space_id,updated_at
               ) VALUES ('text',?,NULL,?)""",
            (space_id, now),
        )
        return space_id

    def init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vector_chunks (
                    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    chunk_type TEXT NOT NULL,
                    chunk_index INTEGER DEFAULT 0,
                    chunk_text TEXT NOT NULL,
                    embedding BLOB,
                    token_count INTEGER DEFAULT 0,
                    book_id TEXT DEFAULT 'default',
                    entity_type TEXT DEFAULT '',
                    importance INTEGER DEFAULT 5
                );
                CREATE INDEX IF NOT EXISTS idx_vc_entity ON vector_chunks(entity_id);
                CREATE INDEX IF NOT EXISTS idx_vc_book ON vector_chunks(book_id);
                CREATE TABLE IF NOT EXISTS vector_index_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vector_sync_queue (
                    entity_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS vector_spaces (
                    space_id TEXT PRIMARY KEY,
                    space_kind TEXT NOT NULL DEFAULT 'text',
                    model_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    normalization TEXT NOT NULL,
                    distance_metric TEXT NOT NULL,
                    chunk_size INTEGER NOT NULL,
                    chunk_overlap INTEGER NOT NULL,
                    vector_schema_version TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('building','validating','ready','active','retired','failed')),
                    source_space_id TEXT,
                    failure_code TEXT,
                    model_hash TEXT NOT NULL DEFAULT '',
                    preprocess_version TEXT NOT NULL DEFAULT '',
                    chunking_version TEXT NOT NULL DEFAULT '',
                    runtime TEXT NOT NULL DEFAULT '',
                    source_revision_hash TEXT NOT NULL DEFAULT '',
                    source_entity_count INTEGER NOT NULL DEFAULT 0,
                    stale INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    validated_at TEXT,
                    activated_at TEXT,
                    retired_at TEXT,
                    FOREIGN KEY(source_space_id) REFERENCES vector_spaces(space_id)
                );
                CREATE INDEX IF NOT EXISTS idx_vector_spaces_status
                ON vector_spaces(space_kind,status,created_at DESC);
                CREATE TABLE IF NOT EXISTS vector_space_pointers (
                    space_kind TEXT PRIMARY KEY,
                    active_space_id TEXT NOT NULL,
                    rollback_space_id TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(active_space_id) REFERENCES vector_spaces(space_id),
                    FOREIGN KEY(rollback_space_id) REFERENCES vector_spaces(space_id)
                );
                """
            )
            self._ensure_column(conn, "vector_chunks", "title", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vector_chunks", "content_hash", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vector_chunks", "embedding_model_id", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vector_chunks", "embedding_revision", "TEXT DEFAULT ''")
            self._ensure_column(conn, "vector_chunks", "embedding_space_id", "TEXT")
            self._ensure_column(conn, "vector_spaces", "model_hash", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn,
                "vector_spaces",
                "preprocess_version",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "vector_spaces",
                "chunking_version",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(conn, "vector_spaces", "runtime", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(
                conn,
                "vector_spaces",
                "source_revision_hash",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "vector_spaces",
                "source_entity_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                "vector_spaces",
                "stale",
                "INTEGER NOT NULL DEFAULT 0",
            )

            existing = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='vector_chunks_vec'"
            ).fetchone()
            if existing and "float[1024]" not in (existing["sql"] or "").lower():
                raise RuntimeError("Existing vector_chunks_vec schema has an incompatible dimension")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS vector_chunks_vec USING vec0(
                    chunk_id INTEGER PRIMARY KEY,
                    embedding float[1024] distance_metric=cosine,
                    book_id TEXT PARTITION KEY,
                    entity_type TEXT,
                    importance INTEGER
                )
                """
            )
            current_space_vec = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='vector_chunks_vec_v3'"
            ).fetchone()
            if current_space_vec and "float[1024]" not in (
                current_space_vec["sql"] or ""
            ).lower():
                raise RuntimeError(
                    "Existing vector_chunks_vec_v3 schema has an incompatible dimension"
                )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS vector_chunks_vec_v3 USING vec0(
                    chunk_id INTEGER PRIMARY KEY,
                    embedding float[1024] distance_metric=cosine,
                    embedding_space_id TEXT PARTITION KEY,
                    book_id TEXT,
                    entity_type TEXT,
                    importance INTEGER
                )
                """
            )
            status = self.embedding.status()
            active_space_id = self._bootstrap_vector_space(conn, status)
            model_hash, runtime = self._runtime_identity(status)
            source_revision_hash, source_entity_count = self._source_revision(conn)
            conn.execute(
                """UPDATE vector_spaces
                      SET model_hash=CASE WHEN model_hash='' THEN ? ELSE model_hash END,
                          preprocess_version=CASE
                              WHEN preprocess_version='' THEN ? ELSE preprocess_version END,
                          chunking_version=CASE
                              WHEN chunking_version='' THEN ? ELSE chunking_version END,
                          runtime=CASE WHEN runtime='' THEN ? ELSE runtime END,
                          source_revision_hash=CASE
                              WHEN source_revision_hash='' THEN ? ELSE source_revision_hash END,
                          source_entity_count=CASE
                              WHEN source_revision_hash='' THEN ? ELSE source_entity_count END
                    WHERE space_id=?""",
                (
                    model_hash,
                    TEXT_PREPROCESS_VERSION,
                    TEXT_CHUNKING_VERSION,
                    runtime,
                    source_revision_hash,
                    source_entity_count,
                    active_space_id,
                ),
            )
            active_space = conn.execute(
                "SELECT * FROM vector_spaces WHERE space_id=?",
                (active_space_id,),
            ).fetchone()
            metadata = {
                "schema_version": VECTOR_SCHEMA_VERSION,
                "dimensions": str(VECTOR_DIMS),
                "model_id": active_space["model_id"],
                "model_revision": active_space["model_revision"],
                "normalization": active_space["normalization"],
                "distance_metric": active_space["distance_metric"],
                "active_space_id": active_space_id,
                "runtime_model_id": status.model_id,
                "runtime_model_revision": status.revision,
            }
            conn.executemany(
                "INSERT INTO vector_index_metadata(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                metadata.items(),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _require_space(conn, space_id: str):
        row = conn.execute(
            "SELECT * FROM vector_spaces WHERE space_id=?",
            (space_id,),
        ).fetchone()
        if not row:
            raise KeyError(space_id)
        return row

    def active_space_id(self) -> str:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT active_space_id FROM vector_space_pointers "
                "WHERE space_kind='text'"
            ).fetchone()
            if not row:
                raise RuntimeError("Text vector space pointer is not initialized")
            return row["active_space_id"]
        finally:
            conn.close()

    def list_vector_spaces(self) -> dict:
        conn = self._get_conn()
        try:
            pointer = conn.execute(
                "SELECT * FROM vector_space_pointers WHERE space_kind='text'"
            ).fetchone()
            rows = conn.execute(
                """SELECT s.*,
                          (SELECT COUNT(*) FROM vector_chunks c
                            WHERE c.embedding_space_id=s.space_id) AS chunk_count,
                          (SELECT COUNT(*) FROM vector_chunks_vec_v3 v
                            WHERE v.embedding_space_id=s.space_id) AS vector_count
                     FROM vector_spaces s
                    WHERE s.space_kind='text'
                    ORDER BY s.created_at DESC,s.space_id DESC"""
            ).fetchall()
            return {
                "active_space_id": pointer["active_space_id"] if pointer else None,
                "rollback_space_id": pointer["rollback_space_id"] if pointer else None,
                "spaces": [dict(row) for row in rows],
            }
        finally:
            conn.close()

    def create_vector_space(
        self,
        *,
        model_id: str | None = None,
        model_revision: str | None = None,
    ) -> dict:
        runtime = self.embedding.status()
        if not runtime.available:
            raise RuntimeError("Embedding runtime is unavailable")
        selected_model_id = model_id or runtime.model_id
        selected_revision = model_revision or runtime.revision
        if (
            selected_model_id != runtime.model_id
            or selected_revision != runtime.revision
        ):
            raise ValueError(
                "New vector spaces must match the active AetherDB embedding runtime"
            )
        model_hash, runtime_identity = self._runtime_identity(
            runtime,
            model_id=selected_model_id,
            model_revision=selected_revision,
        )
        manifest, manifest_hash = self._space_manifest(
            model_id=selected_model_id,
            model_revision=selected_revision,
            model_hash=model_hash,
            runtime=runtime_identity,
        )
        space_id = f"vspace_text_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = self._get_conn()
        try:
            pointer = conn.execute(
                "SELECT active_space_id FROM vector_space_pointers "
                "WHERE space_kind='text'"
            ).fetchone()
            source_space_id = pointer["active_space_id"] if pointer else None
            source_revision_hash, source_entity_count = self._source_revision(conn)
            conn.execute(
                """INSERT INTO vector_spaces(
                       space_id,space_kind,model_id,model_revision,dimension,
                       normalization,distance_metric,chunk_size,chunk_overlap,
                       vector_schema_version,manifest_hash,status,source_space_id,
                       created_at,model_hash,preprocess_version,chunking_version,
                       runtime,source_revision_hash,source_entity_count,stale
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    space_id,
                    "text",
                    selected_model_id,
                    selected_revision,
                    VECTOR_DIMS,
                    "l2",
                    "cosine",
                    CHUNK_SIZE,
                    CHUNK_OVERLAP,
                    VECTOR_SCHEMA_VERSION,
                    manifest_hash,
                    "building",
                    source_space_id,
                    now,
                    model_hash,
                    manifest["preprocess_version"],
                    manifest["chunking_version"],
                    runtime_identity,
                    source_revision_hash,
                    source_entity_count,
                    0,
                ),
            )
            conn.commit()
            return dict(self._require_space(conn, space_id))
        finally:
            conn.close()

    def mark_vector_space_failed(self, space_id: str, failure_code: str) -> dict:
        conn = self._get_conn()
        try:
            space = self._require_space(conn, space_id)
            if space["status"] in {"active", "retired"}:
                raise ValueError("Active or retired vector spaces cannot be marked failed")
            conn.execute(
                "UPDATE vector_spaces SET status='failed',failure_code=? "
                "WHERE space_id=?",
                (failure_code[:96], space_id),
            )
            conn.commit()
            return dict(self._require_space(conn, space_id))
        finally:
            conn.close()

    def validate_vector_space(self, space_id: str) -> dict:
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            space = self._require_space(conn, space_id)
            if space["status"] not in {"building", "ready", "failed"}:
                raise ValueError("Vector space is not available for validation")
            conn.execute(
                "UPDATE vector_spaces SET status='validating',failure_code=NULL "
                "WHERE space_id=?",
                (space_id,),
            )
            chunk_count = conn.execute(
                "SELECT COUNT(*) FROM vector_chunks WHERE embedding_space_id=?",
                (space_id,),
            ).fetchone()[0]
            vector_count = conn.execute(
                "SELECT COUNT(*) FROM vector_chunks_vec_v3 "
                "WHERE embedding_space_id=?",
                (space_id,),
            ).fetchone()[0]
            active_entity_count = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE is_active=1"
            ).fetchone()[0]
            indexed_entity_count = conn.execute(
                "SELECT COUNT(DISTINCT entity_id) FROM vector_chunks "
                "WHERE embedding_space_id=?",
                (space_id,),
            ).fetchone()[0]
            source_revision_hash, source_entity_count = self._source_revision(conn)
            failure_code = None
            if chunk_count != vector_count:
                failure_code = "VECTOR_COUNT_MISMATCH"
            elif active_entity_count != indexed_entity_count:
                failure_code = "ENTITY_COVERAGE_MISMATCH"
            elif (
                source_revision_hash != space["source_revision_hash"]
                or source_entity_count != space["source_entity_count"]
            ):
                failure_code = "SOURCE_REVISION_CHANGED"
            elif chunk_count:
                sample = conn.execute(
                    "SELECT embedding FROM vector_chunks_vec_v3 "
                    "WHERE embedding_space_id=? LIMIT 1",
                    (space_id,),
                ).fetchone()
                try:
                    matched = conn.execute(
                        """SELECT chunk_id FROM vector_chunks_vec_v3
                            WHERE embedding MATCH ? AND k=1
                              AND embedding_space_id=?""",
                        (sample["embedding"], space_id),
                    ).fetchone()
                except sqlite3.Error:
                    matched = None
                if not matched:
                    failure_code = "VECTOR_SAMPLE_QUERY_FAILED"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if failure_code:
                conn.execute(
                    "UPDATE vector_spaces SET status='failed',failure_code=?,stale=? "
                    "WHERE space_id=?",
                    (
                        failure_code,
                        1 if failure_code == "SOURCE_REVISION_CHANGED" else 0,
                        space_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE vector_spaces SET status='ready',failure_code=NULL,"
                    "validated_at=?,stale=0 WHERE space_id=?",
                    (now, space_id),
                )
            conn.commit()
            result = dict(self._require_space(conn, space_id))
            result.update(
                {
                    "chunk_count": chunk_count,
                    "vector_count": vector_count,
                    "active_entity_count": active_entity_count,
                    "indexed_entity_count": indexed_entity_count,
                    "current_source_revision_hash": source_revision_hash,
                    "valid": failure_code is None,
                }
            )
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def activate_vector_space(self, space_id: str) -> dict:
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = self._require_space(conn, space_id)
            if target["status"] != "ready":
                raise ValueError("Only a validated ready vector space can be activated")
            pointer = conn.execute(
                "SELECT * FROM vector_space_pointers WHERE space_kind='text'"
            ).fetchone()
            if not pointer:
                raise RuntimeError("Text vector space pointer is not initialized")
            old_active = pointer["active_space_id"]
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "UPDATE vector_spaces SET status='retired',retired_at=? "
                "WHERE space_id=? AND status='active'",
                (now, old_active),
            )
            conn.execute(
                "UPDATE vector_spaces SET status='active',activated_at=?,"
                "retired_at=NULL WHERE space_id=?",
                (now, space_id),
            )
            conn.execute(
                "UPDATE vector_space_pointers SET active_space_id=?,"
                "rollback_space_id=?,updated_at=? WHERE space_kind='text'",
                (space_id, old_active, now),
            )
            conn.executemany(
                "INSERT INTO vector_index_metadata(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (
                    ("active_space_id", space_id),
                    ("model_id", target["model_id"]),
                    ("model_revision", target["model_revision"]),
                    ("normalization", target["normalization"]),
                    ("distance_metric", target["distance_metric"]),
                ),
            )
            conn.commit()
            return self.list_vector_spaces()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rollback_vector_space(self) -> dict:
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            pointer = conn.execute(
                "SELECT * FROM vector_space_pointers WHERE space_kind='text'"
            ).fetchone()
            if not pointer or not pointer["rollback_space_id"]:
                raise ValueError("No rollback vector space is available")
            old_active = pointer["active_space_id"]
            rollback_space_id = pointer["rollback_space_id"]
            target = self._require_space(conn, rollback_space_id)
            if target["status"] not in {"retired", "ready"}:
                raise ValueError("Rollback vector space is not available")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "UPDATE vector_spaces SET status='retired',retired_at=? "
                "WHERE space_id=?",
                (now, old_active),
            )
            conn.execute(
                "UPDATE vector_spaces SET status='active',activated_at=?,"
                "retired_at=NULL WHERE space_id=?",
                (now, rollback_space_id),
            )
            conn.execute(
                "UPDATE vector_space_pointers SET active_space_id=?,"
                "rollback_space_id=?,updated_at=? WHERE space_kind='text'",
                (rollback_space_id, old_active, now),
            )
            conn.executemany(
                "INSERT INTO vector_index_metadata(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (
                    ("active_space_id", rollback_space_id),
                    ("model_id", target["model_id"]),
                    ("model_revision", target["model_revision"]),
                    ("normalization", target["normalization"]),
                    ("distance_metric", target["distance_metric"]),
                ),
            )
            conn.commit()
            return self.list_vector_spaces()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def garbage_collect_vector_space(
        self,
        space_id: str,
        *,
        confirm_space_id: str,
    ) -> dict:
        if confirm_space_id != space_id:
            raise ValueError("Vector space garbage collection confirmation mismatch")
        from services.database_registry import _get_registry_conn

        registry = _get_registry_conn()
        try:
            columns = {
                row[1] for row in registry.execute("PRAGMA table_info(embedding_tasks)")
            }
            if "target_space_id" in columns:
                task_ref = registry.execute(
                    "SELECT id FROM embedding_tasks WHERE target_space_id=? "
                    "AND status IN ('queued','running') LIMIT 1",
                    (space_id,),
                ).fetchone()
            else:
                task_ref = None
        finally:
            registry.close()
        if task_ref:
            raise ValueError("A running embedding task still references this vector space")

        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            pointer = conn.execute(
                "SELECT * FROM vector_space_pointers WHERE space_kind='text'"
            ).fetchone()
            if space_id in {
                pointer["active_space_id"],
                pointer["rollback_space_id"],
            }:
                raise ValueError("Active or rollback vector spaces cannot be collected")
            space = self._require_space(conn, space_id)
            if space["status"] not in {"retired", "failed"}:
                raise ValueError("Only retired or failed vector spaces can be collected")
            chunk_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT chunk_id FROM vector_chunks WHERE embedding_space_id=?",
                    (space_id,),
                )
            ]
            conn.executemany(
                "DELETE FROM vector_chunks_vec_v3 WHERE chunk_id=?",
                ((chunk_id,) for chunk_id in chunk_ids),
            )
            conn.execute(
                "DELETE FROM vector_chunks WHERE embedding_space_id=?",
                (space_id,),
            )
            conn.execute("DELETE FROM vector_spaces WHERE space_id=?", (space_id,))
            conn.commit()
            return {
                "space_id": space_id,
                "deleted": True,
                "deleted_chunk_count": len(chunk_ids),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start += chunk_size - overlap
        return chunks

    def _entity_chunks(self, entity: dict) -> list[dict]:
        chunks = []

        def normalized_importance(value) -> int:
            if isinstance(value, bool):
                return 5
            if isinstance(value, (int, float)):
                return min(10, max(1, int(value)))
            if isinstance(value, str):
                text = value.strip().lower()
                labels = {
                    "low": 2,
                    "medium": 5,
                    "high": 8,
                    "minor": 2,
                    "major": 8,
                    "低": 2,
                    "中": 5,
                    "中等": 5,
                    "高": 8,
                    "重要": 8,
                }
                if text in labels:
                    return labels[text]
                try:
                    return min(10, max(1, int(float(text))))
                except ValueError:
                    return 5
            return 5

        def append(chunk_type: str, text: str, index: int = 0):
            if text and text.strip():
                chunks.append({
                    "entity_id": entity["entity_id"],
                    "title": entity.get("title", ""),
                    "chunk_type": chunk_type,
                    "chunk_index": index,
                    "chunk_text": text.strip(),
                    "book_id": entity.get("book_id") or "default",
                    "entity_type": entity.get("entity_type") or "",
                    "importance": normalized_importance(entity.get("importance")),
                })

        append("title", entity.get("title", ""))
        append("summary", (entity.get("ai_summary") or "")[:500])
        source = entity.get("full_content") or entity.get("content") or ""
        for index, text in enumerate(self._chunk_text(source)):
            append("content", text, index)
        for tag in (entity.get("tags") or [])[:10]:
            append("tag", str(tag))
        return chunks

    @staticmethod
    def _normalize_vector(vector: List[float]) -> List[float]:
        if len(vector) != VECTOR_DIMS or any(not math.isfinite(value) for value in vector):
            raise ValueError("Embedding vector must contain 1024 finite values")
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            raise ValueError("Embedding vector must not be zero")
        return [value / norm for value in vector]

    def entity_content_hash(self, entity: dict) -> str:
        status = self.embedding.status()
        chunks = self._entity_chunks(entity)
        identity = [
            {
                "chunk_type": chunk["chunk_type"],
                "chunk_index": chunk["chunk_index"],
                "content_hash": hashlib.sha256(
                    chunk["chunk_text"].encode("utf-8")
                ).hexdigest(),
                "title": chunk["title"],
                "book_id": chunk["book_id"],
                "entity_type": chunk["entity_type"],
                "importance": chunk["importance"],
            }
            for chunk in chunks
        ]
        payload = {
            "model_id": status.model_id,
            "revision": status.revision,
            "chunks": identity,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def entity_is_current(self, entity: dict, space_id: str | None = None) -> bool:
        status = self.embedding.status()
        space_id = space_id or self.active_space_id()
        expected = [
            (
                chunk["chunk_type"],
                chunk["chunk_index"],
                hashlib.sha256(chunk["chunk_text"].encode("utf-8")).hexdigest(),
                chunk["title"],
                chunk["book_id"],
                chunk["entity_type"],
                chunk["importance"],
                status.model_id,
                status.revision,
            )
            for chunk in self._entity_chunks(entity)
        ]
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT chunk_type,chunk_index,content_hash,title,book_id,entity_type,"
                "importance,embedding_model_id,embedding_revision FROM vector_chunks "
                "WHERE entity_id=? AND embedding_space_id=? "
                "ORDER BY chunk_type,chunk_index,chunk_id",
                (entity["entity_id"], space_id),
            ).fetchall()
            actual = [tuple(row) for row in rows]
        finally:
            conn.close()
        return sorted(actual, key=repr) == sorted(expected, key=repr)

    def add_entities(
        self,
        entities: list[dict],
        *,
        space_id: str | None = None,
    ) -> int:
        space_id = space_id or self.active_space_id()
        chunks = [chunk for entity in entities for chunk in self._entity_chunks(entity)]
        if not chunks:
            return 0
        vectors = self.embedding.embed_batch([chunk["chunk_text"] for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("Embedding batch result count does not match chunk count")
        vectors = [self._normalize_vector(vector) for vector in vectors]
        status = self.embedding.status()
        entity_ids = list(dict.fromkeys(entity["entity_id"] for entity in entities))

        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            target_space = self._require_space(conn, space_id)
            if target_space["status"] not in {"building", "active"}:
                raise ValueError("Vector writes require a building or active space")
            if (
                target_space["model_id"] != status.model_id
                or target_space["model_revision"] != status.revision
            ):
                raise ValueError(
                    "Embedding runtime does not match the target vector space"
                )
            for entity_id in entity_ids:
                old_ids = [
                    row[0]
                    for row in conn.execute(
                        "SELECT chunk_id FROM vector_chunks "
                        "WHERE entity_id=? AND embedding_space_id=?",
                        (entity_id, space_id),
                    )
                ]
                conn.executemany(
                    "DELETE FROM vector_chunks_vec_v3 WHERE chunk_id=?",
                    ((chunk_id,) for chunk_id in old_ids),
                )
                conn.execute(
                    "DELETE FROM vector_chunks WHERE entity_id=? "
                    "AND embedding_space_id=?",
                    (entity_id, space_id),
                )

            for chunk, vector in zip(chunks, vectors):
                content_hash = hashlib.sha256(chunk["chunk_text"].encode("utf-8")).hexdigest()
                cursor = conn.execute(
                    """
                    INSERT INTO vector_chunks(
                        entity_id, title, chunk_type, chunk_index, chunk_text,
                        embedding, token_count, book_id, entity_type, importance,
                        content_hash, embedding_model_id, embedding_revision,
                        embedding_space_id
                    ) VALUES(?,?,?,?,?,NULL,?,?,?,?,?,?,?,?)
                    """,
                    (
                        chunk["entity_id"],
                        chunk["title"],
                        chunk["chunk_type"],
                        chunk["chunk_index"],
                        chunk["chunk_text"],
                        len(chunk["chunk_text"].split()),
                        chunk["book_id"],
                        chunk["entity_type"],
                        chunk["importance"],
                        content_hash,
                        status.model_id,
                        status.revision,
                        space_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO vector_chunks_vec_v3(
                        chunk_id, embedding, embedding_space_id, book_id,
                        entity_type, importance
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        cursor.lastrowid,
                        sqlite_vec.serialize_float32(vector),
                        space_id,
                        chunk["book_id"],
                        chunk["entity_type"],
                        chunk["importance"],
                    ),
                )
            if target_space["status"] == "active":
                source_revision_hash, source_entity_count = self._source_revision(conn)
                conn.execute(
                    """UPDATE vector_spaces
                          SET source_revision_hash=?,source_entity_count=?,stale=0
                        WHERE space_id=?""",
                    (source_revision_hash, source_entity_count, space_id),
                )
            conn.commit()
            return len(chunks)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_entity(
        self, entity_id, title, content, full_content, ai_summary,
        entity_type, importance, tags, book_id="default",
    ):
        return self.add_entities([{
            "entity_id": entity_id,
            "title": title,
            "content": content,
            "full_content": full_content,
            "ai_summary": ai_summary,
            "entity_type": entity_type,
            "importance": importance,
            "tags": tags,
            "book_id": book_id,
        }])

    def delete_entity(self, entity_id, *, space_id: str | None = None):
        space_id = space_id or self.active_space_id()
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            chunk_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT chunk_id FROM vector_chunks "
                    "WHERE entity_id=? AND embedding_space_id=?",
                    (entity_id, space_id),
                )
            ]
            conn.executemany(
                "DELETE FROM vector_chunks_vec_v3 WHERE chunk_id=?",
                ((chunk_id,) for chunk_id in chunk_ids),
            )
            conn.execute(
                "DELETE FROM vector_chunks WHERE entity_id=? "
                "AND embedding_space_id=?",
                (entity_id, space_id),
            )
            target_space = self._require_space(conn, space_id)
            if target_space["status"] == "active":
                source_revision_hash, source_entity_count = self._source_revision(conn)
                conn.execute(
                    """UPDATE vector_spaces
                          SET source_revision_hash=?,source_entity_count=?,stale=0
                        WHERE space_id=?""",
                    (source_revision_hash, source_entity_count, space_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_entity(
        self, entity_id, title=None, content=None, full_content=None,
        ai_summary=None, entity_type=None, importance=None, tags=None, book_id=None,
    ):
        return self.add_entity(
            entity_id,
            title or "",
            content or "",
            full_content or "",
            ai_summary or "",
            entity_type or "",
            importance or 5,
            tags or [],
            book_id or "default",
        )

    def search(self, query, top_k=10, filter_type=None, book_id=None, lang=None):
        space_id = self.active_space_id()
        query_vec = self._normalize_vector(self.embedding.embed(query))
        vec_results = self._vector_search(
            query_vec, top_k * 2, filter_type, book_id, space_id
        )
        keyword_results = self._keyword_search(
            query, top_k * 2, filter_type, book_id, space_id
        )
        fts_results = self._fts_search(query, top_k * 2, book_id)
        results = self._rrf_merge([vec_results, keyword_results, fts_results], top_k)
        if lang:
            results = self._enrich_with_translations(results, lang)
        return results

    def _vector_search(
        self,
        query_vec,
        top_k,
        filter_type=None,
        book_id=None,
        space_id=None,
    ):
        space_id = space_id or self.active_space_id()
        conn = self._get_conn()
        try:
            where = ["embedding MATCH ?", "k = ?", "embedding_space_id = ?"]
            params = [
                sqlite_vec.serialize_float32(query_vec),
                top_k,
                space_id,
            ]
            if book_id:
                where.append("book_id = ?")
                params.append(book_id)
            if filter_type:
                where.append("entity_type = ?")
                params.append(filter_type)
            rows = conn.execute(
                f"""
                WITH knn AS (
                    SELECT chunk_id, distance
                    FROM vector_chunks_vec_v3
                    WHERE {' AND '.join(where)}
                )
                SELECT c.entity_id, c.title, c.chunk_text, c.book_id,
                       c.entity_type, c.importance, knn.distance
                FROM knn JOIN vector_chunks c ON c.chunk_id = knn.chunk_id
                WHERE c.embedding_space_id=?
                ORDER BY knn.distance
                """,
                (*params, space_id),
            ).fetchall()
            return [
                SearchResult(
                    entity_id=row["entity_id"],
                    title=row["title"],
                    entity_type=row["entity_type"],
                    importance=row["importance"],
                    chunk_text=row["chunk_text"][:200],
                    score=max(0.0, 1.0 - float(row["distance"])),
                    book_id=row["book_id"],
                )
                for row in rows
            ]
        finally:
            conn.close()

    def _keyword_search(
        self,
        query,
        top_k,
        filter_type=None,
        book_id=None,
        space_id=None,
    ):
        space_id = space_id or self.active_space_id()
        conn = self._get_conn()
        try:
            sql = (
                "SELECT entity_id,title,chunk_text,book_id,entity_type,importance "
                "FROM vector_chunks WHERE chunk_text LIKE ? "
                "AND embedding_space_id=?"
            )
            params = [f"%{query}%", space_id]
            if filter_type:
                sql += " AND entity_type=?"
                params.append(filter_type)
            if book_id:
                sql += " AND book_id=?"
                params.append(book_id)
            sql += " LIMIT ?"
            params.append(top_k)
            return [
                SearchResult(
                    entity_id=row["entity_id"],
                    title=row["title"],
                    entity_type=row["entity_type"],
                    importance=row["importance"],
                    chunk_text=row["chunk_text"][:200],
                    score=0.3,
                    book_id=row["book_id"],
                )
                for row in conn.execute(sql, params)
            ]
        finally:
            conn.close()

    def _fts_search(self, query, top_k, book_id=None):
        conn = self._get_conn()
        try:
            safe = self._fts_safe_query(query)
            rows = conn.execute(
                """
                SELECT e.entity_id,e.title,e.entity_type,e.importance,e.content,e.book_id
                FROM entities_fts f JOIN entities e ON f.rowid=e.rowid
                WHERE entities_fts MATCH ? AND (? IS NULL OR e.book_id=?)
                ORDER BY rank LIMIT ?
                """,
                (safe, book_id, book_id, top_k),
            ).fetchall()
            return [
                SearchResult(
                    entity_id=row["entity_id"],
                    title=row["title"],
                    entity_type=row["entity_type"],
                    importance=row["importance"],
                    chunk_text=(row["content"] or "")[:200],
                    score=0.3,
                    book_id=row["book_id"] or "default",
                )
                for row in rows
            ]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    @staticmethod
    def _fts_safe_query(query):
        return '"' + (query or "").replace('"', '""') + '"'

    def _enrich_with_translations(self, results, lang):
        conn = self._get_conn()
        try:
            for result in results:
                translation = conn.execute(
                    """SELECT t.title,t.content
                         FROM entity_translations t
                         JOIN entities e ON e.entity_id=t.entity_id
                        WHERE t.entity_id=? AND t.language=?
                          AND t.translation_status='approved'
                          AND t.approval_status='approved'
                          AND t.source_revision=COALESCE(e.version,1)""",
                    (result.entity_id, lang),
                ).fetchone()
                if translation:
                    result.translated_title = translation["title"]
                    result.translated_content = translation["content"] or ""
        except sqlite3.Error:
            pass
        finally:
            conn.close()
        return results

    @staticmethod
    def _rrf_merge(result_lists, top_k, k=60):
        scores = {}
        data = {}
        for results in result_lists:
            seen = set()
            for index, result in enumerate(results):
                if result.entity_id in seen:
                    continue
                seen.add(result.entity_id)
                scores[result.entity_id] = scores.get(result.entity_id, 0) + 1.0 / (k + index + 1)
                data.setdefault(result.entity_id, result)
        entity_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
        for entity_id in entity_ids:
            data[entity_id].score = scores[entity_id]
        return [data[entity_id] for entity_id in entity_ids]

    def index_status(self) -> dict:
        conn = self._get_conn()
        try:
            pointer = conn.execute(
                "SELECT * FROM vector_space_pointers WHERE space_kind='text'"
            ).fetchone()
            active_space_id = pointer["active_space_id"]
            metadata = dict(conn.execute("SELECT key,value FROM vector_index_metadata"))
            chunk_count = conn.execute(
                "SELECT COUNT(*) FROM vector_chunks WHERE embedding_space_id=?",
                (active_space_id,),
            ).fetchone()[0]
            vector_count = conn.execute(
                "SELECT COUNT(*) FROM vector_chunks_vec_v3 "
                "WHERE embedding_space_id=?",
                (active_space_id,),
            ).fetchone()[0]
            legacy_count = conn.execute(
                "SELECT COUNT(*) FROM vector_chunks "
                "WHERE embedding IS NOT NULL AND length(embedding)>0"
            ).fetchone()[0]
            orphan_count = conn.execute(
                "SELECT COUNT(*) FROM vector_chunks "
                "WHERE embedding_space_id IS NULL OR embedding_space_id=''"
            ).fetchone()[0]
            return {
                "metadata": metadata,
                "active_space_id": active_space_id,
                "rollback_space_id": pointer["rollback_space_id"],
                "chunk_count": chunk_count,
                "vector_count": vector_count,
                "legacy_embedding_count": legacy_count,
                "orphan_chunk_count": orphan_count,
                "rebuild_required": (
                    chunk_count != vector_count
                    or legacy_count > 0
                    or orphan_count > 0
                ),
            }
        finally:
            conn.close()

    def rebuild_from_entities(self, book_id: str | None = None) -> dict:
        runtime_status = self.embedding.status()
        if not runtime_status.available:
            raise RuntimeError("Embedding runtime is unavailable")

        conn = self._get_conn()
        try:
            sql = "SELECT * FROM entities WHERE is_active=1"
            params = []
            if book_id is not None:
                sql += " AND book_id=?"
                params.append(book_id)
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        entities = []
        for row in rows:
            keys = set(row.keys())
            raw_tags = row["tags"] if "tags" in keys else "[]"
            try:
                tags = json.loads(raw_tags) if isinstance(raw_tags, str) else list(raw_tags or [])
            except (TypeError, ValueError):
                tags = []
            entities.append({
                "entity_id": row["entity_id"],
                "title": row["title"],
                "content": row["content"] if "content" in keys else "",
                "full_content": row["full_content"] if "full_content" in keys else "",
                "ai_summary": row["ai_summary"] if "ai_summary" in keys else "",
                "entity_type": row["entity_type"] if "entity_type" in keys else "",
                "importance": row["importance"] if "importance" in keys else 5,
                "tags": tags,
                "book_id": row["book_id"] if "book_id" in keys else "default",
            })

        active_space_id = self.active_space_id()
        inserted = (
            self.add_entities(entities, space_id=active_space_id)
            if entities
            else 0
        )
        active_ids = {entity["entity_id"] for entity in entities}
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            scope_sql = (
                "SELECT DISTINCT entity_id FROM vector_chunks "
                "WHERE embedding_space_id=?"
            )
            scope_params = [active_space_id]
            if book_id is not None:
                scope_sql += " AND book_id=?"
                scope_params.append(book_id)
            indexed_ids = {row[0] for row in conn.execute(scope_sql, scope_params)}
            for entity_id in indexed_ids - active_ids:
                chunk_ids = [
                    row[0]
                    for row in conn.execute(
                        "SELECT chunk_id FROM vector_chunks "
                        "WHERE entity_id=? AND embedding_space_id=?",
                        (entity_id, active_space_id),
                    )
                ]
                conn.executemany(
                    "DELETE FROM vector_chunks_vec_v3 WHERE chunk_id=?",
                    ((chunk_id,) for chunk_id in chunk_ids),
                )
                conn.execute(
                    "DELETE FROM vector_chunks WHERE entity_id=? "
                    "AND embedding_space_id=?",
                    (entity_id, active_space_id),
                )
            orphan_sql = (
                "SELECT chunk_id FROM vector_chunks "
                "WHERE (embedding_space_id IS NULL OR embedding_space_id='')"
            )
            orphan_params = []
            if book_id is not None:
                orphan_sql += " AND book_id=?"
                orphan_params.append(book_id)
            orphan_ids = [
                row[0] for row in conn.execute(orphan_sql, orphan_params)
            ]
            conn.executemany(
                "DELETE FROM vector_chunks_vec WHERE chunk_id=?",
                ((chunk_id,) for chunk_id in orphan_ids),
            )
            conn.executemany(
                "DELETE FROM vector_chunks_vec_v3 WHERE chunk_id=?",
                ((chunk_id,) for chunk_id in orphan_ids),
            )
            conn.executemany(
                "DELETE FROM vector_chunks WHERE chunk_id=?",
                ((chunk_id,) for chunk_id in orphan_ids),
            )
            if book_id is None:
                conn.execute("UPDATE vector_chunks SET embedding=NULL")
            else:
                conn.execute(
                    "UPDATE vector_chunks SET embedding=NULL WHERE book_id=?",
                    (book_id,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        status = self.index_status()
        return {
            "entities_indexed": len(entities),
            "chunks_indexed": inserted,
            "book_id": book_id,
            "status": status,
        }


_default_store: VectorStore | None = None


def set_default_vector_store(store: VectorStore) -> None:
    global _default_store
    _default_store = store


def get_default_vector_store() -> VectorStore | None:
    return _default_store


def embedding_runtime_summary() -> dict:
    """Return non-sensitive runtime identity for task/result reporting."""
    if _default_store is None:
        return {"available": False, "model_id": None, "execution_provider": None}
    status = _default_store.embedding.status()
    return {
        "available": bool(status.available),
        "model_id": status.model_id,
        "execution_provider": status.execution_provider,
    }


def import_entities_to_vector_store(entities: list[dict]) -> int:
    if _default_store is None:
        raise RuntimeError("Vector store is not initialized")
    return _default_store.add_entities(entities)


def import_entity_to_vector_store(entity_id: str, entity: dict) -> int:
    payload = dict(entity)
    payload["entity_id"] = entity_id
    payload["entity_type"] = payload.get("entity_type") or payload.get("type") or "concept"
    return import_entities_to_vector_store([payload])


def connection_db_path(conn) -> str:
    return conn.execute("PRAGMA database_list").fetchone()[2]


def _queue_sync(db_path: str, entity_ids: list[str], operation: str, error: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vector_sync_queue(
                entity_id TEXT PRIMARY KEY, operation TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO vector_sync_queue(entity_id,operation,attempts,last_error)
            VALUES(?,?,1,?)
            ON CONFLICT(entity_id) DO UPDATE SET
                operation=excluded.operation,
                attempts=vector_sync_queue.attempts+1,
                last_error=excluded.last_error,
                updated_at=CURRENT_TIMESTAMP
            """,
            ((entity_id, operation, error[:200]) for entity_id in entity_ids),
        )
        conn.commit()
    finally:
        conn.close()


def sync_entities_after_commit(db_path: str, entity_ids: list[str], operation: str = "upsert") -> bool:
    if not entity_ids:
        return True
    try:
        if _default_store is None or not _default_store.embedding.status().available:
            raise RuntimeError("Embedding runtime is unavailable")
        store = VectorStore(db_path, _default_store.embedding)
        store.init_db()
        if operation == "delete":
            for entity_id in entity_ids:
                store.delete_entity(entity_id)
        else:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                placeholders = ",".join("?" for _ in entity_ids)
                rows = conn.execute(
                    f"SELECT * FROM entities WHERE entity_id IN ({placeholders}) AND is_active=1",
                    entity_ids,
                ).fetchall()
            finally:
                conn.close()
            payloads = []
            for row in rows:
                keys = set(row.keys())
                try:
                    tags = json.loads(row["tags"] or "[]")
                except (TypeError, ValueError):
                    tags = []
                payloads.append({
                    "entity_id": row["entity_id"],
                    "title": row["title"],
                    "content": row["content"] if "content" in keys else "",
                    "full_content": row["full_content"] if "full_content" in keys else "",
                    "ai_summary": row["ai_summary"] if "ai_summary" in keys else "",
                    "entity_type": row["entity_type"],
                    "importance": row["importance"],
                    "tags": tags,
                    "book_id": row["book_id"],
                })
            store.add_entities(payloads)
        conn = sqlite3.connect(db_path)
        try:
            placeholders = ",".join("?" for _ in entity_ids)
            conn.execute(f"DELETE FROM vector_sync_queue WHERE entity_id IN ({placeholders})", entity_ids)
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:
        _queue_sync(db_path, entity_ids, operation, type(exc).__name__)
        return False
