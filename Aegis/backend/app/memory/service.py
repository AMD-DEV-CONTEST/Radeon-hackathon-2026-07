"""
MemoryService — the single facade agents use for all memory operations.
Composes embeddings + vector search + episodic lookup + a write path that
runs after every incident resolves, so the system's memory genuinely grows
with each incident handled (the "learns from previous executions" requirement).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import Incident
from app.db.models.memory import MemoryKind, MemoryRecord
from app.memory.embeddings import EmbeddingService
from app.memory.episodic import EpisodicMemory
from app.memory.vector_store import VectorStore


class MemoryService:
    def __init__(self) -> None:
        self.embeddings = EmbeddingService()
        self.vector_store = VectorStore()
        self.episodic = EpisodicMemory()

    async def find_similar_precedent(
        self, db: AsyncSession, *, query_text: str, top_k: int = 5
    ) -> list[tuple[MemoryRecord, float]]:
        query_embedding = await self.embeddings.embed_text(query_text)
        return await self.vector_store.similarity_search(db, query_embedding, top_k=top_k)

    async def record_resolved_incident(self, db: AsyncSession, incident: Incident) -> MemoryRecord:
        """Called once an incident reaches RESOLVED — writes its postmortem
        summary into long-term memory so future investigations can retrieve it."""
        summary_text = (
            f"Incident: {incident.title}\n"
            f"Severity: {incident.severity.value}\n"
            f"Root cause: {incident.root_cause_summary or 'not recorded'}\n"
            f"Description: {incident.description}"
        )
        embedding = await self.embeddings.embed_text(summary_text)
        return await self.vector_store.upsert(
            db,
            kind=MemoryKind.INCIDENT_POSTMORTEM,
            title=incident.title,
            content=summary_text,
            embedding=embedding,
            metadata={"incident_id": str(incident.id), "severity": incident.severity.value},
        )

    async def ingest_runbook(
        self, db: AsyncSession, *, title: str, content: str, metadata: dict | None = None
    ) -> MemoryRecord:
        """Used by the RAG ingestion pipeline (Phase 9) when an operator uploads
        a runbook document."""
        embedding = await self.embeddings.embed_text(content)
        return await self.vector_store.upsert(
            db, kind=MemoryKind.RUNBOOK, title=title, content=content, embedding=embedding, metadata=metadata or {}
        )
