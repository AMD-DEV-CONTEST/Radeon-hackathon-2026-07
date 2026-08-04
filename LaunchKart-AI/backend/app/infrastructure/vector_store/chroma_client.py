"""
LaunchKart AI 2.0 — ChromaDB Vector Store Client

Provides persistent vector storage for agent memory and semantic search.
"""

from __future__ import annotations

from typing import Any

import chromadb
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

_chroma_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    """Get or create the singleton ChromaDB client with persistence."""
    global _chroma_client
    if _chroma_client is None:
        settings = get_settings()
        _chroma_client = chromadb.PersistentClient(
            path=settings.chroma_persist_directory,
        )
        logger.info("ChromaDB client created", persist_dir=settings.chroma_persist_directory)
    return _chroma_client


def get_memory_collection() -> chromadb.Collection:
    """Get or create the main memory collection."""
    settings = get_settings()
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )


async def add_memory(
    doc_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
) -> None:
    """Add a memory entry to the vector store."""
    collection = get_memory_collection()
    kwargs: dict[str, Any] = {
        "ids": [doc_id],
        "documents": [content],
    }
    if metadata:
        kwargs["metadatas"] = [metadata]
    if embedding:
        kwargs["embeddings"] = [embedding]
    collection.add(**kwargs)


async def search_memory(
    query: str,
    n_results: int = 10,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search memory entries by semantic similarity."""
    collection = get_memory_collection()
    kwargs: dict[str, Any] = {
        "query_texts": [query],
        "n_results": n_results,
    }
    if where:
        kwargs["where"] = where
    return collection.query(**kwargs)


async def delete_memory(doc_id: str) -> None:
    """Delete a memory entry from the vector store."""
    collection = get_memory_collection()
    collection.delete(ids=[doc_id])
