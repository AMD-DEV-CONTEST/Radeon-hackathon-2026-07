import json
import sqlite3

import pytest

import services.database_registry as registry
from services.embedding_runtime import EmbeddingRuntimeStatus
from services.vector_store import VectorStore


class SpaceEmbeddingProvider:
    is_aetherdb_local = True

    def __init__(self):
        self.batch_calls = 0

    @staticmethod
    def _vector(text):
        vector = [0.0] * 1024
        vector[sum(text.encode("utf-8")) % 1024] = 1.0
        return vector

    def embed(self, text):
        return self._vector(text)

    def embed_batch(self, texts):
        self.batch_calls += 1
        return [self._vector(text) for text in texts]

    def dims(self):
        return 1024

    def status(self):
        return EmbeddingRuntimeStatus(
            True,
            "BAAI/bge-m3",
            "fixture-revision",
            1024,
            "CPUExecutionProvider",
        )


def _entity(entity_id, content):
    return {
        "entity_id": entity_id,
        "title": f"Title {entity_id}",
        "content": content,
        "full_content": "",
        "ai_summary": "",
        "entity_type": "concept",
        "importance": 5,
        "tags": ["fixture"],
        "book_id": "book-a",
    }


def _setup_store(tmp_path):
    db_path = tmp_path / "vectors.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE entities(
            entity_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            full_content TEXT DEFAULT '',
            ai_summary TEXT DEFAULT '',
            entity_type TEXT DEFAULT '',
            importance INTEGER DEFAULT 5,
            tags TEXT DEFAULT '[]',
            book_id TEXT DEFAULT 'default',
            is_active INTEGER DEFAULT 1
        )
        """
    )
    entities = [_entity("alpha", "moon harbor"), _entity("beta", "river road")]
    conn.executemany(
        """INSERT INTO entities(
               entity_id,title,content,full_content,ai_summary,entity_type,
               importance,tags,book_id,is_active
           ) VALUES (?,?,?,?,?,?,?,?,?,1)""",
        (
            (
                item["entity_id"],
                item["title"],
                item["content"],
                item["full_content"],
                item["ai_summary"],
                item["entity_type"],
                item["importance"],
                json.dumps(item["tags"]),
                item["book_id"],
            )
            for item in entities
        ),
    )
    conn.commit()
    conn.close()
    provider = SpaceEmbeddingProvider()
    store = VectorStore(db_path, provider)
    store.init_db()
    store.add_entities(entities)
    return db_path, provider, store, entities


def test_space_build_validate_atomic_activate_and_pointer_only_rollback(tmp_path):
    db_path, provider, store, entities = _setup_store(tmp_path)
    old_space_id = store.active_space_id()
    with sqlite3.connect(db_path) as conn:
        source_before = conn.execute(
            "SELECT entity_id,title,content FROM entities ORDER BY entity_id"
        ).fetchall()
        old_chunk_count = conn.execute(
            "SELECT COUNT(*) FROM vector_chunks WHERE embedding_space_id=?",
            (old_space_id,),
        ).fetchone()[0]

    target = store.create_vector_space()
    assert target["status"] == "building"
    assert target["model_hash"]
    assert target["preprocess_version"] == "bge-m3-dense-l2-v1"
    assert target["chunking_version"] == "char-512-overlap-128-v1"
    assert target["runtime"] == "aetherdb-native-onnxruntime"
    store.add_entities(entities, space_id=target["space_id"])
    validation = store.validate_vector_space(target["space_id"])
    assert validation["valid"] is True
    assert validation["status"] == "ready"

    activated = store.activate_vector_space(target["space_id"])
    assert activated["active_space_id"] == target["space_id"]
    assert activated["rollback_space_id"] == old_space_id
    statuses = {item["space_id"]: item["status"] for item in activated["spaces"]}
    assert statuses[old_space_id] == "retired"
    assert statuses[target["space_id"]] == "active"

    calls_before_rollback = provider.batch_calls
    rolled_back = store.rollback_vector_space()
    assert rolled_back["active_space_id"] == old_space_id
    assert rolled_back["rollback_space_id"] == target["space_id"]
    assert provider.batch_calls == calls_before_rollback

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM vector_chunks WHERE embedding_space_id=?",
            (old_space_id,),
        ).fetchone()[0] == old_chunk_count
        assert conn.execute(
            "SELECT entity_id,title,content FROM entities ORDER BY entity_id"
        ).fetchall() == source_before


def test_source_change_marks_new_space_stale_without_switching_active_pointer(tmp_path):
    db_path, _, store, entities = _setup_store(tmp_path)
    old_space_id = store.active_space_id()
    target = store.create_vector_space()
    store.add_entities(entities, space_id=target["space_id"])

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE entities SET content='changed during migration' WHERE entity_id='alpha'"
        )
        conn.commit()

    validation = store.validate_vector_space(target["space_id"])
    assert validation["valid"] is False
    assert validation["status"] == "failed"
    assert validation["failure_code"] == "SOURCE_REVISION_CHANGED"
    assert validation["stale"] == 1
    assert store.active_space_id() == old_space_id
    with pytest.raises(ValueError, match="validated ready"):
        store.activate_vector_space(target["space_id"])


def test_gc_requires_exact_confirmation_and_preserves_pointer_and_task_references(
    tmp_path,
    monkeypatch,
):
    _, _, store, _ = _setup_store(tmp_path)
    root = tmp_path / "registry"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()

    failed = store.create_vector_space()
    store.mark_vector_space_failed(failed["space_id"], "FIXTURE_FAILURE")
    with pytest.raises(ValueError, match="confirmation mismatch"):
        store.garbage_collect_vector_space(
            failed["space_id"],
            confirm_space_id="wrong-space",
        )

    now = "2026-07-30T00:00:00+00:00"
    with registry._get_registry_conn() as conn:
        conn.execute(
            """INSERT INTO embedding_tasks(
                   id,database_id,task_kind,operation,status,target_space_id,
                   created_at,updated_at
               ) VALUES ('task-ref','default','rebuild','upsert','queued',?,?,?)""",
            (failed["space_id"], now, now),
        )
        conn.commit()
    with pytest.raises(ValueError, match="still references"):
        store.garbage_collect_vector_space(
            failed["space_id"],
            confirm_space_id=failed["space_id"],
        )

    with registry._get_registry_conn() as conn:
        conn.execute(
            "UPDATE embedding_tasks SET status='completed' WHERE id='task-ref'"
        )
        conn.commit()
    result = store.garbage_collect_vector_space(
        failed["space_id"],
        confirm_space_id=failed["space_id"],
    )
    assert result["deleted"] is True
    assert failed["space_id"] not in {
        item["space_id"] for item in store.list_vector_spaces()["spaces"]
    }
    with pytest.raises(ValueError, match="Active or rollback"):
        store.garbage_collect_vector_space(
            store.active_space_id(),
            confirm_space_id=store.active_space_id(),
        )
