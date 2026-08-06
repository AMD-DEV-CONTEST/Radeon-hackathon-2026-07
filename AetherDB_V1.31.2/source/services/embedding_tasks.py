"""Persistent AetherDB-owned background embedding tasks."""

from __future__ import annotations

import json
import logging
import os
import queue
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.database_registry import (
    _get_registry_conn,
    get_database,
    get_db_path,
    list_databases,
)
from services.vector_store import VectorStore, get_default_vector_store


INITIAL_BATCH_SIZE = 16
MIN_BATCH_SIZE = 4
MAX_BATCH_SIZE = 100
TERMINAL_STATUSES = {"completed", "partial_failed", "failed", "cancelled"}
_WORKER_LOCK = threading.Lock()
_STATE_LOCK = threading.RLock()
_RUNNING_TASKS: set[str] = set()
_TASK_QUEUE: queue.Queue[str] = queue.Queue()
_WORKER_THREAD: threading.Thread | None = None
log = logging.getLogger(__name__)


class EmbeddingTaskError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _requested_backend() -> str:
    value = os.environ.get("AETHERDB_EMBEDDING_ACCELERATOR", "auto").strip().lower()
    return value if value in {"auto", "cpu", "cuda", "rocm", "migraphx"} else "auto"


def _public_task(row, *, include_items: bool = False) -> dict:
    task = dict(row)
    task["cancel_requested"] = bool(task["cancel_requested"])
    task["backend_fallback_detected"] = bool(task["backend_fallback_detected"])
    if include_items:
        conn = _get_registry_conn()
        try:
            task["items"] = [
                dict(item)
                for item in conn.execute(
                    "SELECT entity_id,operation,content_hash,status,attempts,error_code,updated_at "
                    "FROM embedding_task_items WHERE task_id=? ORDER BY entity_id,operation",
                    (task["id"],),
                )
            ]
        finally:
            conn.close()
    return task


