import json
import sqlite3
import time

import services.database_registry as registry
import services.embedding_tasks as tasks
from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY
from main import app
from services.db import close_connection, init_db
from services.embedding_runtime import EmbeddingRuntimeStatus
from services.vector_store import VectorStore, set_default_vector_store
from tests.asgi_client import asgi_request


class TaskEmbeddingProvider:
    is_aetherdb_local = True

    def __init__(
        self,
        *,
        provider="CPUExecutionProvider",
        detail="",
        fail_marker=None,
        available=True,
    ):
        self.execution_provider = provider
        self.detail = detail
        self.fail_marker = fail_marker
        self.available = available
        self.batch_calls = []

    @staticmethod
    def _vector(text):
        vector = [0.0] * 1024
        vector[sum(text.encode("utf-8")) % 1024] = 1.0
        return vector

    def embed(self, text):
        return self.embed_batch([text])[0]

    def embed_batch(self, texts):
        self.batch_calls.append(list(texts))
        if self.fail_marker and any(self.fail_marker in text for text in texts):
            raise RuntimeError("fixture embedding failure")
        return [self._vector(text) for text in texts]

    def dims(self):
        return 1024

    def status(self):
        return EmbeddingRuntimeStatus(
            self.available,
            "BAAI/bge-m3",
            "fixture-revision",
            1024,
            self.execution_provider,
            self.detail,
        )


class ExternalEmbeddingProvider(TaskEmbeddingProvider):
    is_aetherdb_local = False


def setup_runtime(tmp_path, monkeypatch, provider=None):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    provider = provider or TaskEmbeddingProvider()
    db_path = registry.get_db_path("default")
    store = VectorStore(db_path, provider)
    store.init_db()
    set_default_vector_store(store)
    return db_path, provider, store


