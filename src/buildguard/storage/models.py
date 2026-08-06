"""Relational storage models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from buildguard.utils.time import utc_now


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    __abstract__ = True


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC and restore timezone awareness when SQLite drops offsets."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        normalized = value.astimezone(UTC)
        return normalized.replace(tzinfo=None) if dialect.name == "sqlite" else normalized

    def process_result_value(self, value: datetime | None, _: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Timestamped:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class SessionModel(Timestamped, Base):
    __tablename__ = "sessions"
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MessageModel(Timestamped, Base):
    __tablename__ = "messages"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TaskModel(Timestamped, Base):
    __tablename__ = "tasks"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    plan_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ToolCallModel(Timestamped, Base):
    __tablename__ = "tool_calls"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    success: Mapped[bool | None] = mapped_column(Boolean)
    duration_ms: Mapped[float | None] = mapped_column(Float)


class InspectionResultModel(Timestamped, Base):
    __tablename__ = "inspection_results"
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), index=True)
    source_path: Mapped[str] = mapped_column(Text)
    detections_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    risks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model_name: Mapped[str] = mapped_column(String(256), index=True)
    processing_ms: Mapped[float] = mapped_column(Float)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)


class UploadedEvidenceModel(Timestamped, Base):
    __tablename__ = "uploaded_evidence"
    evidence_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    storage_path: Mapped[str] = mapped_column(Text, unique=True)
    original_name: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column()
    width: Mapped[int] = mapped_column()
    height: Mapped[int] = mapped_column()


class RiskEventModel(Timestamped, Base):
    __tablename__ = "risk_events"
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    __table_args__ = (Index("ix_risk_event_severity_created", "severity", "created_at"),)


class ReportModel(Timestamped, Base):
    __tablename__ = "reports"
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    report_type: Mapped[str] = mapped_column(String(128), index=True)
    output_path: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)


class RagDocumentModel(Timestamped, Base):
    __tablename__ = "rag_documents"
    source: Mapped[str] = mapped_column(Text, unique=True)
    checksum: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RagChunkModel(Timestamped, Base):
    __tablename__ = "rag_chunks"
    document_id: Mapped[str] = mapped_column(ForeignKey("rag_documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(index=True)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (Index("ix_rag_chunk_document_position", "document_id", "chunk_index"),)


class PerformanceLogModel(Timestamped, Base):
    __tablename__ = "performance_logs"
    operation: Mapped[str] = mapped_column(String(256), index=True)
    duration_ms: Mapped[float] = mapped_column(Float)
    success: Mapped[bool] = mapped_column(Boolean, index=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SecurityAuditLogModel(Timestamped, Base):
    __tablename__ = "security_audit_logs"
    actor: Mapped[str] = mapped_column(String(256), index=True)
    action: Mapped[str] = mapped_column(String(256), index=True)
    resource: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class VerifiedFactModel(Timestamped, Base):
    __tablename__ = "verified_facts"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    subject: Mapped[str] = mapped_column(String(512), index=True)
    predicate: Mapped[str] = mapped_column(String(256), index=True)
    object_text: Mapped[str] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(128), index=True)
    source_id: Mapped[str] = mapped_column(String(512), index=True)
    checksum: Mapped[str | None] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class RemediationRecordModel(Timestamped, Base):
    __tablename__ = "remediation_records"
    event_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(256), index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class CameraStatusModel(Timestamped, Base):
    __tablename__ = "camera_statuses"
    camera_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    status_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RealtimeEventModel(Timestamped, Base):
    __tablename__ = "realtime_events"
    camera_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    track_id: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True), index=True)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (
        Index(
            "ix_realtime_event_camera_type_status",
            "camera_id",
            "event_type",
            "status",
        ),
    )
