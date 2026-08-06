"""Durable projections used by the PostgreSQL DAG scheduler.

The workflow, operation, and attempt facts remain owned by ``creative_hub.db``.
These tables are deliberately projections: they can be rebuilt from workflow
definitions and attempt events, while leases and admission reservations make
the rebuild-safe scheduler state durable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from creative_hub.models import ORCHESTRATION_SCHEMA, OrchestrationBase

# Register the referenced tables before SQLAlchemy resolves composite FKs.
from creative_hub.db import models as _atomic_models  # noqa: F401,E402


RESOURCE_POOLS = frozenset(
    {"cpu", "local_gpu", "cloud_image", "cloud_video", "llm"}
)
PRIORITY_CLASSES = frozenset({"batch", "interactive", "urgent", "system"})


class WorkflowRunEdgeRecord(OrchestrationBase):
    __tablename__ = "workflow_run_edges"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "upstream_operation_run_id",
            "downstream_operation_run_id",
            name="uq_orch_workflow_edges_pair",
        ),
        CheckConstraint(
            "upstream_operation_run_id <> downstream_operation_run_id",
            name="ck_orch_workflow_edges_not_self",
        ),
        CheckConstraint(
            "required_status IN ('SUCCEEDED', 'TERMINAL')",
            name="ck_orch_workflow_edges_required",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_workflow_edges_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["upstream_operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_runs.id",
                f"{ORCHESTRATION_SCHEMA}.operation_runs.project_id",
            ],
            name="fk_orch_workflow_edges_upstream",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["downstream_operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_runs.id",
                f"{ORCHESTRATION_SCHEMA}.operation_runs.project_id",
            ],
            name="fk_orch_workflow_edges_downstream",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_workflow_edges_upstream",
            "upstream_operation_run_id",
            "downstream_operation_run_id",
        ),
        Index(
            "ix_orch_workflow_edges_downstream",
            "downstream_operation_run_id",
            "upstream_operation_run_id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    upstream_operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    downstream_operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    required_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="SUCCEEDED", server_default="SUCCEEDED"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperationDependencyStateRecord(OrchestrationBase):
    __tablename__ = "operation_dependency_states"
    __table_args__ = (
        UniqueConstraint(
            "operation_run_id",
            "workflow_run_id",
            "project_id",
            name="uq_orch_dependency_state_scope",
        ),
        CheckConstraint(
            "status IN ('WAITING', 'READY', 'DISPATCHED', 'PAUSED_HUMAN', "
            "'BLOCKED', 'TERMINAL')",
            name="ck_orch_dependency_state_status",
        ),
        CheckConstraint(
            "dependency_count >= 0 AND satisfied_count >= 0 "
            "AND failed_count >= 0 AND "
            "satisfied_count + failed_count <= dependency_count",
            name="ck_orch_dependency_state_counts",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_dependency_state_version"
        ),
        ForeignKeyConstraint(
            ["operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_runs.id",
                f"{ORCHESTRATION_SCHEMA}.operation_runs.project_id",
            ],
            name="fk_orch_dependency_state_operation",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_dependency_state_workflow_status",
            "workflow_run_id",
            "status",
            "operation_run_id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    dependency_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    satisfied_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DagReadyQueueRecord(OrchestrationBase):
    __tablename__ = "dag_ready_queue"
    __table_args__ = (
        UniqueConstraint(
            "operation_run_id", name="uq_orch_dag_ready_operation"
        ),
        CheckConstraint(
            "resource_pool IN ('cpu', 'local_gpu', 'cloud_image', "
            "'cloud_video', 'llm')",
            name="ck_orch_dag_ready_resource_pool",
        ),
        CheckConstraint(
            "priority_class IN ('batch', 'interactive', 'urgent', 'system')",
            name="ck_orch_dag_ready_priority",
        ),
        CheckConstraint(
            "state IN ('WAITING', 'READY', 'LEASED', 'PAUSED_HUMAN', "
            "'BUDGET_BLOCKED', 'DONE', 'CANCELLED')",
            name="ck_orch_dag_ready_state",
        ),
        CheckConstraint(
            "estimated_cost_micros IS NOT NULL "
            "AND estimated_cost_micros >= 0",
            name="ck_orch_dag_ready_estimated_cost",
        ),
        CheckConstraint(
            "lease_generation >= 0 AND dispatch_count >= 0",
            name="ck_orch_dag_ready_counters",
        ),
        CheckConstraint(
            "(state = 'LEASED' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND attempt_id IS NOT NULL) "
            "OR (state <> 'LEASED' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_orch_dag_ready_lease_shape",
        ),
        ForeignKeyConstraint(
            ["operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_runs.id",
                f"{ORCHESTRATION_SCHEMA}.operation_runs.project_id",
            ],
            name="fk_orch_dag_ready_operation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_dag_ready_attempt",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_orch_dag_ready_claim",
            "state",
            "resource_pool",
            "not_before",
            "enqueued_at",
        ),
        Index(
            "ix_orch_dag_ready_workflow_state",
            "workflow_run_id",
            "state",
        ),
        Index(
            "ix_orch_dag_ready_expired_lease",
            "lease_expires_at",
            "id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    resource_pool: Mapped[str] = mapped_column(String(24), nullable=False)
    priority_class: Mapped[str] = mapped_column(String(16), nullable=False)
    priority_value: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_micros: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    not_before: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    dispatch_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    blocked_reason: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ResourcePoolQuotaRecord(OrchestrationBase):
    __tablename__ = "resource_pool_quotas"
    __table_args__ = (
        CheckConstraint(
            "resource_pool IN ('cpu', 'local_gpu', 'cloud_image', "
            "'cloud_video', 'llm')",
            name="ck_orch_resource_quota_pool",
        ),
        CheckConstraint(
            "max_concurrent > 0 AND in_use >= 0 "
            "AND in_use <= max_concurrent",
            name="ck_orch_resource_quota_capacity",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_resource_quota_version"
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    resource_pool: Mapped[str] = mapped_column(
        String(24), primary_key=True
    )
    max_concurrent: Mapped[int] = mapped_column(Integer, nullable=False)
    in_use: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SchedulerFairnessCounterRecord(OrchestrationBase):
    __tablename__ = "scheduler_fairness_counters"
    __table_args__ = (
        UniqueConstraint(
            "scope_kind",
            "scope_key",
            "resource_pool",
            name="uq_orch_scheduler_fairness_dimension",
        ),
        CheckConstraint(
            "scope_kind IN ('RESOURCE_POOL', 'PROJECT', 'WORKFLOW')",
            name="ck_orch_scheduler_fairness_scope",
        ),
        CheckConstraint(
            "resource_pool IN ('cpu', 'local_gpu', 'cloud_image', "
            "'cloud_video', 'llm')",
            name="ck_orch_scheduler_fairness_pool",
        ),
        CheckConstraint(
            "dispatch_count >= 0",
            name="ck_orch_scheduler_fairness_dispatches",
        ),
        Index(
            "ix_orch_scheduler_fairness_order",
            "resource_pool",
            "scope_kind",
            "dispatch_count",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_pool: Mapped[str] = mapped_column(String(24), nullable=False)
    dispatch_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    last_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class DagAdmissionReservationRecord(OrchestrationBase):
    __tablename__ = "dag_admission_reservations"
    __table_args__ = (
        UniqueConstraint(
            "queue_entry_id",
            "lease_generation",
            "budget_account_id",
            name="uq_orch_dag_admission_account",
        ),
        CheckConstraint(
            "status IN ('RESERVED', 'RELEASED', 'SETTLED')",
            name="ck_orch_dag_admission_status",
        ),
        CheckConstraint(
            "amount_micros > 0",
            name="ck_orch_dag_admission_amount",
        ),
        ForeignKeyConstraint(
            ["queue_entry_id"],
            [f"{ORCHESTRATION_SCHEMA}.dag_ready_queue.id"],
            name="fk_orch_dag_admission_queue",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["budget_account_id"],
            [f"{ORCHESTRATION_SCHEMA}.budget_accounts.id"],
            name="fk_orch_dag_admission_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["budget_reservation_id", "budget_account_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.budget_reservations.id",
                f"{ORCHESTRATION_SCHEMA}.budget_reservations.account_id",
                f"{ORCHESTRATION_SCHEMA}.budget_reservations.project_id",
            ],
            name="fk_orch_dag_admission_reservation",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_dag_admission_attempt",
            "attempt_id",
            "status",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    queue_entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    budget_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    budget_reservation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="RESERVED", server_default="RESERVED"
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


class DagSchedulerEventRecord(OrchestrationBase):
    __tablename__ = "dag_scheduler_events"
    __table_args__ = (
        UniqueConstraint(
            "queue_entry_id",
            "sequence",
            name="uq_orch_dag_scheduler_event_sequence",
        ),
        CheckConstraint(
            "sequence > 0", name="ck_orch_dag_scheduler_event_sequence"
        ),
        CheckConstraint(
            "length(data_digest) = 64",
            name="ck_orch_dag_scheduler_event_digest",
        ),
        ForeignKeyConstraint(
            ["queue_entry_id"],
            [f"{ORCHESTRATION_SCHEMA}.dag_ready_queue.id"],
            name="fk_orch_dag_scheduler_event_queue",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_dag_scheduler_event_workflow",
            "workflow_run_id",
            "occurred_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    queue_entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    data_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "DagAdmissionReservationRecord",
    "DagReadyQueueRecord",
    "DagSchedulerEventRecord",
    "OperationDependencyStateRecord",
    "PRIORITY_CLASSES",
    "RESOURCE_POOLS",
    "ResourcePoolQuotaRecord",
    "SchedulerFairnessCounterRecord",
    "WorkflowRunEdgeRecord",
]