def get_embedding_task(task_id: str, *, include_items: bool = True) -> dict:
    conn = _get_registry_conn()
    try:
        row = conn.execute("SELECT * FROM embedding_tasks WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise EmbeddingTaskError("EMBEDDING_TASK_NOT_FOUND", "Embedding task was not found")
    return _public_task(row, include_items=include_items)


def list_embedding_tasks(
    database_id: str | None = None,
    status: str | None = None,
    *,
    limit: int = 100,
) -> list[dict]:
    clauses = []
    params: list[object] = []
    if database_id:
        clauses.append("database_id=?")
        params.append(database_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM embedding_tasks{where} ORDER BY created_at DESC,id DESC LIMIT ?",
            (*params, max(1, min(limit, 500))),
        ).fetchall()
        return [_public_task(row) for row in rows]
    finally:
        conn.close()


def _database_id_for_path(db_path: str) -> str:
    expected = Path(db_path).resolve(strict=False)
    for database in list_databases():
        if Path(database["db_path"]).resolve(strict=False) == expected:
            return database["database_id"]
    raise EmbeddingTaskError("DATABASE_NOT_REGISTERED", "Database is not registered")


def _entity_ids_for_scope(database_id: str, book_id: str | None) -> list[str]:
    conn = sqlite3.connect(get_db_path(database_id))
    try:
        sql = "SELECT entity_id FROM entities WHERE is_active=1"
        params = []
        if book_id:
            sql += " AND book_id=?"
            params.append(book_id)
        return [row[0] for row in conn.execute(sql, params)]
    finally:
        conn.close()


def create_embedding_task(
    database_id: str,
    *,
    entity_ids: list[str] | tuple[str, ...] | None = None,
    book_id: str | None = None,
    operation: str = "upsert",
    task_kind: str = "entity_sync",
    retry_of: str | None = None,
    target_space_id: str | None = None,
    start: bool = True,
) -> dict:
    if not get_database(database_id):
        raise EmbeddingTaskError("DATABASE_NOT_FOUND", "Database was not found")
    if operation not in {"upsert", "delete"}:
        raise EmbeddingTaskError("INVALID_OPERATION", "Unsupported embedding operation")
    if task_kind not in {"entity_sync", "rebuild", "retry_failed"}:
        raise EmbeddingTaskError("INVALID_TASK_KIND", "Unsupported embedding task kind")
    if target_space_id and book_id is not None:
        raise EmbeddingTaskError(
            "VECTOR_SPACE_REQUIRES_FULL_SCOPE",
            "Immutable vector space builds must cover the complete database",
        )
    if target_space_id:
        with sqlite3.connect(get_db_path(database_id)) as business:
            target = business.execute(
                "SELECT status FROM vector_spaces WHERE space_id=?",
                (target_space_id,),
            ).fetchone()
        if not target:
            raise EmbeddingTaskError(
                "VECTOR_SPACE_NOT_FOUND",
                "Target vector space was not found",
            )
        if target[0] not in {"building", "failed"}:
            raise EmbeddingTaskError(
                "VECTOR_SPACE_NOT_BUILDABLE",
                "Target vector space is not available for building",
            )
        if target[0] == "failed":
            with sqlite3.connect(get_db_path(database_id)) as business:
                business.execute(
                    "UPDATE vector_spaces SET status='building',failure_code=NULL "
                    "WHERE space_id=? AND status='failed'",
                    (target_space_id,),
                )
                business.commit()
    ids = list(dict.fromkeys(entity_ids or _entity_ids_for_scope(database_id, book_id)))
    if len(ids) > 100_000:
        raise EmbeddingTaskError("TOO_MANY_ITEMS", "Embedding task exceeds the item limit")
    now = _now()
    conn = _get_registry_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if task_kind == "rebuild":
            existing = conn.execute(
                "SELECT * FROM embedding_tasks WHERE database_id=? AND book_id IS ? "
                "AND target_space_id IS ? AND task_kind='rebuild' "
                "AND status IN ('queued','running') "
                "ORDER BY created_at DESC LIMIT 1",
                (database_id, book_id, target_space_id),
            ).fetchone()
            if existing:
                conn.commit()
                task = _public_task(existing)
                if start:
                    _submit_task(task["id"])
                return task
        task_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO embedding_tasks "
            "(id,database_id,book_id,task_kind,operation,status,requested_backend,"
            "total_items,current_batch_size,retry_of,target_space_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'queued',?,?,?,?,?,?,?)",
            (
                task_id,
                database_id,
                book_id,
                task_kind,
                operation,
                _requested_backend(),
                len(ids),
                INITIAL_BATCH_SIZE,
                retry_of,
                target_space_id,
                now,
                now,
            ),
        )
        conn.executemany(
            "INSERT INTO embedding_task_items "
            "(task_id,entity_id,operation,status,updated_at) VALUES (?,?,?,'queued',?)",
            ((task_id, entity_id, operation, now) for entity_id in ids),
        )
        conn.commit()
    finally:
        conn.close()
    if start:
        _submit_task(task_id)
    return get_embedding_task(task_id, include_items=False)


def enqueue_entity_sync_task_by_path(
    db_path: str,
    entity_ids: list[str],
    operation: str = "upsert",
) -> dict:
    database_id = _database_id_for_path(db_path)
    return create_embedding_task(
        database_id,
        entity_ids=entity_ids,
        operation=operation,
        task_kind="entity_sync",
    )


def _submit_task(task_id: str) -> None:
    global _WORKER_THREAD
    with _STATE_LOCK:
        if task_id in _RUNNING_TASKS:
            return
        _RUNNING_TASKS.add(task_id)
        _TASK_QUEUE.put(task_id)
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            _WORKER_THREAD = threading.Thread(
                target=_worker_loop,
                name="embedding-task-worker",
                daemon=True,
            )
            _WORKER_THREAD.start()


