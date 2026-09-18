"""Persistent local BM25 index."""

from __future__ import annotations

import hashlib
from pathlib import Path

import orjson
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from buildguard.logging_system.jsonl_writer import atomic_write_json
from buildguard.rag.embedding_backend import lexical_tokens
from buildguard.rag.schemas import DocumentChunk, ScoredChunk


def corpus_checksum(chunks: list[DocumentChunk]) -> str:
    material = "\n".join(sorted(chunk.chunk_id for chunk in chunks))
    return hashlib.sha256(material.encode()).hexdigest()


class BM25Index:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.path = self.directory / "bm25.json"
        self.chunks: list[DocumentChunk] = []
        self._index: BM25Okapi | None = None
        self.checksum = corpus_checksum([])

    def build(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = list(chunks)
        tokenized = [lexical_tokens(chunk.content) for chunk in self.chunks]
        self._index = BM25Okapi(tokenized) if tokenized else None
        self.checksum = corpus_checksum(self.chunks)

    def save(self) -> None:
        atomic_write_json(
            self.path,
            {
                "checksum": self.checksum,
                "chunks": [chunk.model_dump(mode="json") for chunk in self.chunks],
            },
        )

    def load(self) -> bool:
        if not self.path.is_file():
            return False
        payload = orjson.loads(self.path.read_bytes())
        chunks = [DocumentChunk.model_validate(item) for item in payload.get("chunks", [])]
        self.build(chunks)
        return bool(self.checksum == payload.get("checksum"))

    def search(self, query: str, top_k: int) -> list[ScoredChunk]:
        if self._index is None or not self.chunks:
            return []
        query_tokens = set(lexical_tokens(query))
        scores = self._index.get_scores(list(query_tokens))
        overlaps = [
            len(query_tokens & set(lexical_tokens(chunk.content))) for chunk in self.chunks
        ]
        order = sorted(
            range(len(scores)),
            key=lambda index: (
                -max(0.0, float(scores[index])),
                -overlaps[index],
                self.chunks[index].chunk_id,
            ),
        )
        return [
            ScoredChunk(
                chunk=self.chunks[index],
                score=max(0.0, float(scores[index])),
                rank=rank,
                source="bm25",
            )
            for rank, index in enumerate(order[:top_k], start=1)
        ]
