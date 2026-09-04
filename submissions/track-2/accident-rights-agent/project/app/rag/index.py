"""Persistent Qdrant local-mode index."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Iterable

from qdrant_client import QdrantClient, models

from app.rag.embeddings import EmbeddingProvider
from app.schemas.legal import LegalChunk


COLLECTION_NAME = "legal_chunks_v2"


def point_id(source_id: str) -> int:
    digest = hashlib.sha256(source_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


class LegalVectorIndex:
    def __init__(
        self,
        path: Path | str,
        embedding: EmbeddingProvider,
        *,
        collection: str = COLLECTION_NAME,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding = embedding
        self.collection = collection
        self.client = QdrantClient(path=str(self.path))

    def rebuild(self, chunks: Iterable[LegalChunk], batch_size: int = 32) -> int:
        chunk_list = list(chunks)
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=self.embedding.dimension,
                distance=models.Distance.COSINE,
            ),
        )
        for start in range(0, len(chunk_list), batch_size):
            batch = chunk_list[start : start + batch_size]
            vectors = self.embedding.encode([chunk.text for chunk in batch])
            self.client.upsert(
                collection_name=self.collection,
                points=[
                    models.PointStruct(
                        id=point_id(chunk.source_id),
                        vector=vector,
                        payload=chunk.qdrant_payload(),
                    )
                    for chunk, vector in zip(batch, vectors, strict=True)
                ],
                wait=True,
            )
        return len(chunk_list)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        jurisdiction: str | None = None,
        status: str = "effective",
        document_types: set[str] | None = None,
        effective_as_of: date | None = None,
    ) -> list[tuple[str, float]]:
        must: list[models.Condition] = [
            models.FieldCondition(
                key="status", match=models.MatchValue(value=status)
            )
        ]
        if jurisdiction:
            must.append(
                models.FieldCondition(
                    key="jurisdiction", match=models.MatchValue(value=jurisdiction)
                )
            )
        if document_types:
            must.append(
                models.FieldCondition(
                    key="document_type",
                    match=models.MatchAny(any=sorted(document_types)),
                )
            )
        if effective_as_of:
            cutoff = datetime.combine(
                effective_as_of, time.max, tzinfo=timezone.utc
            )
            must.append(
                models.FieldCondition(
                    key="effective_date",
                    range=models.DatetimeRange(lte=cutoff),
                )
            )
        response = self.client.query_points(
            collection_name=self.collection,
            query=self.embedding.encode([query])[0],
            query_filter=models.Filter(must=must),
            limit=limit,
            with_payload=True,
        )
        return [
            (str(point.payload["source_id"]), float(point.score))
            for point in response.points
        ]

    def count(self) -> int:
        return int(
            self.client.count(
                collection_name=self.collection, exact=True
            ).count
        )

    def close(self) -> None:
        self.client.close()
