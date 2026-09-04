from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskTable(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    requester_id: Mapped[str] = mapped_column(String(200), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_storage_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RevisionTable(Base):
    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("task_id", "revision_number"),)

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    requester_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_storage_id: Mapped[str | None] = mapped_column(String(200))
    output_sha256: Mapped[str | None] = mapped_column(String(64))
    decision_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RevisionStageTable(Base):
    __tablename__ = "revision_stages"
    __table_args__ = (UniqueConstraint("revision_id", "stage_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactTable(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("namespace", "storage_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), index=True
    )
    namespace: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_id: Mapped[str] = mapped_column(String(200), nullable=False)


class ContextTable(Base):
    __tablename__ = "contexts"

    revision_id: Mapped[str] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), primary_key=True
    )
    recipient: Mapped[str] = mapped_column(String(80), nullable=False)
    organization: Mapped[str] = mapped_column(String(240), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String(240), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(80), nullable=False)
    classification: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class RegionTable(Base):
    __tablename__ = "regions"
    __table_args__ = (UniqueConstraint("revision_id", "region_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    region_id: Mapped[str] = mapped_column(String(240), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str] = mapped_column(String(500), nullable=False)
    region_order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(240))


class DecisionTable(Base):
    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("revision_id", "region_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    region_id: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(40), nullable=False)
    transform: Mapped[str | None] = mapped_column(String(120))


class ApprovalTable(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    requester_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason_code: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEventTable(Base):
    __tablename__ = "audit_events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(200), index=True)
    revision_id: Mapped[str | None] = mapped_column(String(200), index=True)
    policy_sha256: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class CopilotCheckpointTable(Base):
    __tablename__ = "copilot_checkpoints"
    __table_args__ = (UniqueConstraint("task_id", "thread_id", "checkpoint_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[str | None] = mapped_column(String(200))
    thread_id: Mapped[str] = mapped_column(String(200), nullable=False)
    checkpoint_order: Mapped[int] = mapped_column(Integer, nullable=False)
    safe_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PseudonymMappingTable(Base):
    __tablename__ = "pseudonym_mappings"
    __table_args__ = (
        UniqueConstraint("task_id", "category", "value_hmac"),
        UniqueConstraint("task_id", "alias"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    value_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    first_seen_order: Mapped[int] = mapped_column(Integer, nullable=False)


class DeletionTombstoneTable(Base):
    __tablename__ = "deletion_tombstones"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    deletion_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
