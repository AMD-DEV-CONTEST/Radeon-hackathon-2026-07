"""Hermetic runtime database for standalone security batch scripts."""

from __future__ import annotations

import atexit
import json
import os
import sqlite3
import tempfile
from pathlib import Path


def prepare_security_batch_database() -> str:
    project_root = Path(__file__).resolve().parents[1]
    runtime = tempfile.TemporaryDirectory(prefix="aetherdb-security-batch-")
    atexit.register(runtime.cleanup)
    os.environ["AETHERDB_RESOURCE_ROOT"] = str(project_root)
    os.environ["AETHERDB_RUNTIME_ROOT"] = runtime.name
    os.environ["AETHERDB_ENV"] = "test"
    os.environ["AETHERDB_EMBEDDING_PROVIDER"] = "mock"

    from services.database_registry import get_db_path, init_registry
    from services.db import close_connection, init_db
    from services.embedding import MockEmbeddingProvider
    from services.vector_store import VectorStore

    init_registry()
    init_db("default")
    close_connection()
    db_path = get_db_path("default")
    VectorStore(db_path, MockEmbeddingProvider()).init_db()

    conn = sqlite3.connect(db_path)
    try:
        tags = json.dumps(["security-batch"])
        conn.executemany(
            "INSERT INTO entities "
            "(entity_id,entity_type,title,content,tags,importance,book_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                ("BATCH_ENTITY_A", "concept", "Batch A", "test", tags, 1, "default"),
                ("BATCH_ENTITY_B", "concept", "Batch B", "test", tags, 1, "default"),
            ),
        )
        conn.execute(
            "INSERT INTO relations "
            "(source_id,target_id,relation_type,description,book_id) "
            "VALUES (?,?,?,?,?)",
            ("BATCH_ENTITY_A", "BATCH_ENTITY_B", "references", "test", "default"),
        )
        conn.execute(
            "INSERT INTO entity_versions "
            "(entity_id,version,title,content,tags,importance,book_id) "
            "VALUES (?,?,?,?,?,?,?)",
            ("BATCH_ENTITY_A", 1, "Batch A", "test", tags, 1, "default"),
        )
        conn.execute(
            "INSERT INTO vector_chunks "
            "(entity_id,chunk_type,chunk_index,chunk_text,book_id,entity_type,importance) "
            "VALUES (?,?,?,?,?,?,?)",
            ("BATCH_ENTITY_A", "content", 0, "test", "default", "concept", 1),
        )
        conn.execute(
            "INSERT INTO entity_translations "
            "(entity_id,language,title,content,book_id) VALUES (?,?,?,?,?)",
            ("BATCH_ENTITY_A", "en", "Batch A", "test", "default"),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path
