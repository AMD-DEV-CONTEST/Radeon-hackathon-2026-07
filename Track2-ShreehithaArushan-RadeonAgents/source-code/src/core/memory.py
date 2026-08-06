"""
Memory management: short-term conversation buffer + long-term vector store.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Dual memory system:
    - Short-term: rolling conversation history
    - Long-term: persistent semantic memory via Chroma
    """

    def __init__(
        self,
        max_history: int = 20,
        vector_store_path: str = "./data/chroma_db",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        self.max_history = max_history
        self.short_term: deque = deque(maxlen=max_history)

        self.client = chromadb.PersistentClient(
            path=vector_store_path,
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        self.collection = self.client.get_or_create_collection(
            name="agent_long_term_memory",
            metadata={"hnsw:space": "cosine"},
        )

        logger.info(f"Loading embedding model: {embedding_model}")
        self.embedder = SentenceTransformer(embedding_model)

    def add_message(self, role: str, content: str) -> None:
        self.short_term.append({"role": role, "content": content})

    def get_history(self, last_n: Optional[int] = None) -> List[Dict[str, str]]:
        history = list(self.short_term)
        if last_n is not None:
            return history[-last_n:]
        return history

    def clear_short_term(self) -> None:
        self.short_term.clear()

    def store_long_term(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        id: Optional[str] = None,
    ) -> str:
        doc_id = id or str(uuid.uuid4())
        embedding = self.embedder.encode(text, show_progress_bar=False).tolist()
        self.collection.add(
            documents=[text],
            embeddings=[embedding],
            metadatas=[metadata or {}],
            ids=[doc_id],
        )
        return doc_id

    def retrieve(
        self,
        query: str,
        k: int = 5,
        where: Optional[Dict] = None,
    ) -> List[str]:
        if self.collection.count() == 0:
            return []
        embedding = self.embedder.encode(query, show_progress_bar=False).tolist()
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(k, self.collection.count()),
            where=where,
        )
        return results["documents"][0] if results and results["documents"] else []

    def retrieve_with_metadata(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        if self.collection.count() == 0:
            return []
        embedding = self.embedder.encode(query, show_progress_bar=False).tolist()
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        out = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            out.append({"text": doc, "metadata": meta, "distance": dist})
        return out
