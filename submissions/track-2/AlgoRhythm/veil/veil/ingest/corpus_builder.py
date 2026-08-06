"""Build the auxiliary corpus: SQLite FTS5 + Qdrant, from one pass over the files.

Run this once before the demo:

    python -m veil.ingest.corpus_builder corpus/meridian

Both stores are written together so the hybrid retriever in tools/corpus_search.py
can never see a dense index and a lexical index that disagree about what exists.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from veil.config import CONFIG
from veil.ingest.chunker import Chunk, chunk_text
from veil.ingest.loader import load_document

_SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_chunks (
    id      INTEGER PRIMARY KEY,
    text    TEXT NOT NULL,
    source  TEXT NOT NULL,
    idx     INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS corpus_fts
    USING fts5(text, source, content='corpus_chunks', content_rowid='id');
"""


def collect_chunks(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    files = sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith("."))
    for path in files:
        doc = load_document(str(path))
        if not doc.get("ok") or not doc["text"]:
            print(f"  skip {path.name}: {doc.get('error', 'no text')}")
            continue
        got = chunk_text(doc["text"], source=path.name)
        chunks.extend(got)
        print(f"  {path.name}: {len(got)} chunks")
    return chunks


def write_sqlite(chunks: list[Chunk]) -> None:
    con = sqlite3.connect(CONFIG.storage.db_path)
    try:
        con.executescript(_SCHEMA)
        con.execute("DELETE FROM corpus_chunks")
        con.execute("DELETE FROM corpus_fts")
        con.executemany(
            "INSERT INTO corpus_chunks (text, source, idx) VALUES (?,?,?)",
            [(c.text, c.source, c.index) for c in chunks],
        )
        # Rebuild rather than incrementally sync: the corpus is small and a
        # stale FTS index would silently degrade every correlational finding.
        con.execute("INSERT INTO corpus_fts(corpus_fts) VALUES('rebuild')")
        con.commit()
    finally:
        con.close()


def write_qdrant(chunks: list[Chunk]) -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(CONFIG.storage.embedding_model)
    vectors = model.encode(
        [c.text for c in chunks], normalize_embeddings=True, show_progress_bar=True
    )

    client = QdrantClient(path=CONFIG.storage.qdrant_path)
    client.recreate_collection(
        collection_name=CONFIG.storage.collection,
        vectors_config=VectorParams(size=vectors.shape[1], distance=Distance.COSINE),
    )
    client.upsert(
        collection_name=CONFIG.storage.collection,
        points=[
            PointStruct(
                id=i,
                vector=v.tolist(),
                payload={"text": c.text, "source": c.source, "idx": c.index},
            )
            for i, (c, v) in enumerate(zip(chunks, vectors))
        ],
    )


def build(root: str) -> None:
    path = Path(root)
    if not path.exists():
        raise SystemExit(f"Corpus directory not found: {root}")

    print(f"Reading {path}...")
    chunks = collect_chunks(path)
    if not chunks:
        raise SystemExit("No chunks produced — nothing to index.")

    print(f"\n{len(chunks)} chunks total")
    print("Writing SQLite + FTS5...")
    write_sqlite(chunks)
    print("Embedding and writing Qdrant...")
    write_qdrant(chunks)
    print(f"\nDone. Corpus ready at {CONFIG.storage.db_path} + {CONFIG.storage.qdrant_path}")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "corpus/meridian")