def insert_entities(db_path, count, *, marker_entity=None):
    conn = sqlite3.connect(db_path)
    try:
        rows = []
        for index in range(count):
            entity_id = f"TASK_ENTITY_{index:04d}"
            marker = "__FAIL__" if entity_id == marker_entity else f"content-{index}"
            rows.append(
                (
                    entity_id,
                    "concept",
                    f"Title {index}",
                    marker,
                    "[]",
                    5,
                    "default",
                )
            )
        conn.executemany(
            "INSERT INTO entities(entity_id,entity_type,title,content,tags,importance,book_id) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        return [row[0] for row in rows]
    finally:
        conn.close()


def test_dynamic_microbatch_and_content_hash_dedup(tmp_path, monkeypatch):
    db_path, provider, _ = setup_runtime(tmp_path, monkeypatch)
    entity_ids = insert_entities(db_path, 40)
    task = tasks.create_embedding_task(
        "default",
        entity_ids=entity_ids,
        start=False,
    )

    result = tasks.run_embedding_task(task["id"])

    assert result["status"] == "completed"
    assert result["successful_items"] == 40
    assert result["current_batch_size"] > tasks.INITIAL_BATCH_SIZE
    assert result["requested_backend"] == "auto"
    assert result["effective_backend"] == "CPUExecutionProvider"
    first_call_count = len(provider.batch_calls)
    assert first_call_count == 2

    duplicate = tasks.create_embedding_task(
        "default",
        entity_ids=entity_ids,
        start=False,
    )
    duplicate_result = tasks.run_embedding_task(duplicate["id"])
    assert duplicate_result["status"] == "completed"
    assert duplicate_result["skipped_items"] == 40
    assert len(provider.batch_calls) == first_call_count

    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(embedding_task_items)")}
        stored = json.dumps(conn.execute("SELECT * FROM embedding_task_items").fetchall())
    assert "content" not in columns
    assert "content-0" not in stored
    close_connection()


def test_failed_items_are_isolated_and_retry_only_failed_ids(tmp_path, monkeypatch):
    provider = TaskEmbeddingProvider(fail_marker="__FAIL__")
    db_path, _, _ = setup_runtime(tmp_path, monkeypatch, provider)
    failed_id = "TASK_ENTITY_0001"
    entity_ids = insert_entities(db_path, 2, marker_entity=failed_id)
    task = tasks.create_embedding_task("default", entity_ids=entity_ids, start=False)

    result = tasks.run_embedding_task(task["id"])

    assert result["status"] == "partial_failed"
    assert result["successful_items"] == 1
    assert result["failed_items"] == 1
    failed = next(item for item in result["items"] if item["status"] == "failed")
    assert failed["entity_id"] == failed_id
    assert failed["error_code"] == "RuntimeError"

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE entities SET content='repaired' WHERE entity_id=?", (failed_id,))
        conn.commit()
    retry = tasks.retry_failed_embedding_items(task["id"], start=False)
    retry_result = tasks.run_embedding_task(retry["id"])
    assert retry_result["status"] == "completed"
    assert retry_result["total_items"] == retry_result["successful_items"] == 1
    assert retry_result["retry_of"] == task["id"]
    close_connection()


def test_cancel_and_restart_recovery_are_persistent(tmp_path, monkeypatch):
    db_path, _, _ = setup_runtime(tmp_path, monkeypatch)
    entity_ids = insert_entities(db_path, 3)
    task = tasks.create_embedding_task("default", entity_ids=entity_ids, start=False)

    cancelled = tasks.cancel_embedding_task(task["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested"] is True
    assert {item["status"] for item in cancelled["items"]} == {"cancelled"}

    interrupted = tasks.create_embedding_task("default", entity_ids=entity_ids, start=False)
    with sqlite3.connect(registry.REGISTRY_PATH) as conn:
        conn.execute("UPDATE embedding_tasks SET status='running' WHERE id=?", (interrupted["id"],))
        conn.execute(
            "UPDATE embedding_task_items SET status='running' WHERE task_id=? AND entity_id=?",
            (interrupted["id"], entity_ids[0]),
        )
        conn.commit()
    submitted = []
    monkeypatch.setattr(tasks, "_submit_task", submitted.append)
    assert tasks.recover_interrupted_embedding_tasks() == 1
    recovered = tasks.get_embedding_task(interrupted["id"])
    assert recovered["status"] == "queued"
    assert "running" not in {item["status"] for item in recovered["items"]}
    assert submitted == [interrupted["id"]]
    close_connection()


def test_backend_mismatch_and_external_provider_are_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHERDB_EMBEDDING_ACCELERATOR", "cuda")
    db_path, _, _ = setup_runtime(tmp_path, monkeypatch, TaskEmbeddingProvider())
    entity_ids = insert_entities(db_path, 1)
    mismatch = tasks.create_embedding_task("default", entity_ids=entity_ids, start=False)
    mismatch_result = tasks.run_embedding_task(mismatch["id"])
    assert mismatch_result["status"] == "failed"
    assert mismatch_result["requested_backend"] == "cuda"
    assert mismatch_result["effective_backend"] == "CPUExecutionProvider"
    assert mismatch_result["error_code"] == "EMBEDDING_BACKEND_MISMATCH"

    monkeypatch.setenv("AETHERDB_EMBEDDING_ACCELERATOR", "auto")
    external_store = VectorStore(db_path, ExternalEmbeddingProvider())
    external_store.init_db()
    set_default_vector_store(external_store)
    external = tasks.create_embedding_task("default", entity_ids=entity_ids, start=False)
    external_result = tasks.run_embedding_task(external["id"])
    assert external_result["status"] == "failed"
    assert external_result["error_code"] == "EXTERNAL_EMBEDDING_FORBIDDEN"
    close_connection()


def test_auto_cpu_fallback_is_visible_in_task_status(tmp_path, monkeypatch):
    provider = TaskEmbeddingProvider(detail="CUDA initialization failed; using CPU fallback")
    db_path, _, _ = setup_runtime(tmp_path, monkeypatch, provider)
    entity_ids = insert_entities(db_path, 1)
    task = tasks.create_embedding_task("default", entity_ids=entity_ids, start=False)

    result = tasks.run_embedding_task(task["id"])

    assert result["status"] == "completed"
    assert result["effective_backend"] == "CPUExecutionProvider"
    assert result["backend_fallback_detected"] is True
    close_connection()


def test_delete_task_cleans_vectors_when_model_runtime_is_unavailable(tmp_path, monkeypatch):
    db_path, _, store = setup_runtime(tmp_path, monkeypatch)
    entity_ids = insert_entities(db_path, 1)
    initial = tasks.create_embedding_task("default", entity_ids=entity_ids, start=False)
    assert tasks.run_embedding_task(initial["id"])["status"] == "completed"
    assert store.index_status()["vector_count"] > 0

    unavailable = TaskEmbeddingProvider(
        provider=None,
        detail="BGE-M3 model artifacts are missing",
        available=False,
    )
    set_default_vector_store(VectorStore(db_path, unavailable))
    deletion = tasks.create_embedding_task(
        "default",
        entity_ids=entity_ids,
        operation="delete",
        start=False,
    )
    result = tasks.run_embedding_task(deletion["id"])
    assert result["status"] == "completed"
    assert store.index_status()["vector_count"] == 0
    close_connection()


def test_background_rebuild_targets_new_space_without_replacing_active(
    tmp_path,
    monkeypatch,
):
    db_path, provider, store = setup_runtime(tmp_path, monkeypatch)
    entity_ids = insert_entities(db_path, 3)
    original_space_id = store.active_space_id()
    target = store.create_vector_space()
    task = tasks.create_embedding_task(
        "default",
        entity_ids=entity_ids,
        task_kind="rebuild",
        target_space_id=target["space_id"],
        start=False,
    )

    result = tasks.run_embedding_task(task["id"])

    assert result["status"] == "completed"
    assert result["target_space_id"] == target["space_id"]
    assert store.active_space_id() == original_space_id
    validation = store.validate_vector_space(target["space_id"])
    assert validation["valid"] is True
    activated = store.activate_vector_space(target["space_id"])
    assert activated["active_space_id"] == target["space_id"]
    assert activated["rollback_space_id"] == original_space_id
    assert provider.batch_calls
    close_connection()


def test_embedding_task_stops_when_core_runtime_is_unavailable(tmp_path, monkeypatch):
    db_path, provider, store = setup_runtime(tmp_path, monkeypatch)
    provider.manifest = object()
    entity_ids = insert_entities(db_path, 2)
    monkeypatch.setattr(
        tasks,
        "_core_embedding_blocker",
        lambda: ("EMBEDDING_RUNTIME_UNAVAILABLE", "Core BGE-M3 is unavailable"),
    )
    target = store.create_vector_space()
    task = tasks.create_embedding_task(
        "default",
        entity_ids=entity_ids,
        task_kind="rebuild",
        target_space_id=target["space_id"],
        start=False,
    )

    result = tasks.run_embedding_task(task["id"])

    assert result["status"] == "failed"
    assert result["error_code"] == "EMBEDDING_RUNTIME_UNAVAILABLE"
    assert provider.batch_calls == []
    spaces = {item["space_id"]: item for item in store.list_vector_spaces()["spaces"]}
    assert spaces[target["space_id"]]["failure_code"] == "EMBEDDING_RUNTIME_UNAVAILABLE"
    close_connection()


def test_vector_task_api_and_entity_save_are_background_but_chapter_draft_is_not(tmp_path, monkeypatch):
    db_path, _, _ = setup_runtime(tmp_path, monkeypatch)
    entity_ids = insert_entities(db_path, 1)
    admin = {"X-API-Key": ADMIN_API_KEY}
    user = {"X-API-Key": USER_API_KEY}
    payload = {"database_id": "default", "entity_ids": entity_ids}

    assert asgi_request(app, "POST", "/api/vector-index/tasks", json_body=payload)[0] == 401
    status, task = asgi_request(
        app,
        "POST",
        "/api/vector-index/tasks",
        headers=admin,
        json_body=payload,
    )
    assert status == 202
    for _ in range(100):
        task = tasks.get_embedding_task(task["id"])
        if task["status"] in tasks.TERMINAL_STATUSES:
            break
        time.sleep(0.01)
    assert task["status"] == "completed"
    assert asgi_request(
        app,
        "GET",
        f"/api/vector-index/tasks/{task['id']}",
        headers=admin,
    )[0] == 200

    before_save = len(tasks.list_embedding_tasks())
    entity_status, entity_body = asgi_request(
        app,
        "POST",
        "/api/entity",
        headers=user,
        json_body={
            "entity_type": "concept",
            "title": "Background entity",
            "content": "queued locally",
            "book_id": "default",
        },
    )
    assert entity_status == 200
    assert entity_body["vector_task_id"]
    for _ in range(100):
        saved_task = tasks.get_embedding_task(entity_body["vector_task_id"])
        if saved_task["status"] in tasks.TERMINAL_STATUSES:
            break
        time.sleep(0.01)
    assert saved_task["status"] == "completed"
    assert len(tasks.list_embedding_tasks()) == before_save + 1

    before_chapter = len(tasks.list_embedding_tasks())
    chapter_status, _ = asgi_request(
        app,
        "POST",
        "/api/books/default/chapters",
        headers=user,
        params={"title": "Draft only"},
    )
    assert chapter_status == 200
    assert len(tasks.list_embedding_tasks()) == before_chapter
    close_connection()
