"""ChromaDB vector store wrapper for code chunk storage and retrieval."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .parser import CodeChunk

logger = logging.getLogger(__name__)


class VectorStore:
    """Persistent vector store backed by ChromaDB."""

    def __init__(self, persist_dir: str) -> None:
        self.persist_dir = str(Path(persist_dir).resolve())
        self._client: Any = None
        self._collection: Any = None

    def _ensure_loaded(self) -> None:
        if self._client is not None:
            return
        import chromadb
        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=self.persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, chunks: list[CodeChunk], embeddings: list[list[float]]) -> None:
        """Add code chunks with their embeddings to the store."""
        self._ensure_loaded()
        if not chunks:
            return

        ids = [f"{c.file_path}:{c.start_line}:{c.symbol_name}" for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [c.to_metadata() for c in chunks]

        # ChromaDB requires non-null metadata values; sanitize
        for m in metadatas:
            for k, v in list(m.items()):
                if v is None:
                    m[k] = ""

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """Query the store by embedding vector.

        Returns list of dicts with keys: content, file_path, symbol_name,
        symbol_kind, start_line, end_line, qualified_name, score.
        """
        self._ensure_loaded()
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.count()),
        )

        items: list[dict[str, Any]] = []
        if not results or not results.get("ids") or not results["ids"][0]:
            return items

        ids = results["ids"][0]
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0] if "distances" in results else [0.0] * len(ids)

        for i in range(len(ids)):
            meta = metadatas[i]
            items.append({
                "content": documents[i],
                "file_path": meta.get("file_path", ""),
                "symbol_name": meta.get("symbol_name", ""),
                "symbol_kind": meta.get("symbol_kind", ""),
                "start_line": meta.get("start_line", 0),
                "end_line": meta.get("end_line", 0),
                "qualified_name": meta.get("qualified_name", ""),
                "score": 1.0 - float(distances[i]),  # cosine distance -> similarity
            })
        return items

    def delete_by_file(self, file_path: str) -> None:
        """Delete all chunks belonging to a file."""
        self._ensure_loaded()
        self._collection.delete(where={"file_path": file_path})

    def count(self) -> int:
        """Return number of stored chunks."""
        self._ensure_loaded()
        try:
            return self._collection.count()
        except Exception:
            return 0

    def clear(self) -> None:
        """Remove all chunks."""
        self._ensure_loaded()
        self._client.delete_collection("code_chunks")
        self._collection = self._client.get_or_create_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"},
        )
