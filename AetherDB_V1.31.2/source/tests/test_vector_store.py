import math
import json
import sqlite3

from services.embedding_runtime import EmbeddingRuntimeStatus
from services.vector_store import VectorStore, set_default_vector_store, sync_entities_after_commit
from services.db import close_connection, get_connection


class FixtureEmbeddingProvider:
    is_aetherdb_local = True

    def __init__(self):
        self.batch_calls = 0

    @staticmethod
    def _vector(text):
        vector = [0.0] * 1024
        if "moon" in text.lower() or "月" in text:
            vector[0] = 1.0
        else:
            vector[1] = 1.0
        return vector

    def embed(self, text):
        return self._vector(text)

    def embed_batch(self, texts):
        self.batch_calls += 1
        return [self._vector(text) for text in texts]

    def dims(self):
        return 1024

    def status(self):
        return EmbeddingRuntimeStatus(True, "BAAI/bge-m3", "fixture", 1024, "CPUExecutionProvider")


def test_vec0_batch_write_search_and_atomic_replacement(tmp_path):
    provider = FixtureEmbeddingProvider()
    store = VectorStore(tmp_path / "vectors.db", provider)
    store.init_db()

    inserted = store.add_entities([
        {
            "entity_id": "moon-guard",
            "title": "月港守卫",
            "content": "The moon guardian patrols the harbor.",
            "entity_type": "character",
            "importance": 8,
            "tags": ["moon"],
            "book_id": "book-a",
        },
        {
            "entity_id": "kitchen",
            "title": "厨房",
            "content": "Bread is baking in the kitchen.",
            "entity_type": "location",
            "importance": 3,
            "tags": [],
            "book_id": "book-a",
        },
    ])

    assert inserted == 5
    assert provider.batch_calls == 1
    results = store.search("moon patrol", top_k=2, book_id="book-a")
    assert results[0].entity_id == "moon-guard"
    assert results[0].title == "月港守卫"

    status = store.index_status()
    assert status["chunk_count"] == 5
    assert status["vector_count"] == 5
    assert status["legacy_embedding_count"] == 0
    assert status["rebuild_required"] is False

    store.update_entity(
        "moon-guard",
        title="月港守卫",
        content="Bread room only.",
        entity_type="character",
        importance=8,
        tags=[],
        book_id="book-a",
    )
    status = store.index_status()
    assert status["chunk_count"] == 4
    assert status["vector_count"] == 4


def test_vector_store_rejects_wrong_dimension_without_partial_write(tmp_path):
    provider = FixtureEmbeddingProvider()
    provider.embed_batch = lambda texts: [[1.0, 0.0] for _ in texts]
    store = VectorStore(tmp_path / "vectors.db", provider)
    store.init_db()

    try:
        store.add_entity("bad", "Bad", "bad", "", "", "concept", 5, [])
        raise AssertionError("Expected dimension validation failure")
    except ValueError as exc:
        assert "1024" in str(exc)

    assert store.index_status()["chunk_count"] == 0


def test_entity_chunks_normalizes_model_importance_labels(tmp_path):
    store = VectorStore(tmp_path / "vectors.db", FixtureEmbeddingProvider())

    chunks = store._entity_chunks(
        {
            "entity_id": "concept-high",
            "title": "Label Importance",
            "content": "Model returned a localized importance label.",
            "entity_type": "concept",
            "importance": "\u9ad8",
            "tags": [],
            "book_id": "book-a",
        }
    )

    assert chunks
    assert {chunk["importance"] for chunk in chunks} == {8}


def test_rebuild_uses_authoritative_entities_and_clears_legacy_blobs(tmp_path):
    db_path = tmp_path / "rebuild.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE entities(
            entity_id TEXT PRIMARY KEY, title TEXT, content TEXT, full_content TEXT,
            ai_summary TEXT, entity_type TEXT, importance INTEGER, tags TEXT,
            book_id TEXT, is_active INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO entities VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("active", "月城", "moon city", "", "", "location", 7, json.dumps(["moon"]), "book-a", 1),
    )
    conn.execute(
        "INSERT INTO entities VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("inactive", "旧城", "old city", "", "", "location", 2, "[]", "book-a", 0),
    )
    conn.commit()
    conn.close()

    store = VectorStore(db_path, FixtureEmbeddingProvider())
    store.init_db()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO vector_chunks(entity_id,chunk_type,chunk_text,embedding,book_id) VALUES(?,?,?,?,?)",
        ("inactive", "title", "legacy", b"legacy mock", "book-a"),
    )
    conn.commit()
    conn.close()

    result = store.rebuild_from_entities()

    assert result["entities_indexed"] == 1
    assert result["chunks_indexed"] == 3
    assert result["status"]["legacy_embedding_count"] == 0
    assert result["status"]["chunk_count"] == result["status"]["vector_count"] == 3
    assert result["status"]["rebuild_required"] is False


def test_thread_local_connection_switches_database_paths(tmp_path):
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    close_connection()
    conn1 = get_connection(str(first))
    conn1.execute("CREATE TABLE marker(value TEXT)")
    conn1.execute("INSERT INTO marker VALUES('first')")
    conn1.commit()

    conn2 = get_connection(str(second))
    conn2.execute("CREATE TABLE marker(value TEXT)")
    conn2.execute("INSERT INTO marker VALUES('second')")
    conn2.commit()
    close_connection()

    assert sqlite3.connect(first).execute("SELECT value FROM marker").fetchone()[0] == "first"
    assert sqlite3.connect(second).execute("SELECT value FROM marker").fetchone()[0] == "second"


def test_post_commit_sync_batches_entities_in_scoped_database(tmp_path):
    db_path = tmp_path / "scoped.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE entities(
            entity_id TEXT PRIMARY KEY,title TEXT,content TEXT,full_content TEXT,
            ai_summary TEXT,entity_type TEXT,importance INTEGER,tags TEXT,
            book_id TEXT,is_active INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO entities VALUES(?,?,?,?,?,?,?,?,?,?)",
        [
            ("a", "Moon", "moon", "", "", "concept", 5, "[]", "book-a", 1),
            ("b", "Bread", "bread", "", "", "concept", 5, "[]", "book-a", 1),
        ],
    )
    conn.commit()
    conn.close()
    provider = FixtureEmbeddingProvider()
    root_store = VectorStore(db_path, provider)
    root_store.init_db()
    set_default_vector_store(root_store)

    assert sync_entities_after_commit(str(db_path), ["a", "b"]) is True
    assert provider.batch_calls == 1
    assert root_store.index_status()["vector_count"] == 4
