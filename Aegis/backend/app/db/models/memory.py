"""
MemoryRecord — long-term, cross-incident memory backed by pgvector.

Every resolved incident's summary is embedded and stored here. The Runbook
Retriever agent queries this table by cosine similarity so that "have we seen
something like this before" is answered from real precedent, not guesswork —
this is the mechanism that makes Aegis improve over time.
"""
import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, DateTime, Text, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import PortableJSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

EMBEDDING_DIM = 1024  # matches the local embedding model configured in Phase 9


class MemoryKind(str, enum.Enum):
    INCIDENT_POSTMORTEM = "incident_postmortem"
    RUNBOOK = "runbook"
    KNOWLEDGE_SNIPPET = "knowledge_snippet"


class MemoryRecord(Base):
    __tablename__ = "memory_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[MemoryKind] = mapped_column(Enum(MemoryKind, name="memory_kind"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    memory_metadata: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
