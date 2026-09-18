"""FAISS cosine-similarity index with persisted chunk mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import orjson

from buildguard.exceptions import RagIndexError
from buildguard.logging_system.jsonl_writer import atomic_write_json
from buildguard.rag.bm25_index import corpus_checksum
from buildguard.rag.embedding_backend import EmbeddingBackend
from buildguard.rag.schemas import DocumentChunk, ScoredChunk


class DenseIndex:
    def __init__(self, directory: Path, backend: EmbeddingBackend) -> None:
        self.directory = directory.resolve()
        self.index_path = self.directory / "dense.faiss"
        self.metadata_path = self.directory / "dense_metadata.json"
        self.backend = backend
        self.chunks: list[DocumentChunk] = []
        self.index: Any | None = None
        self.checksum = corpus_checksum([])

    @staticmethod
    def _faiss() -> Any:
        try:
            import faiss

            return faiss
        except ImportError as exc:
            raise RagIndexError("faiss-cpu is required for the dense index") from exc

    def build(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = list(chunks)
        self.checksum = corpus_checksum(self.chunks)
        faiss = self._faiss()
        self.index = faiss.IndexFlatIP(self.backend.dimension)
        if self.chunks:
            vectors = self.backend.encode([chunk.content for chunk in self.chunks])
            if vectors.shape != (len(self.chunks), self.backend.dimension):
                raise RagIndexError(
                    f"Embedding shape mismatch: {vectors.shape}, expected "
                    f"({len(self.chunks)}, {self.backend.dimension})"
                )
            self.index.add(np.ascontiguousarray(vectors, dtype=np.float32))

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.index is None:
            self.build(self.chunks)
        self._faiss().write_index(self.index, str(self.index_path))
        atomic_write_json(
            self.metadata_path,
            {
                "checksum": self.checksum,
                "dimension": self.backend.dimension,
                "chunks": [chunk.model_dump(mode="json") for chunk in self.chunks],
            },
        )

    def load(self) -> bool:
        if not self.index_path.is_file() or not self.metadata_path.is_file():
            return False
        payload = orjson.loads(self.metadata_path.read_bytes())
        if int(payload.get("dimension", -1)) != self.backend.dimension:
            raise RagIndexError("Dense index dimension does not match embedding backend")
        self.chunks = [
            DocumentChunk.model_validate(item) for item in payload.get("chunks", [])
        ]
        self.checksum = corpus_checksum(self.chunks)
        if self.checksum != payload.get("checksum"):
            raise RagIndexError("Dense index metadata checksum mismatch")
        self.index = self._faiss().read_index(str(self.index_path))
        if self.index.ntotal != len(self.chunks):
            raise RagIndexError("Dense index vector count does not match metadata")
        return True

    def search(self, query: str, top_k: int) -> list[ScoredChunk]:
        if self.index is None or not self.chunks:
            return []
        vector = self.backend.encode_queries([query])
        scores, indexes = self.index.search(
            np.ascontiguousarray(vector, dtype=np.float32),
            min(top_k, len(self.chunks)),
        )
        results: list[ScoredChunk] = []
        for rank, (index, score) in enumerate(zip(indexes[0], scores[0]), start=1):
            if index < 0:
                continue
            results.append(
                ScoredChunk(
                    chunk=self.chunks[int(index)],
                    score=float(score),
                    rank=rank,
                    source="dense",
                )
            )
        return results