def wait_for_embedding_tasks(timeout: float = 5.0) -> bool:
    """Wait until the process-local task queue is idle without stopping its worker."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        with _STATE_LOCK:
            idle = not _RUNNING_TASKS and _TASK_QUEUE.unfinished_tasks == 0
        if idle:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def _worker_loop() -> None:
    while True:
        task_id = _TASK_QUEUE.get()
        try:
            try:
                run_embedding_task(task_id)
            except EmbeddingTaskError as exc:
                if exc.code != "EMBEDDING_TASK_NOT_FOUND":
                    log.warning("Embedding task %s stopped: %s", task_id, exc.code)
            except sqlite3.OperationalError as exc:
                if "no such table: embedding_tasks" not in str(exc):
                    log.exception("Embedding task %s database error", task_id)
            except Exception:
                log.exception("Embedding task %s crashed", task_id)
        finally:
            with _STATE_LOCK:
                _RUNNING_TASKS.discard(task_id)
            _TASK_QUEUE.task_done()


def _set_task_error(task_id: str, code: str, message: str) -> None:
    now = _now()
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE embedding_task_items SET status='failed',attempts=attempts+1,"
            "error_code=?,updated_at=? WHERE task_id=? AND status IN ('queued','running')",
            (code, now, task_id),
        )
        conn.execute(
            "UPDATE embedding_tasks SET status='failed',processed_items=total_items,"
            "failed_items=total_items,error_code=?,error_message=?,completed_at=?,updated_at=? "
            "WHERE id=?",
            (code, message, now, now, task_id),
        )
        conn.commit()
    finally:
        conn.close()
    _mark_target_space_failed(task_id, code)


def _mark_target_space_failed(task_id: str, failure_code: str) -> None:
    conn = _get_registry_conn()
    try:
        task = conn.execute(
            "SELECT database_id,target_space_id FROM embedding_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if not task or not task["target_space_id"]:
        return
    with sqlite3.connect(get_db_path(task["database_id"])) as business:
        business.execute(
            """UPDATE vector_spaces
                  SET status='failed',failure_code=?
                WHERE space_id=?
                  AND status IN ('building','validating','ready','failed')""",
            (failure_code[:96], task["target_space_id"]),
        )
        business.commit()


def _runtime_for_task(task_id: str, *, require_available: bool = True):
    root_store = get_default_vector_store()
    if root_store is None:
        from services.embedding import create_embedding_provider

        embedding = create_embedding_provider()
    else:
        embedding = root_store.embedding
    if embedding.is_aetherdb_local is not True:
        raise EmbeddingTaskError(
            "EXTERNAL_EMBEDDING_FORBIDDEN",
            "Embedding tasks require the AetherDB-owned local runtime",
        )
    status = embedding.status()
    if require_available and not status.available:
        raise EmbeddingTaskError("EMBEDDING_RUNTIME_UNAVAILABLE", "Embedding runtime is unavailable")
    blocker = (
        _core_embedding_blocker()
        if getattr(embedding, "manifest", None) is not None
        else None
    )
    if require_available and blocker is not None:
        raise EmbeddingTaskError(*blocker)
    task = get_embedding_task(task_id, include_items=False)
    requested = task["requested_backend"]
    expected = {
        "cpu": "CPUExecutionProvider",
        "cuda": "CUDAExecutionProvider",
        "rocm": "MIGraphXExecutionProvider",
        "migraphx": "MIGraphXExecutionProvider",
    }.get(requested)
    fallback = "fallback" in (status.detail or "").lower()
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE embedding_tasks SET effective_backend=?,backend_fallback_detected=?,"
            "model_id=?,model_revision=?,updated_at=? WHERE id=?",
            (
                status.execution_provider,
                int(fallback),
                status.model_id,
                status.revision,
                _now(),
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    if require_available and expected and status.execution_provider != expected:
        raise EmbeddingTaskError(
            "EMBEDDING_BACKEND_MISMATCH",
            "Effective embedding backend does not match the requested backend",
        )
    return embedding


def _core_embedding_blocker() -> tuple[str, str] | None:
    try:
        from services.model_runtime.core_service import get_core_embedding_service

        status = get_core_embedding_service().status()
    except Exception:
        return None
    state = status.get("state")
    if state == "unavailable":
        return (
            "EMBEDDING_RUNTIME_UNAVAILABLE",
            status.get("detail") or "Embedding runtime is unavailable",
        )
    return None


def _load_entity(database_id: str, entity_id: str) -> dict | None:
    conn = sqlite3.connect(get_db_path(database_id))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id=? AND is_active=1",
            (entity_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    keys = set(row.keys())
    try:
        tags = json.loads(row["tags"] or "[]")
    except (TypeError, json.JSONDecodeError):
        tags = []
    return {
        "entity_id": row["entity_id"],
        "title": row["title"],
        "content": row["content"] if "content" in keys else "",
        "full_content": row["full_content"] if "full_content" in keys else "",
        "ai_summary": row["ai_summary"] if "ai_summary" in keys else "",
        "entity_type": row["entity_type"],
        "importance": row["importance"],
        "tags": tags,
        "book_id": row["book_id"],
    }


def _estimated_tokens(store: VectorStore, entities: list[dict]) -> int:
    return sum(
        max(1, len(chunk["chunk_text"]) // 4)
        for entity in entities
        for chunk in store._entity_chunks(entity)
    )


def _next_batch_size(current: int, token_count: int, elapsed_ms: float) -> int:
    if elapsed_ms >= 4000 or token_count >= 24_000:
        return max(MIN_BATCH_SIZE, current // 2)
    if elapsed_ms <= 1500 and token_count <= 12_000:
        return min(MAX_BATCH_SIZE, current + max(4, current // 2))
    return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, current))


def _task_cancel_requested(task_id: str) -> bool:
    conn = _get_registry_conn()
    try:
        row = conn.execute(
            "SELECT cancel_requested FROM embedding_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def _set_item_status(
    task_id: str,
    entity_id: str,
    operation: str,
    status: str,
    *,
    content_hash: str | None = None,
    error_code: str | None = None,
    increment_attempt: bool = False,
) -> None:
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE embedding_task_items SET status=?,content_hash=COALESCE(?,content_hash),"
            "error_code=?,attempts=attempts+?,updated_at=? "
            "WHERE task_id=? AND entity_id=? AND operation=?",
            (
                status,
                content_hash,
                error_code,
                int(increment_attempt),
                _now(),
                task_id,
                entity_id,
                operation,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _refresh_task_counts(task_id: str, batch_size: int) -> None:
    conn = _get_registry_conn()
    try:
        counts = dict(
            conn.execute(
                "SELECT status,COUNT(*) FROM embedding_task_items WHERE task_id=? GROUP BY status",
                (task_id,),
            )
        )
        processed = sum(counts.get(name, 0) for name in ("completed", "failed", "skipped", "cancelled"))
        conn.execute(
            "UPDATE embedding_tasks SET processed_items=?,successful_items=?,failed_items=?,"
            "skipped_items=?,current_batch_size=?,updated_at=? WHERE id=?",
            (
                processed,
                counts.get("completed", 0),
                counts.get("failed", 0),
                counts.get("skipped", 0),
                batch_size,
                _now(),
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _finish_task(task_id: str, cancelled: bool = False) -> None:
    now = _now()
    conn = _get_registry_conn()
    try:
        if cancelled:
            conn.execute(
                "UPDATE embedding_task_items SET status='cancelled',updated_at=? "
                "WHERE task_id=? AND status IN ('queued','running')",
                (now, task_id),
            )
        counts = dict(
            conn.execute(
                "SELECT status,COUNT(*) FROM embedding_task_items WHERE task_id=? GROUP BY status",
                (task_id,),
            )
        )
        if cancelled:
            status, code, message = "cancelled", "USER_CANCELLED", "Embedding task was cancelled"
        elif counts.get("failed", 0) and counts.get("completed", 0) + counts.get("skipped", 0):
            status, code, message = "partial_failed", "ITEM_FAILURES", "Some embedding items failed"
        elif counts.get("failed", 0):
            status, code, message = "failed", "ITEM_FAILURES", "Embedding items failed"
        else:
            status, code, message = "completed", None, None
        processed = sum(counts.get(name, 0) for name in ("completed", "failed", "skipped", "cancelled"))
        conn.execute(
            "UPDATE embedding_tasks SET status=?,processed_items=?,successful_items=?,"
            "failed_items=?,skipped_items=?,error_code=?,error_message=?,completed_at=?,"
            "updated_at=? WHERE id=?",
            (
                status,
                processed,
                counts.get("completed", 0),
                counts.get("failed", 0),
                counts.get("skipped", 0),
                code,
                message,
                now,
                now,
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    if status != "completed":
        _mark_target_space_failed(task_id, code or "BUILD_FAILED")


def _process_upsert_batch(
    task_id: str,
    store: VectorStore,
    items: list[dict],
    *,
    target_space_id: str | None = None,
) -> tuple[int, float]:
    entities = []
    entity_by_id = {}
    for item in items:
        entity = _load_entity(item["database_id"], item["entity_id"])
        if not entity:
            _set_item_status(
                task_id,
                item["entity_id"],
                item["operation"],
                "skipped",
                error_code="ENTITY_NOT_ACTIVE",
            )
            continue
        content_hash = store.entity_content_hash(entity)
        if store.entity_is_current(entity, space_id=target_space_id):
            _set_item_status(
                task_id,
                item["entity_id"],
                item["operation"],
                "skipped",
                content_hash=content_hash,
            )
            continue
        entities.append(entity)
        entity_by_id[entity["entity_id"]] = (entity, content_hash, item["operation"])
        _set_item_status(task_id, item["entity_id"], item["operation"], "running")
    if not entities:
        return 0, 0.0
    token_count = _estimated_tokens(store, entities)
    started = time.perf_counter()
    try:
        store.add_entities(entities, space_id=target_space_id)
        for entity in entities:
            _, content_hash, operation = entity_by_id[entity["entity_id"]]
            _set_item_status(
                task_id,
                entity["entity_id"],
                operation,
                "completed",
                content_hash=content_hash,
                increment_attempt=True,
            )
    except Exception:
        for entity in entities:
            _, content_hash, operation = entity_by_id[entity["entity_id"]]
            if _task_cancel_requested(task_id):
                _set_item_status(task_id, entity["entity_id"], operation, "cancelled")
                continue
            try:
                store.add_entities([entity], space_id=target_space_id)
                _set_item_status(
                    task_id,
                    entity["entity_id"],
                    operation,
                    "completed",
                    content_hash=content_hash,
                    increment_attempt=True,
                )
            except Exception as exc:
                _set_item_status(
                    task_id,
                    entity["entity_id"],
                    operation,
                    "failed",
                    content_hash=content_hash,
                    error_code=type(exc).__name__[:80],
                    increment_attempt=True,
                )
    return token_count, (time.perf_counter() - started) * 1000


def run_embedding_task(task_id: str) -> dict:
    with _WORKER_LOCK:
        task = get_embedding_task(task_id, include_items=False)
        if task["status"] in TERMINAL_STATUSES:
            return get_embedding_task(task_id)
        if task["cancel_requested"]:
            _finish_task(task_id, cancelled=True)
            return get_embedding_task(task_id)
        try:
            embedding = _runtime_for_task(
                task_id,
                require_available=task["operation"] != "delete",
            )
        except EmbeddingTaskError as exc:
            _set_task_error(task_id, exc.code, str(exc))
            return get_embedding_task(task_id)
        now = _now()
        conn = _get_registry_conn()
        try:
            conn.execute(
                "UPDATE embedding_tasks SET status='running',started_at=COALESCE(started_at,?),"
                "updated_at=? WHERE id=? AND status='queued'",
                (now, now, task_id),
            )
            conn.commit()
        finally:
            conn.close()
        store = VectorStore(get_db_path(task["database_id"]), embedding)
        store.init_db()
        batch_size = int(task["current_batch_size"] or INITIAL_BATCH_SIZE)
        while True:
            if _task_cancel_requested(task_id):
                _finish_task(task_id, cancelled=True)
                break
            conn = _get_registry_conn()
            try:
                rows = conn.execute(
                    "SELECT entity_id,operation FROM embedding_task_items "
                    "WHERE task_id=? AND status='queued' ORDER BY entity_id LIMIT ?",
                    (task_id, batch_size),
                ).fetchall()
            finally:
                conn.close()
            if not rows:
                _finish_task(task_id)
                break
            items = [
                {
                    "database_id": task["database_id"],
                    "entity_id": row["entity_id"],
                    "operation": row["operation"],
                }
                for row in rows
            ]
            if task["operation"] == "delete":
                for item in items:
                    try:
                        store.delete_entity(
                            item["entity_id"],
                            space_id=task.get("target_space_id"),
                        )
                        _set_item_status(
                            task_id,
                            item["entity_id"],
                            item["operation"],
                            "completed",
                            increment_attempt=True,
                        )
                    except Exception as exc:
                        _set_item_status(
                            task_id,
                            item["entity_id"],
                            item["operation"],
                            "failed",
                            error_code=type(exc).__name__[:80],
                            increment_attempt=True,
                        )
                token_count, elapsed_ms = 0, 0.0
            else:
                token_count, elapsed_ms = _process_upsert_batch(
                    task_id,
                    store,
                    items,
                    target_space_id=task.get("target_space_id"),
                )
            batch_size = _next_batch_size(batch_size, token_count, elapsed_ms)
            _refresh_task_counts(task_id, batch_size)
        return get_embedding_task(task_id)


def cancel_embedding_task(task_id: str) -> dict:
    task = get_embedding_task(task_id, include_items=False)
    if task["status"] in TERMINAL_STATUSES:
        return get_embedding_task(task_id)
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE embedding_tasks SET cancel_requested=1,updated_at=? WHERE id=?",
            (_now(), task_id),
        )
        conn.commit()
    finally:
        conn.close()
    if task["status"] == "queued":
        _finish_task(task_id, cancelled=True)
    return get_embedding_task(task_id)


def retry_failed_embedding_items(task_id: str, *, start: bool = True) -> dict:
    task = get_embedding_task(task_id, include_items=False)
    conn = _get_registry_conn()
    try:
        failed_ids = [
            row[0]
            for row in conn.execute(
                "SELECT entity_id FROM embedding_task_items WHERE task_id=? AND status='failed'",
                (task_id,),
            )
        ]
        existing = conn.execute(
            "SELECT * FROM embedding_tasks WHERE retry_of=? AND status IN ('queued','running') "
            "ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if existing:
        return _public_task(existing)
    if not failed_ids:
        raise EmbeddingTaskError("NO_FAILED_ITEMS", "Embedding task has no failed items")
    return create_embedding_task(
        task["database_id"],
        entity_ids=failed_ids,
        book_id=task["book_id"],
        operation=task["operation"],
        task_kind="retry_failed",
        retry_of=task_id,
        target_space_id=task.get("target_space_id"),
        start=start,
    )


def recover_interrupted_embedding_tasks() -> int:
    now = _now()
    conn = _get_registry_conn()
    try:
        conn.execute(
            "UPDATE embedding_task_items SET status='queued',error_code=NULL,updated_at=? "
            "WHERE status='running'",
            (now,),
        )
        cursor = conn.execute(
            "UPDATE embedding_tasks SET status='queued',error_code='INTERRUPTED',"
            "error_message='Embedding task resumed after restart',updated_at=? "
            "WHERE status='running'",
            (now,),
        )
        queued = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM embedding_tasks WHERE status='queued' AND cancel_requested=0"
            )
        ]
        conn.commit()
    finally:
        conn.close()
    for task_id in queued:
        _submit_task(task_id)
    return cursor.rowcount
