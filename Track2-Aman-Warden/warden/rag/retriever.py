"""
RAG retriever — similarity search for known attack patterns.

Used by Tier 2 to augment its analysis prompt with relevant known
attacks, improving detection accuracy.
"""

from __future__ import annotations

import logging
import hashlib
from typing import Optional

logger = logging.getLogger(__name__)


class WardenRetriever:
    """
    Retrieves similar known attacks from the pattern vector store.

    Used by the routing engine to augment Tier 2's context with
    relevant known attack examples, improving detection accuracy.
    """

    def __init__(self, db_path: str = "warden_rag_db"):
        self.db_path = db_path
        self._store = None
        self._loaded = False

    def initialize(self) -> bool:
        """Initialize the vector store (ChromaDB)."""
        try:
            import chromadb
            client = chromadb.PersistentClient(path=self.db_path)
            self._store = client.get_or_create_collection(
                name="attack_patterns",
                metadata={"description": "Known attack patterns for RAG augmentation"}
            )
            self._loaded = True
            logger.info(f"RAG retriever initialized: {self.db_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize RAG retriever: {e}")
            return False

    def add_patterns(self, patterns: list[dict]) -> int:
        """
        Add known attack patterns to the vector store.

        Args:
            patterns: List of dicts with {text, type, severity, source}

        Returns:
            Number of patterns added.
        """
        if not self._loaded or not self._store:
            return 0

        documents = []
        metadatas = []
        ids = []

        for i, p in enumerate(patterns):
            text = p.get("text", "")
            documents.append(text)
            metadatas.append({
                "type": p.get("type", "unknown"),
                "severity": p.get("severity", "medium"),
                "source": p.get("source", ""),
            })
            ids.append(f"pattern_{i}_{hashlib.sha1(text.encode()).hexdigest()}")

        try:
            self._store.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
            )
            return len(documents)
        except Exception as e:
            logger.error(f"Failed to add patterns: {e}")
            return 0

    def retrieve_for_check(self, query: str, top_k: int = 3) -> str:
        """
        Find known attacks similar to the query.

        Returns formatted context string for Tier 2's prompt.
        """
        if not self._loaded or not self._store:
            return ""

        try:
            results = self._store.query(
                query_texts=[query],
                n_results=top_k,
            )

            if not results["documents"] or not results["documents"][0]:
                return ""

            context_parts = []
            for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                context_parts.append(
                    f"- [{meta.get('type', 'unknown')}] ({meta.get('severity', 'unknown')}): {doc[:200]}"
                )

            return "\n".join(context_parts)

        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}")
            return ""

    def is_available(self) -> bool:
        return self._loaded
