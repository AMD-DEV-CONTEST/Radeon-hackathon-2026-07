"""Evidence — a discrete, citable fact gathered by an investigating agent."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Text, ForeignKey, Enum, Float, func
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import PortableJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class EvidenceType(str, enum.Enum):
    LOG = "log"
    METRIC = "metric"
    DEPLOY_EVENT = "deploy_event"
    RUNBOOK = "runbook"
    PAST_INCIDENT = "past_incident"


class Evidence(Base):
    """
    A single piece of evidence an agent surfaced, kept as a first-class row (not
    buried in free text) so the Synthesizer agent's final report can cite specific
    evidence ids — this is the mechanism behind explainability, not decoration.
    """
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType, name="evidence_type"), nullable=False)
    source_agent: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[dict] = mapped_column(PortableJSON, default=dict)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    incident: Mapped["Incident"] = relationship(back_populates="evidence")
