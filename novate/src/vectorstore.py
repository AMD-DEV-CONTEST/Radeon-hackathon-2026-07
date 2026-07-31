"""
Persistent local vector store (Chroma) for Nova's RAG capability.

Everything is written to disk under config.VECTOR_DB_DIR and never leaves
the machine. This module is intentionally storage-agnostic at the call
site: `VectorStore.query()` is the only method the rest of the app needs.
"""
from __future__ import annotations

import logging
from typing import List, Tuple

import chromadb
from chromadb.config import Settings

import config
from src.embeddings import LocalEmbedder

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Simple sliding-window chunker (character-based, model-agnostic)."""
    if overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks = []
    start = 0
    text = text.strip()
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return [c for c in chunks if c.strip()]


class VectorStore:
    """Thin wrapper around a persistent Chroma collection."""

    def __init__(
        self,
        persist_dir: str = str(config.VECTOR_DB_DIR),
        collection_name: str = config.COLLECTION_NAME,
        embedder: LocalEmbedder | None = None,
    ) -> None:
        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(collection_name)
        self._embedder = embedder or LocalEmbedder()

    def add_document(self, doc_id: str, text: str, source: str) -> int:
        """Chunk, embed, and upsert a document. Returns number of chunks added."""
        chunks = chunk_text(text, config.RAG_CHUNK_SIZE, config.RAG_CHUNK_OVERLAP)
        if not chunks:
            return 0

        ids = [f"{doc_id}::chunk_{i}" for i in range(len(chunks))]
        embeddings = self._embedder.embed_documents(chunks)
        metadatas = [{"source": source, "chunk_index": i} for i in range(len(chunks))]

        self._collection.upsert(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        logger.info("Indexed %d chunks from '%s'", len(chunks), source)
        return len(chunks)

    def query(self, question: str, top_k: int = config.RAG_TOP_K) -> List[Tuple[str, str, float]]:
        """Return list of (chunk_text, source, distance) for the closest matches."""
        query_embedding = self._embedder.embed_query(question)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        if not results["documents"] or not results["documents"][0]:
            return []

        out = []
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            out.append((doc, meta.get("source", "unknown"), dist))
        return out

    def count(self) -> int:
        return self._collection.count()
