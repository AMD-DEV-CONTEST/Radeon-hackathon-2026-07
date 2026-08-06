"""
Local Retrieval-Augmented Generation over private documents.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import List, Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class LocalRAG:
    """
    Simple but effective local RAG pipeline.
    Supports .txt, .md, .py and other text files.
    """

    def __init__(
        self,
        persist_path: str = "./data/chroma_rag",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.client = chromadb.PersistentClient(
            path=persist_path,
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        self.collection = self.client.get_or_create_collection(
            name="local_knowledge",
            metadata={"hnsw:space": "cosine"},
        )

        logger.info(f"Loading RAG embedding model: {embedding_model}")
        self.embedder = SentenceTransformer(embedding_model)

    def _chunk_text(self, text: str) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end])
            start = end - self.chunk_overlap
        return chunks

    def ingest_file(self, file_path: str | Path) -> int:
        path = Path(file_path)
        if not path.is_file():
            logger.warning(f"Not a file: {path}")
            return 0

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Failed to read {path}: {e}")
            return 0

        chunks = self._chunk_text(text)
        count = 0
        for chunk in chunks:
            if not chunk.strip():
                continue
            emb = self.embedder.encode(chunk, show_progress_bar=False).tolist()
            self.collection.add(
                documents=[chunk],
                embeddings=[emb],
                metadatas=[{"source": str(path), "filename": path.name}],
                ids=[str(uuid.uuid4())],
            )
            count += 1
        logger.info(f"Ingested {count} chunks from {path.name}")
        return count

    def ingest_folder(self, folder: str | Path, extensions: Optional[List[str]] = None) -> int:
        if extensions is None:
            extensions = [".txt", ".md", ".py", ".rst", ".json", ".yaml", ".yml"]
        folder = Path(folder)
        total = 0
        for ext in extensions:
            for f in folder.rglob(f"*{ext}"):
                total += self.ingest_file(f)
        print(f"Total chunks ingested from {folder}: {total}")
        return total

    def query(self, question: str, k: int = 4) -> str:
        if self.collection.count() == 0:
            return "Knowledge base is empty. Please ingest documents first."
        emb = self.embedder.encode(question, show_progress_bar=False).tolist()
        results = self.collection.query(
            query_embeddings=[emb],
            n_results=min(k, self.collection.count()),
            include=["documents", "metadatas"],
        )
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        parts = []
        for doc, meta in zip(docs, metas):
            source = meta.get("filename", meta.get("source", "unknown"))
            parts.append(f"[Source: {source}]\n{doc}")
        return "\n\n---\n\n".join(parts)

    def count(self) -> int:
        return self.collection.count()
