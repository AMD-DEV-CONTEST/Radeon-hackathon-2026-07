"""
Enterprise RAG ingestion pipeline (Phase 9).

Takes raw runbook/postmortem documents (arbitrary length), chunks them into
retrieval-sized windows, embeds each chunk locally, and writes them into
MemoryRecord via MemoryService. This is the pipeline the "Runbook Retriever"
agent's search tool reads from.

Chunking strategy: fixed-size sliding window with overlap, which is simple,
fast, and — crucially for an incident-response runbook — preserves procedural
step ordering better than semantic/paragraph-based chunking would.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.service import MemoryService

CHUNK_SIZE_CHARS = 1500
CHUNK_OVERLAP_CHARS = 200


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


class RagIngestionService:
    def __init__(self, memory_service: MemoryService | None = None) -> None:
        self.memory_service = memory_service or MemoryService()

    async def ingest_document(
        self, db: AsyncSession, *, title: str, raw_text: str, source_metadata: dict | None = None
    ) -> int:
        chunks = chunk_text(raw_text)
        for i, chunk in enumerate(chunks):
            await self.memory_service.ingest_runbook(
                db,
                title=f"{title} (chunk {i + 1}/{len(chunks)})",
                content=chunk,
                metadata={**(source_metadata or {}), "chunk_index": i, "total_chunks": len(chunks)},
            )
        return len(chunks)
