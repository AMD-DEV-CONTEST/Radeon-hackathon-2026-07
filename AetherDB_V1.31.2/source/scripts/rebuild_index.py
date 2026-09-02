"""
rebuild_index.py - Rebuild vector embeddings for all entities in the database.
Usage: python rebuild_index.py [--book-id BOOK_ID]
"""
import sys
import json
import sqlite3

sys.path.insert(0, ".")
from services.embedding import MockEmbeddingProvider
from services.vector_store import VectorStore

DB_PATH = "novel_world_zh.db"

def rebuild(book_id=None):
    print("Initializing vector store...")
    provider = MockEmbeddingProvider()
    store = VectorStore(DB_PATH, provider)
    store.init_db()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if book_id:
        cursor.execute(
            "SELECT * FROM entities WHERE is_active = 1 AND book_id = ?",
            (book_id,)
        )
    else:
        cursor.execute("SELECT * FROM entities WHERE is_active = 1")

    rows = cursor.fetchall()
    total = len(rows)
    print(f"Found {total} active entities to index")

    for i, row in enumerate(rows):
        entity = dict(row)
        try:
            tags = json.loads(entity.get("tags", "[]")) if entity.get("tags") else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        book = entity.get("book_id") or book_id or "default"
        store.add_entity(
            entity["entity_id"],
            entity.get("title", ""),
            entity.get("content", ""),
            entity.get("full_content", "") or entity.get("content", ""),
            entity.get("ai_summary", ""),
            entity.get("entity_type", ""),
            entity.get("importance", 5),
            tags,
            book
        )
        if (i + 1) % 20 == 0 or i == total - 1:
            print(f"  [{i+1}/{total}] {entity['entity_id']} - {entity.get('title', '')[:30]}")

    conn.close()
    print(f"\nDone. Indexed {total} entities.")
    print(f"Embeddings stored in vector_chunks table in {DB_PATH}")

if __name__ == "__main__":
    book_id = None
    if len(sys.argv) > 1 and sys.argv[1].startswith("--book-id="):
        book_id = sys.argv[1].split("=", 1)[1]
    elif len(sys.argv) > 2 and sys.argv[1] == "--book-id":
        book_id = sys.argv[2]
    rebuild(book_id)
