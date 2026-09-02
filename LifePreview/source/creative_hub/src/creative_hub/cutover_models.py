"""Durable records for the one-way unified-runtime cutover.

The cutover authority deliberately lives in the orchestration database.  The
legacy Factory files and database exports are evidence sources only; none of
their rows become current workflow or canon rows as a side effect of import.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from creative_hub.models import ORCHESTRATION_SCHEMA, OrchestrationBase


class CutoverEpochRecord(OrchestrationBase):
    __tablename__ = "cutover_epochs"
    __table_args__ = (
        UniqueConstraint(
            "cutover_epoch",
            name="uq_orch_cutover_epoch",
        ),
        CheckConstraint(
            "phase IN ('PLANNED', 'FROZEN', 'IMPORTING', 'RECONCILING', "
            "'DRAINING', 'READY', 'ACTIVATED', 'FORWARD_FIX', "
            "'ROLLED_BACK', 'RETIRED')",
            name="ck_orch_cutover_phase",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_orch_cutover_state_version",
        ),
        CheckConstraint(
            "source_snapshot_digest IS NULL "
            "OR length(source_snapshot_digest) = 64",
            name="ck_orch_cutover_snapshot_digest",
        ),
        CheckConstraint(
            "first_unified_write_at IS NULL OR activated_at IS NOT NULL",
            name="ck_orch_cutover_first_write_after_activation",
        ),
        CheckConstraint(
            "phase NOT IN ('ACTIVATED', 'FORWARD_FIX', 'RETIRED') "
            "OR (legacy_admission_frozen AND legacy_write_fence)",
            name="ck_orch_cutover_active_fences",
        ),
        Index(
            "ix_orch_cutover_phase_updated",
            "phase",
            "updated_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    cutover_epoch: Mapped[str] = mapped_column(String(160), nullable=False)
    phase: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PLANNED", server_default="PLANNED"
    )
    state_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    legacy_admission_frozen: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    legacy_write_fence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    source_snapshot_digest: Mapped[str | None] = mapped_column(String(64))
    created_by_actor: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    first_unified_write_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class CutoverImportBatchRecord(OrchestrationBase):
    __tablename__ = "cutover_import_batches"
    __table_args__ = (
        UniqueConstraint(
            "cutover_id",
            "source_kind",
            "source_identity",
            name="uq_orch_cutover_import_source",
        ),
        CheckConstraint(
            "source_kind IN ('FACTORY_V3_FILE', 'LEGACY_DB_SNAPSHOT')",
            name="ck_orch_cutover_import_source_kind",
        ),
        CheckConstraint(
            "length(source_digest) = 64",
            name="ck_orch_cutover_import_digest",
        ),
        ForeignKeyConstraint(
            ["cutover_id"],
            [f"{ORCHESTRATION_SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_import_epoch",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_cutover_import_epoch_kind",
            "cutover_id",
            "source_kind",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    cutover_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(500), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    imported_by_actor: Mapped[str] = mapped_column(String(160), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CutoverImportedFactRecord(OrchestrationBase):
    __tablename__ = "cutover_imported_facts"
    __table_args__ = (
        UniqueConstraint(
            "cutover_id",
            "source_kind",
            "source_identity",
            name="uq_orch_cutover_imported_fact",
        ),
        CheckConstraint(
            "source_kind IN ('FACTORY_V3_FILE', 'LEGACY_DB_SNAPSHOT')",
            name="ck_orch_cutover_fact_source",
        ),
        CheckConstraint(
            "proof_status IN ('PROVEN', 'UNKNOWN')",
            name="ck_orch_cutover_fact_proof",
        ),
        CheckConstraint(
            "length(fact_digest) = 64",
            name="ck_orch_cutover_fact_digest",
        ),
        CheckConstraint(
            "NOT canon_eligible",
            name="ck_orch_cutover_fact_never_auto_canon",
        ),
        ForeignKeyConstraint(
            ["cutover_id"],
            [f"{ORCHESTRATION_SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_fact_epoch",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_cutover_fact_epoch_kind",
            "cutover_id",
            "fact_kind",
            "proof_status",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    cutover_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(500), nullable=False)
    fact_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    proof_status: Mapped[str] = mapped_column(String(16), nullable=False)
    canon_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CutoverInFlightRecord(OrchestrationBase):
    __tablename__ = "cutover_inflight_items"
    __table_args__ = (
        UniqueConstraint(
            "cutover_id",
            "item_kind",
            "source_identity",
            name="uq_orch_cutover_inflight_identity",
        ),
        CheckConstraint(
            "item_kind IN ('RUN', 'PROVIDER_TASK', 'LEASE', 'SELECTION', "
            "'REVIEW')",
            name="ck_orch_cutover_inflight_kind",
        ),
        CheckConstraint(
            "classification IN ('ADOPT_REQUIRED', 'ADOPTED', "
            "'LEGACY_DRAIN', 'TERMINAL', 'RUNNING', 'HUNG_MANUAL', "
            "'COMPLETED_PENDING_COLLECTION', 'COLLECTED', 'FAILED', "
            "'OUTCOME_UNKNOWN', 'RECHECK_REQUIRED', 'EXPIRED', "
            "'HUMAN_CONFIRM_REQUIRED', 'ADOPTED_READ_ONLY', 'RESOLVED', "
            "'UNKNOWN')",
            name="ck_orch_cutover_inflight_classification",
        ),
        CheckConstraint(
            "evidence_digest IS NULL OR length(evidence_digest) = 64",
            name="ck_orch_cutover_inflight_digest",
        ),
        CheckConstraint(
            "item_kind <> 'PROVIDER_TASK' OR must_not_resubmit",
            name="ck_orch_cutover_provider_no_resubmit",
        ),
        ForeignKeyConstraint(
            ["cutover_id"],
            [f"{ORCHESTRATION_SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_inflight_epoch",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_cutover_inflight_epoch_classification",
            "cutover_id",
            "classification",
            "item_kind",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    cutover_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    item_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(500), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_digest: Mapped[str | None] = mapped_column(String(64))
    must_not_resubmit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CutoverReconciliationRecord(OrchestrationBase):
    __tablename__ = "cutover_reconciliations"
    __table_args__ = (
        UniqueConstraint(
            "cutover_id",
            "side",
            name="uq_orch_cutover_reconciliation_side",
        ),
        CheckConstraint(
            "side IN ('LEGACY', 'UNIFIED')",
            name="ck_orch_cutover_reconciliation_side",
        ),
        CheckConstraint(
            "running_count >= 0 AND cost_micros >= 0",
            name="ck_orch_cutover_reconciliation_counts",
        ),
        CheckConstraint(
            "length(snapshot_digest) = 64",
            name="ck_orch_cutover_reconciliation_digest",
        ),
        ForeignKeyConstraint(
            ["cutover_id"],
            [f"{ORCHESTRATION_SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_reconciliation_epoch",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    cutover_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    running_count: Mapped[int] = mapped_column(Integer, nullable=False)
    terminal_counts: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    artifact_digests: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False
    )
    selections: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    open_review_tasks: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    snapshot_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CutoverEventRecord(OrchestrationBase):
    __tablename__ = "cutover_events"
    __table_args__ = (
        UniqueConstraint(
            "cutover_id",
            "sequence",
            name="uq_orch_cutover_event_sequence",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_orch_cutover_event_sequence",
        ),
        CheckConstraint(
            "length(payload_digest) = 64",
            name="ck_orch_cutover_event_digest",
        ),
        ForeignKeyConstraint(
            ["cutover_id"],
            [f"{ORCHESTRATION_SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_event_epoch",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_cutover_event_epoch_sequence",
            "cutover_id",
            "sequence",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    cutover_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
