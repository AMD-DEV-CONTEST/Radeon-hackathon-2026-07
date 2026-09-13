"""Incident model — the central entity Aegis investigates."""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Text, ForeignKey, Enum, Float, func
from sqlalchemy.dialects.postgresql import UUID
from app.db.types import PortableJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class IncidentSeverity(str, enum.Enum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"
    SEV4 = "sev4"


class IncidentStatus(str, enum.Enum):
    TRIGGERED = "triggered"
    INVESTIGATING = "investigating"
    ROOT_CAUSE_IDENTIFIED = "root_cause_identified"
    REMEDIATION_PENDING_APPROVAL = "remediation_pending_approval"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    FAILED = "failed"


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "prometheus_alert", "manual"
    severity: Mapped[IncidentSeverity] = mapped_column(Enum(IncidentSeverity, name="incident_severity"))
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status"),
        default=IncidentStatus.TRIGGERED,
        nullable=False,
    )
    raw_payload: Mapped[dict] = mapped_column(PortableJSON, default=dict)  # original alert payload
    root_cause_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_cause_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="incident", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Incident {self.id} [{self.status.value}] {self.title!r}>"
