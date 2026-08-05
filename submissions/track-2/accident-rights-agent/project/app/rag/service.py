"""Construction helpers shared by the CLI, graph, and tests."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from app.rag.corpus import LegalCorpusStore
from app.rag.embeddings import BgeM3EmbeddingProvider, HashEmbeddingProvider
from app.rag.index import LegalVectorIndex
from app.rag.reranker import BgeReranker, HeuristicReranker
from app.rag.retrieval import HybridLegalRetriever


def build_embedding(provider: str | None = None):
    selected = provider or os.getenv("EMBEDDING_PROVIDER", "hash")
    if selected == "bge":
        return BgeM3EmbeddingProvider(
            os.environ["BGE_M3_MODEL_PATH"],
            device=os.getenv("EMBEDDING_DEVICE", "cpu"),
            batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "8")),
        )
    if selected != "hash":
        raise ValueError(f"Unsupported embedding provider: {selected}")
    return HashEmbeddingProvider(
        dimension=int(os.getenv("HASH_EMBEDDING_DIMENSION", "384"))
    )


def build_reranker(provider: str | None = None):
    selected = provider or os.getenv("RERANKER_PROVIDER", "heuristic")
    if selected == "bge":
        return BgeReranker(
            os.environ["BGE_RERANKER_MODEL_PATH"],
            device=os.getenv("RERANKER_DEVICE", "cpu"),
        )
    if selected != "heuristic":
        raise ValueError(f"Unsupported reranker provider: {selected}")
    return HeuristicReranker(
        os.getenv(
            "RERANKER_DEGRADED_REASON",
            "BGE reranker not enabled in this runtime; deterministic overlap fallback",
        )
    )


def build_retriever(
    *,
    corpus_path: Path | str | None = None,
    qdrant_path: Path | str | None = None,
    as_of: date | None = None,
    embedding_provider: str | None = None,
    reranker_provider: str | None = None,
) -> HybridLegalRetriever:
    selected_corpus: Path | str = (
        corpus_path or os.getenv("LEGAL_CORPUS_DB") or "data/laws/legal_corpus.sqlite3"
    )
    selected_qdrant: Path | str = (
        qdrant_path or os.getenv("QDRANT_PATH") or "data/qdrant/legal"
    )
    embedding = build_embedding(embedding_provider)
    return HybridLegalRetriever(
        LegalCorpusStore(selected_corpus),
        LegalVectorIndex(selected_qdrant, embedding),
        reranker=build_reranker(reranker_provider),
        as_of=as_of,
    )
