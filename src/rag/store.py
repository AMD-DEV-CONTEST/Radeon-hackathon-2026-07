from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from src.config import RAGConfig, Settings
from src.rag.ingest import chunk_text, load_document


@dataclass
class RetrievedChunk:
    text: str
    source: str
    score: float


class VectorStore:
    def __init__(self, settings: Settings) -> None:
        self.cfg: RAGConfig = settings.rag
        persist = settings.resolve(self.cfg.persist_dir)
        persist.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist))
        self.embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=self.cfg.embedding_model
        )
        self.collection = self.client.get_or_create_collection(
            name=self.cfg.collection,
            embedding_function=self.embedder,
            metadata={"hnsw:space": "cosine"},
        )

    def add_file(self, path: Path) -> int:
        text = load_document(path)
        chunks = chunk_text(text, self.cfg.chunk_size, self.cfg.chunk_overlap)
        if not chunks:
            return 0
        ids = [f"{path.name}-{i}" for i in range(len(chunks))]
        metadatas = [{"source": path.name, "chunk": i} for i in range(len(chunks))]
        self.collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        return len(chunks)

    def add_directory(self, directory: Path) -> int:
        total = 0
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in {
                ".md",
                ".txt",
                ".pdf",
                ".csv",
                ".json",
                ".log",
            }:
                total += self.add_file(path)
        return total

    def ensure_sample_docs(self, directory: Path) -> int:
        """Index sample docs only when the collection is empty (skip slow re-embed)."""
        if self.count() > 0:
            print(f"[kb] already indexed ({self.count()} chunks), skip reindex", flush=True)
            return 0
        if not directory.exists():
            return 0
        print("[kb] indexing sample docs (first boot only)...", flush=True)
        return self.add_directory(directory)

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        k = top_k or self.cfg.top_k
        if self.collection.count() == 0:
            return []
        result = self.collection.query(query_texts=[query], n_results=min(k, self.collection.count()))
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0]
        out: list[RetrievedChunk] = []
        for doc, meta, dist in zip(docs, metas, dists):
            score = 1.0 - float(dist) if dist is not None else 0.0
            out.append(
                RetrievedChunk(
                    text=doc,
                    source=str((meta or {}).get("source", "unknown")),
                    score=score,
                )
            )
        return out

    def count(self) -> int:
        return self.collection.count()
