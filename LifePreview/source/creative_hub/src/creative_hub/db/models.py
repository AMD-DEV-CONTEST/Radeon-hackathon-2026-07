from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from creative_hub.models import ORCHESTRATION_SCHEMA, OrchestrationBase


SHA256_CHECK = "length({column}) = 64"
GENERAL_VIDEO_TEMPLATE_ID = UUID("f7dfaea5-bdbb-5479-af6a-30c7b2de0028")
GENERAL_VIDEO_TEMPLATE_DIGEST = (
    "fbfb6425135fbab09bc52ed3a6c34745299d5d825d407609a8556a55aac879a0"
)
SHORT_DRAMA_TEMPLATE_ID = UUID("88b80429-b4f5-5011-850b-5e4e6076593c")
SHORT_DRAMA_TEMPLATE_DIGEST = (
    "8f856fdd1d3c12241f942c02843b7585fcae951825fc74082930af0c894673d6"
)
SHORT_DRAMA_FOLDER_ROLES = (
    "source",
    "story_bible",
    "character_bible",
    "world_bible",
    "style_bible",
    "characters",
    "scenes",
    "props",
    "episodes",
    "shots",
    "candidates",
    "quality",
    "deliveries",
)


class ProjectRecord(OrchestrationBase):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("project_key", name="uq_orch_projects_key"),
        UniqueConstraint("id", "project_key", name="uq_orch_projects_id_key"),
        CheckConstraint(
            "length(project_key) BETWEEN 1 AND 100",
            name="ck_orch_projects_key_length",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_orch_projects_status",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="config_digest"),
            name="ck_orch_projects_config_digest",
        ),
        CheckConstraint(
            "length(template_key) BETWEEN 1 AND 120",
            name="ck_orch_projects_template_key_length",
        ),
        CheckConstraint(
            "template_version > 0", name="ck_orch_projects_template_version"
        ),
        ForeignKeyConstraint(
            ["template_key", "template_version"],
            [
                f"{ORCHESTRATION_SCHEMA}.project_templates.template_key",
                f"{ORCHESTRATION_SCHEMA}.project_templates.version",
            ],
            name="fk_orch_projects_template",
            ondelete="RESTRICT",
        ),
        Index("ix_orch_projects_status_created", "status", "created_at"),
        Index(
            "ix_orch_projects_template",
            "template_key",
            "template_version",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    config_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    template_key: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="general_video",
        server_default="general_video",
    )
    template_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
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


class WorkflowDefinitionRecord(OrchestrationBase):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "workflow_key", name="uq_orch_workflow_defs_project_key"
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_workflow_defs_id_project"
        ),
        CheckConstraint(
            "length(workflow_key) BETWEEN 1 AND 160",
            name="ck_orch_workflow_defs_key_length",
        ),
        CheckConstraint(
            "current_revision > 0",
            name="ck_orch_workflow_defs_revision",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_workflow_defs_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["id", "current_revision"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_definition_revisions.workflow_definition_id",
                f"{ORCHESTRATION_SCHEMA}.workflow_definition_revisions.revision",
            ],
            name="fk_orch_workflow_defs_current_revision",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_orch_workflow_defs_project_updated",
            "project_id",
            "updated_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    current_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
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


class WorkflowDefinitionRevisionRecord(OrchestrationBase):
    __tablename__ = "workflow_definition_revisions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_definition_id",
            "revision",
            name="uq_orch_workflow_revisions_number",
        ),
        UniqueConstraint(
            "id",
            "workflow_definition_id",
            "project_id",
            name="uq_orch_workflow_revisions_scope",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_workflow_revisions_command",
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_workflow_revisions_positive"
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="definition_digest"),
            name="ck_orch_workflow_revisions_digest",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_workflow_revisions_command_length",
        ),
        ForeignKeyConstraint(
            ["workflow_definition_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_definitions.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_definitions.project_id",
            ],
            name="fk_orch_workflow_revisions_definition",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_workflow_revisions_definition_created",
            "workflow_definition_id",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workflow_definition_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    schema_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    definition_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowRunRecord(OrchestrationBase):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_workflow_runs_command",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_workflow_runs_id_project"
        ),
        UniqueConstraint(
            "project_id",
            "source_repair_proposal_id",
            name="uq_orch_workflow_runs_source_repair",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'RUNNING', 'WAITING_HUMAN', 'COMPLETED', "
            "'COMPLETED_WITH_WARNINGS', 'BLOCKED', 'FAILED', 'CANCELLED')",
            name="ck_orch_workflow_runs_status",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_workflow_runs_version"
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="input_digest"),
            name="ck_orch_workflow_runs_input_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="policy_digest"),
            name="ck_orch_workflow_runs_policy_digest",
        ),
        CheckConstraint(
            "(parent_workflow_run_id IS NULL AND "
            "source_repair_proposal_id IS NULL) OR "
            "(parent_workflow_run_id IS NOT NULL AND "
            "source_repair_proposal_id IS NOT NULL)",
            name="ck_orch_workflow_runs_repair_lineage_pair",
        ),
        ForeignKeyConstraint(
            ["workflow_definition_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_definitions.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_definitions.project_id",
            ],
            name="fk_orch_workflow_runs_definition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workflow_revision_id",
                "workflow_definition_id",
                "project_id",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_definition_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_definition_revisions.workflow_definition_id",
                f"{ORCHESTRATION_SCHEMA}.workflow_definition_revisions.project_id",
            ],
            name="fk_orch_workflow_runs_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_workflow_runs_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_repair_proposal_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.repair_proposals.id",
                f"{ORCHESTRATION_SCHEMA}.repair_proposals.project_id",
            ],
            name="fk_orch_workflow_runs_source_repair",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_workflow_runs_project_status",
            "project_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_orch_workflow_runs_definition_created",
            "workflow_definition_id",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    workflow_definition_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    workflow_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    parent_workflow_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True)
    )
    source_repair_proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True)
    )
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DRAFT", server_default="DRAFT"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def unit_keys(self) -> tuple[str, ...]:
        """Return the immutable logical-unit projection for a repair run."""

        manifest = self.input_payload.get("repair_manifest")
        if not isinstance(manifest, dict):
            return ()
        unit_keys = manifest.get("unit_keys")
        if not isinstance(unit_keys, list):
            return ()
        return tuple(key for key in unit_keys if isinstance(key, str))


class OperationRunRecord(OrchestrationBase):
    __tablename__ = "operation_runs"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_operation_runs_command",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_operation_runs_id_project"
        ),
        UniqueConstraint(
            "id",
            "workflow_run_id",
            "project_id",
            name="uq_orch_operation_runs_dag_scope",
        ),
        CheckConstraint(
            "status IN ('CREATED', 'QUEUED', 'LEASED', 'RUNNING', "
            "'MATERIALIZING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_orch_operation_runs_status",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_operation_runs_version"
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="operation_input_digest"),
            name="ck_orch_operation_runs_input_digest",
        ),
        CheckConstraint(
            "(accepted_attempt_id IS NULL AND accepted_attempt_number IS NULL) "
            "OR (accepted_attempt_id IS NOT NULL "
            "AND accepted_attempt_number IS NOT NULL)",
            name="ck_orch_operation_runs_accepted_pair",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_operation_runs_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_runs.id",
                f"{ORCHESTRATION_SCHEMA}.operation_runs.project_id",
            ],
            name="fk_orch_operation_runs_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "accepted_attempt_id",
                "id",
                "accepted_attempt_number",
                "project_id",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.attempt_number",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_operation_runs_accepted_attempt",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_orch_operation_runs_workflow_status",
            "workflow_run_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_orch_operation_runs_project_type",
            "project_id",
            "op_type",
            "created_at",
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
    node_key: Mapped[str] = mapped_column(String(200), nullable=False)
    op_type: Mapped[str] = mapped_column(String(160), nullable=False)
    op_version: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    operation_input_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="CREATED", server_default="CREATED"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    accepted_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_attempt_number: Mapped[int | None] = mapped_column(Integer)
    parent_operation_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True)
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


class OperationAttemptRecord(OrchestrationBase):
    __tablename__ = "operation_attempts"
    __table_args__ = (
        UniqueConstraint(
            "operation_run_id",
            "attempt_number",
            name="uq_orch_operation_attempts_number",
        ),
        UniqueConstraint(
            "id",
            "operation_run_id",
            "attempt_number",
            "project_id",
            name="uq_orch_operation_attempts_accept_scope",
        ),
        UniqueConstraint(
            "id",
            "operation_run_id",
            "project_id",
            name="uq_orch_operation_attempts_run_scope",
        ),
        UniqueConstraint(
            "project_id",
            "submission_nonce",
            name="uq_orch_operation_attempts_nonce",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_orch_operation_attempts_number",
        ),
        CheckConstraint(
            "fencing_token >= 0",
            name="ck_orch_operation_attempts_fencing",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="implementation_digest"),
            name="ck_orch_operation_attempts_implementation",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="request_digest"),
            name="ck_orch_operation_attempts_request_digest",
        ),
        ForeignKeyConstraint(
            ["operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_runs.id",
                f"{ORCHESTRATION_SCHEMA}.operation_runs.project_id",
            ],
            name="fk_orch_operation_attempts_run",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_operation_attempts_run_created",
            "operation_run_id",
            "created_at",
        ),
        Index(
            "ix_orch_operation_attempts_provider_task",
            "provider_task_id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(160), nullable=False)
    implementation_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    provider_task_id: Mapped[str | None] = mapped_column(String(255))
    submission_nonce: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperationAttemptStateRecord(OrchestrationBase):
    __tablename__ = "operation_attempt_states"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PREPARED', 'SUBMITTED', 'OUTCOME_UNKNOWN', "
            "'OBSERVED_TERMINAL', 'MATERIALIZING', 'SUCCEEDED', 'FAILED', "
            "'CANCELLED', 'STALE')",
            name="ck_orch_attempt_states_status",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_attempt_states_version"
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_orch_attempt_states_duration",
        ),
        CheckConstraint(
            "cost_micros IS NULL OR cost_micros >= 0",
            name="ck_orch_attempt_states_cost",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_attempt_states_attempt",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_attempt_states_project_status",
            "project_id",
            "status",
            "updated_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PREPARED",
        server_default="PREPARED",
    )
    stage: Mapped[str] = mapped_column(
        String(64), nullable=False, default="PREPARED", server_default="PREPARED"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    provider_state: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    error: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OperationAttemptEventRecord(OrchestrationBase):
    __tablename__ = "operation_attempt_events"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "sequence", name="uq_orch_attempt_events_sequence"
        ),
        UniqueConstraint(
            "attempt_id",
            "state_version",
            name="uq_orch_attempt_events_state_version",
        ),
        CheckConstraint(
            "sequence > 0", name="ck_orch_attempt_events_sequence"
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_attempt_events_version"
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="data_digest"),
            name="ck_orch_attempt_events_digest",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_attempt_events_attempt",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_attempt_events_attempt_sequence",
            "attempt_id",
            "sequence",
        ),
        Index(
            "ix_orch_attempt_events_project_occurred",
            "project_id",
            "occurred_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    data_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProviderInvocationRecord(OrchestrationBase):
    """Attempt-linked authority for one logical external provider task."""

    __tablename__ = "provider_invocations"
    __table_args__ = (
        UniqueConstraint(
            "operation_attempt_id",
            "provider",
            name="uq_orch_provider_invocations_attempt_provider",
        ),
        UniqueConstraint(
            "provider",
            "client_token",
            name="uq_orch_provider_invocations_client_token",
        ),
        # PostgreSQL and SQLite both allow multiple NULL values here. Once a
        # task id is observed, however, it can belong to only one invocation.
        UniqueConstraint(
            "provider",
            "provider_task_id",
            name="uq_orch_provider_invocations_provider_task",
        ),
        UniqueConstraint(
            "id",
            "operation_attempt_id",
            "operation_run_id",
            "project_id",
            name="uq_orch_provider_invocations_attempt_scope",
        ),
        CheckConstraint(
            "phase IN ('PREPARED', 'SUBMITTED', 'OUTCOME_UNKNOWN', "
            "'OBSERVED_TERMINAL', 'MATERIALIZING', 'COMMITTED')",
            name="ck_orch_provider_invocations_phase",
        ),
        CheckConstraint(
            "terminal_outcome IS NULL OR terminal_outcome IN "
            "('SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_orch_provider_invocations_terminal_outcome",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_orch_provider_invocations_version",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="request_digest"),
            name="ck_orch_provider_invocations_request_digest",
        ),
        CheckConstraint(
            "result_digest IS NULL OR length(result_digest) = 64",
            name="ck_orch_provider_invocations_result_digest",
        ),
        CheckConstraint(
            "materialized_digest IS NULL OR length(materialized_digest) = 64",
            name="ck_orch_provider_invocations_materialized_digest",
        ),
        CheckConstraint(
            "cost_micros IS NULL OR cost_micros >= 0",
            name="ck_orch_provider_invocations_cost",
        ),
        CheckConstraint(
            "(human_required = false AND safe_reason_code IS NULL) OR "
            "(human_required = true AND safe_reason_code IS NOT NULL)",
            name="ck_orch_provider_invocations_human_reason",
        ),
        CheckConstraint(
            "(phase NOT IN ('OBSERVED_TERMINAL', 'MATERIALIZING', "
            "'COMMITTED')) OR (terminal_outcome IS NOT NULL AND "
            "result_digest IS NOT NULL AND terminal_observed_at IS NOT NULL)",
            name="ck_orch_provider_invocations_terminal_data",
        ),
        CheckConstraint(
            "(phase <> 'COMMITTED') OR "
            "(terminal_outcome = 'SUCCEEDED' AND committed_at IS NOT NULL "
            "AND materialized_digest IS NOT NULL)",
            name="ck_orch_provider_invocations_committed",
        ),
        ForeignKeyConstraint(
            ["operation_attempt_id", "operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_provider_invocations_attempt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reservation_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.budget_reservations.id",
                f"{ORCHESTRATION_SCHEMA}.budget_reservations.project_id",
            ],
            name="fk_orch_provider_invocations_reservation",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_provider_invocations_project_phase",
            "project_id",
            "phase",
            "updated_at",
        ),
        Index(
            "ix_orch_provider_invocations_reconcile",
            "phase",
            "human_required",
            "updated_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    client_token: Mapped[str] = mapped_column(String(255), nullable=False)
    submission_nonce: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    supports_idempotent_submit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    supports_query_by_client_token: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    supports_query_by_task_id: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    phase: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PREPARED", server_default="PREPARED"
    )
    provider_task_id: Mapped[str | None] = mapped_column(String(255))
    terminal_outcome: Mapped[str | None] = mapped_column(String(16))
    result_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    result_digest: Mapped[str | None] = mapped_column(String(64))
    materialized_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    materialized_digest: Mapped[str | None] = mapped_column(String(64))
    cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    reservation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    human_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    safe_reason_code: Mapped[str | None] = mapped_column(String(100))
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    submit_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    materializing_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProviderInvocationGrantRecord(OrchestrationBase):
    """One-shot authorization for a provider side effect."""

    __tablename__ = "provider_invocation_grants"
    __table_args__ = (
        CheckConstraint(
            "action IN ('SUBMIT', 'RECONCILE', 'MATERIALIZE')",
            name="ck_orch_provider_grants_action",
        ),
        CheckConstraint(
            "length(granted_by_actor) BETWEEN 1 AND 200",
            name="ck_orch_provider_grants_actor",
        ),
        ForeignKeyConstraint(
            [
                "invocation_id",
                "operation_attempt_id",
                "operation_run_id",
                "project_id",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.provider_invocations.id",
                f"{ORCHESTRATION_SCHEMA}.provider_invocations.operation_attempt_id",
                f"{ORCHESTRATION_SCHEMA}.provider_invocations.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.provider_invocations.project_id",
            ],
            name="fk_orch_provider_grants_invocation",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_provider_grants_invocation_action",
            "invocation_id",
            "action",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    invocation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by_actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProviderCallbackReceiptRecord(OrchestrationBase):
    """Immutable callback receipt providing durable callback idempotency."""

    __tablename__ = "provider_callback_receipts"
    __table_args__ = (
        UniqueConstraint(
            "invocation_id",
            "callback_id",
            name="uq_orch_provider_callbacks_id",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="payload_digest"),
            name="ck_orch_provider_callbacks_digest",
        ),
        ForeignKeyConstraint(
            [
                "invocation_id",
                "operation_attempt_id",
                "operation_run_id",
                "project_id",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.provider_invocations.id",
                f"{ORCHESTRATION_SCHEMA}.provider_invocations.operation_attempt_id",
                f"{ORCHESTRATION_SCHEMA}.provider_invocations.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.provider_invocations.project_id",
            ],
            name="fk_orch_provider_callbacks_invocation",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_provider_callbacks_invocation_received",
            "invocation_id",
            "received_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    invocation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    callback_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BudgetAccountRecord(OrchestrationBase):
    __tablename__ = "budget_accounts"
    __table_args__ = (
        CheckConstraint(
            "length(account_key) BETWEEN 1 AND 100",
            name="ck_orch_budget_accounts_key_length",
        ),
        CheckConstraint(
            "length(currency) = 3",
            name="ck_orch_budget_accounts_currency",
        ),
        CheckConstraint(
            "limit_micros >= 0 AND reserved_micros >= 0 "
            "AND settled_micros >= 0",
            name="ck_orch_budget_accounts_nonnegative",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_budget_accounts_version"
        ),
        CheckConstraint(
            "(scope_kind = 'GLOBAL' AND project_id IS NULL "
            "AND workflow_run_id IS NULL) OR "
            "(scope_kind = 'PROJECT' AND project_id IS NOT NULL "
            "AND workflow_run_id IS NULL) OR "
            "(scope_kind = 'WORKFLOW' AND project_id IS NOT NULL "
            "AND workflow_run_id IS NOT NULL)",
            name="ck_orch_budget_accounts_scope_shape",
        ),
        CheckConstraint(
            "scope_kind IN ('GLOBAL', 'PROJECT', 'WORKFLOW')",
            name="ck_orch_budget_accounts_scope_kind",
        ),
        CheckConstraint(
            "resource_pool IN ('cpu', 'local_gpu', 'cloud_image', "
            "'cloud_video', 'llm')",
            name="ck_orch_budget_accounts_resource_pool",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_budget_accounts_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_budget_accounts_workflow",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_orch_budget_accounts_global_dimension",
            "account_key",
            "resource_pool",
            unique=True,
            postgresql_where=text("scope_kind = 'GLOBAL'"),
        ),
        Index(
            "uq_orch_budget_accounts_project_dimension",
            "project_id",
            "account_key",
            "resource_pool",
            unique=True,
            postgresql_where=text("scope_kind = 'PROJECT'"),
        ),
        Index(
            "uq_orch_budget_accounts_workflow_dimension",
            "workflow_run_id",
            "account_key",
            "resource_pool",
            unique=True,
            postgresql_where=text("scope_kind = 'WORKFLOW'"),
        ),
        Index(
            "ix_orch_budget_accounts_project_updated",
            "project_id",
            "updated_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    scope_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PROJECT",
        server_default="PROJECT",
    )
    workflow_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    resource_pool: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="cpu",
        server_default="cpu",
    )
    account_key: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    limit_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_micros: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    settled_micros: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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


class BudgetReservationRecord(OrchestrationBase):
    __tablename__ = "budget_reservations"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_budget_reservations_command",
        ),
        UniqueConstraint(
            "id",
            "account_id",
            "project_id",
            name="uq_orch_budget_reservations_scope",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_budget_reservations_project_scope",
        ),
        CheckConstraint(
            "status IN ('RESERVED', 'RELEASED', 'SETTLED')",
            name="ck_orch_budget_reservations_status",
        ),
        CheckConstraint(
            "amount_micros > 0", name="ck_orch_budget_reservations_amount"
        ),
        CheckConstraint(
            "settled_micros IS NULL OR settled_micros >= 0",
            name="ck_orch_budget_reservations_settled",
        ),
        CheckConstraint(
            "(status = 'SETTLED' AND settled_micros IS NOT NULL) "
            "OR (status <> 'SETTLED' AND settled_micros IS NULL)",
            name="ck_orch_budget_reservations_terminal",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_budget_reservations_version"
        ),
        CheckConstraint(
            "(operation_attempt_id IS NULL AND operation_run_id IS NULL) "
            "OR (operation_attempt_id IS NOT NULL "
            "AND operation_run_id IS NOT NULL)",
            name="ck_orch_budget_reservations_attempt_pair",
        ),
        ForeignKeyConstraint(
            ["account_id"],
            [f"{ORCHESTRATION_SCHEMA}.budget_accounts.id"],
            name="fk_orch_budget_reservations_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["operation_attempt_id", "operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_budget_reservations_attempt",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_budget_reservations_account_status",
            "account_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_orch_budget_reservations_attempt",
            "operation_attempt_id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    operation_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="RESERVED",
        server_default="RESERVED",
    )
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settled_micros: Mapped[int | None] = mapped_column(BigInteger)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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


class BudgetLedgerEntryRecord(OrchestrationBase):
    __tablename__ = "budget_ledger_entries"
    __table_args__ = (
        UniqueConstraint(
            "reservation_id",
            "sequence",
            name="uq_orch_budget_ledger_sequence",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_budget_ledger_command",
        ),
        CheckConstraint(
            "entry_type IN ('RESERVE', 'RELEASE', 'SETTLE')",
            name="ck_orch_budget_ledger_type",
        ),
        CheckConstraint(
            "sequence > 0", name="ck_orch_budget_ledger_sequence"
        ),
        CheckConstraint(
            "reserved_balance_micros >= 0 AND settled_balance_micros >= 0",
            name="ck_orch_budget_ledger_balances",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="metadata_digest"),
            name="ck_orch_budget_ledger_digest",
        ),
        ForeignKeyConstraint(
            ["account_id"],
            [f"{ORCHESTRATION_SCHEMA}.budget_accounts.id"],
            name="fk_orch_budget_ledger_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reservation_id", "account_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.budget_reservations.id",
                f"{ORCHESTRATION_SCHEMA}.budget_reservations.account_id",
                f"{ORCHESTRATION_SCHEMA}.budget_reservations.project_id",
            ],
            name="fk_orch_budget_ledger_reservation",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_budget_ledger_account_created",
            "account_id",
            "created_at",
        ),
        Index(
            "ix_orch_budget_ledger_project_created",
            "project_id",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reservation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reserved_delta_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settled_delta_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_balance_micros: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    settled_balance_micros: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False
    )
    metadata_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SelectionHeadRecord(OrchestrationBase):
    __tablename__ = "selection_heads"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "selection_key",
            name="uq_orch_selection_heads_key",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_selection_heads_scope"
        ),
        CheckConstraint(
            "status IN ('OPEN', 'SEALED')",
            name="ck_orch_selection_heads_status",
        ),
        CheckConstraint(
            "current_revision IS NULL OR current_revision > 0",
            name="ck_orch_selection_heads_revision",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_selection_heads_version"
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_selection_heads_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["id", "current_revision", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.selection_revisions.selection_head_id",
                f"{ORCHESTRATION_SCHEMA}.selection_revisions.revision",
                f"{ORCHESTRATION_SCHEMA}.selection_revisions.project_id",
            ],
            name="fk_orch_selection_heads_current",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_orch_selection_heads_workflow_status",
            "workflow_run_id",
            "status",
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
    selection_key: Mapped[str] = mapped_column(String(200), nullable=False)
    current_revision: Mapped[int | None] = mapped_column(Integer)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", server_default="OPEN"
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


class ArtifactPublicationClaimRecord(OrchestrationBase):
    """Durable fence and idempotency identity for artifact publication."""

    __tablename__ = "artifact_publication_claims"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "operation_attempt_id",
            "publication_key",
            name="uq_orch_artifact_claim_publication",
        ),
        UniqueConstraint(
            "project_id",
            "staging_token",
            name="uq_orch_artifact_claim_staging_token",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "operation_run_id",
            "operation_attempt_id",
            "attempt_number",
            "fencing_token",
            "publication_key",
            "staging_token",
            name="uq_orch_artifact_claim_identity",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_artifact_claim_scope",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_orch_artifact_claim_attempt_number",
        ),
        CheckConstraint(
            "fencing_token >= 0",
            name="ck_orch_artifact_claim_fencing",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'REGISTERED', 'FINALIZED', 'SUPERSEDED')",
            name="ck_orch_artifact_claim_status",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_orch_artifact_claim_version",
        ),
        ForeignKeyConstraint(
            [
                "operation_attempt_id",
                "operation_run_id",
                "attempt_number",
                "project_id",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.attempt_number",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_artifact_claim_attempt",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_artifact_claim_recovery",
            "status",
            "updated_at",
        ),
        Index(
            "ix_orch_artifact_claim_current_fence",
            "project_id",
            "operation_run_id",
            "fencing_token",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    publication_key: Mapped[str] = mapped_column(String(255), nullable=False)
    staging_token: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", server_default="OPEN"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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


class ArtifactRecordRow(OrchestrationBase):
    """Durable catalog row. Only COMMITTED rows are externally visible."""

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_artifacts_scope"
        ),
        UniqueConstraint(
            "project_id",
            "publication_claim_id",
            name="uq_orch_artifacts_claim",
        ),
        UniqueConstraint(
            "project_id",
            "operation_attempt_id",
            "publication_key",
            name="uq_orch_artifacts_publication",
        ),
        UniqueConstraint(
            "project_id",
            "staging_token",
            name="uq_orch_artifacts_staging_token",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "operation_run_id",
            "operation_attempt_id",
            "content_digest",
            name="uq_orch_artifacts_selection_identity",
        ),
        CheckConstraint(
            "attempt_number > 0", name="ck_orch_artifacts_attempt_number"
        ),
        CheckConstraint(
            "fencing_token >= 0", name="ck_orch_artifacts_fencing"
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="content_digest"),
            name="ck_orch_artifacts_digest",
        ),
        CheckConstraint("byte_size > 0", name="ck_orch_artifacts_byte_size"),
        CheckConstraint(
            "retention_class IN ('ephemeral', 'workflow', 'audit', 'canon')",
            name="ck_orch_artifacts_retention",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'COMMITTED', 'TOMBSTONED')",
            name="ck_orch_artifacts_status",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_artifacts_version"
        ),
        CheckConstraint(
            "(status = 'PENDING' AND storage_uri IS NULL "
            "AND committed_at IS NULL AND tombstoned_at IS NULL) OR "
            "(status = 'COMMITTED' AND storage_uri IS NOT NULL "
            "AND committed_at IS NOT NULL AND tombstoned_at IS NULL) OR "
            "(status = 'TOMBSTONED' AND storage_uri IS NOT NULL "
            "AND committed_at IS NOT NULL AND tombstoned_at IS NOT NULL)",
            name="ck_orch_artifacts_publication_state",
        ),
        ForeignKeyConstraint(
            [
                "publication_claim_id",
                "project_id",
                "operation_run_id",
                "operation_attempt_id",
                "attempt_number",
                "fencing_token",
                "publication_key",
                "staging_token",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.artifact_publication_claims.id",
                f"{ORCHESTRATION_SCHEMA}.artifact_publication_claims.project_id",
                f"{ORCHESTRATION_SCHEMA}.artifact_publication_claims.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.artifact_publication_claims.operation_attempt_id",
                f"{ORCHESTRATION_SCHEMA}.artifact_publication_claims.attempt_number",
                f"{ORCHESTRATION_SCHEMA}.artifact_publication_claims.fencing_token",
                f"{ORCHESTRATION_SCHEMA}.artifact_publication_claims.publication_key",
                f"{ORCHESTRATION_SCHEMA}.artifact_publication_claims.staging_token",
            ],
            name="fk_orch_artifacts_claim",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "operation_attempt_id",
                "operation_run_id",
                "attempt_number",
                "project_id",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.attempt_number",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_artifacts_attempt",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_artifacts_project_status",
            "project_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_orch_artifacts_project_digest",
            "project_id",
            "content_digest",
        ),
        Index(
            "ix_orch_artifacts_gc",
            "status",
            "retain_until",
            "state_version",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    publication_claim_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    publication_key: Mapped[str] = mapped_column(String(255), nullable=False)
    staging_token: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    logical_role: Mapped[str] = mapped_column(String(200), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(16), nullable=False)
    retain_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    staging_locator: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_uri: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    committed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    tombstoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class ArtifactLineageEdgeRecord(OrchestrationBase):
    __tablename__ = "artifact_lineage_edges"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "output_artifact_id",
            "role",
            "ordinal",
            name="uq_orch_artifact_lineage_role_order",
        ),
        CheckConstraint(
            "output_artifact_id <> input_artifact_id",
            name="ck_orch_artifact_lineage_not_self",
        ),
        CheckConstraint(
            "ordinal >= 0", name="ck_orch_artifact_lineage_ordinal"
        ),
        ForeignKeyConstraint(
            ["output_artifact_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_artifact_lineage_output",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["input_artifact_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_artifact_lineage_input",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_artifact_lineage_input",
            "project_id",
            "input_artifact_id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    output_artifact_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    input_artifact_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    role: Mapped[str] = mapped_column(String(200), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ArtifactGCTombstoneRecord(OrchestrationBase):
    __tablename__ = "artifact_gc_tombstones"
    __table_args__ = (
        CheckConstraint(
            SHA256_CHECK.format(column="content_digest"),
            name="ck_orch_artifact_tombstone_digest",
        ),
        CheckConstraint(
            "artifact_state_version > 0",
            name="ck_orch_artifact_tombstone_version",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_artifact_tombstone_artifact",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    artifact_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_state_version: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    tombstoned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ArtifactProtectionVersionRecord(OrchestrationBase):
    __tablename__ = "artifact_protection_versions"
    __table_args__ = (
        CheckConstraint(
            "version >= 0", name="ck_orch_artifact_protection_version"
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_artifact_protection_version_project",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ArtifactProtectionRootRecord(OrchestrationBase):
    __tablename__ = "artifact_protection_roots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "kind",
            "artifact_id",
            name="uq_orch_artifact_protection_root",
        ),
        CheckConstraint(
            "kind IN ('selected', 'canonical', 'open_review_evidence', "
            "'open_qc_evidence', 'replay_manifest')",
            name="ck_orch_artifact_protection_kind",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.artifact_protection_versions.project_id"],
            name="fk_orch_artifact_protection_root_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_artifact_protection_root_artifact",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_artifact_protection_roots_project_kind",
            "project_id",
            "kind",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SelectionRevisionRecord(OrchestrationBase):
    __tablename__ = "selection_revisions"
    __table_args__ = (
        UniqueConstraint(
            "selection_head_id",
            "revision",
            "project_id",
            name="uq_orch_selection_revisions_number",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_selection_revisions_command",
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_selection_revisions_positive"
        ),
        CheckConstraint(
            "decision IN ('SELECTED', 'DEGRADED_ACCEPTED', "
            "'HUMAN_SELECTED', 'REJECTED')",
            name="ck_orch_selection_revisions_decision",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="artifact_digest"),
            name="ck_orch_selection_revisions_artifact",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="payload_digest"),
            name="ck_orch_selection_revisions_payload",
        ),
        ForeignKeyConstraint(
            ["selection_head_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.selection_heads.id",
                f"{ORCHESTRATION_SCHEMA}.selection_heads.project_id",
            ],
            name="fk_orch_selection_revisions_head",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "selected_attempt_id",
                "selected_operation_run_id",
                "project_id",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_selection_revisions_attempt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "artifact_id",
                "project_id",
                "selected_operation_run_id",
                "selected_attempt_id",
                "artifact_digest",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.operation_attempt_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.content_digest",
            ],
            name="fk_orch_selection_revisions_artifact",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_selection_revisions_head_created",
            "selection_head_id",
            "created_at",
        ),
        Index(
            "ix_orch_selection_revisions_attempt",
            "selected_attempt_id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    selection_head_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    selected_operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    selected_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QCPromptRevisionRecord(OrchestrationBase):
    __tablename__ = "qc_prompt_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "prompt_key",
            "stage",
            "revision",
            name="uq_orch_qc_prompt_revision",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "prompt_digest",
            name="uq_orch_qc_prompt_identity",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_prompt_scope",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_qc_prompt_command",
        ),
        CheckConstraint("revision > 0", name="ck_orch_qc_prompt_revision"),
        CheckConstraint(
            "command_idempotency_key IS NULL OR "
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_qc_prompt_command_length",
        ),
        CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_prompt_stage",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="prompt_digest"),
            name="ck_orch_qc_prompt_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_qc_prompt_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_prompt_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.qc_prompt_revisions.project_id",
            ],
            name="fk_orch_qc_prompt_parent",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_qc_prompt_head",
            "project_id",
            "prompt_key",
            "stage",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    prompt_key: Mapped[str] = mapped_column(String(120), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True)
    )
    created_by_actor: Mapped[str] = mapped_column(String(200), nullable=False)
    command_idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QCGatePolicySnapshotRecord(OrchestrationBase):
    __tablename__ = "qc_gate_policy_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            name="uq_orch_qc_gate_policy_stage",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_gate_policy_scope",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "gate_key",
            name="uq_orch_qc_gate_policy_gate_scope",
        ),
        CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_gate_policy_stage",
        ),
        CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_qc_gate_policy_gate_key",
        ),
        CheckConstraint(
            "review_mode IN ('ALL', 'EXCEPTIONS_ONLY', 'OFF')",
            name="ck_orch_qc_gate_policy_review",
        ),
        CheckConstraint(
            "exhaustion_policy IN ('BLOCK', 'DEGRADED_ACCEPT')",
            name="ck_orch_qc_gate_policy_exhaustion",
        ),
        CheckConstraint(
            "machine_qc_required = true",
            name="ck_orch_qc_gate_machine_mandatory",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="policy_digest"),
            name="ck_orch_qc_gate_policy_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="evaluator_bundle_digest"),
            name="ck_orch_qc_gate_evaluator",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_qc_gate_policy_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["prompt_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_prompt_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.qc_prompt_revisions.project_id",
            ],
            name="fk_orch_qc_gate_policy_prompt",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_qc_gate_policy_workflow",
            "project_id",
            "workflow_run_id",
            "gate_key",
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
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    gate_key: Mapped[str] = mapped_column(String(200), nullable=False)
    review_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    exhaustion_policy: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="DEGRADED_ACCEPT",
        server_default="DEGRADED_ACCEPT",
    )
    machine_qc_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ranking_revision: Mapped[str] = mapped_column(String(100), nullable=False)
    ranking_weights: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prompt_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    rubric_revision_id: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    evaluator_bundle_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QCEvaluationFactRecord(OrchestrationBase):
    __tablename__ = "qc_evaluation_facts"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "project_id",
            "artifact_id",
            "artifact_digest",
            "gate_key",
            name="uq_orch_qc_evaluation_identity",
        ),
        CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_evaluation_stage",
        ),
        CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_qc_evaluation_gate_key",
        ),
        CheckConstraint(
            "judgment IN ('PASS', 'FAIL')",
            name="ck_orch_qc_evaluation_judgment",
        ),
        CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1000000",
            name="ck_orch_qc_evaluation_score",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1000000",
            name="ck_orch_qc_evaluation_confidence",
        ),
        CheckConstraint(
            "expected_selection_version >= 0",
            name="ck_orch_qc_evaluation_selection_version",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="artifact_digest"),
            name="ck_orch_qc_evaluation_artifact_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="evidence_pack_digest"),
            name="ck_orch_qc_evaluation_evidence_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="prompt_digest"),
            name="ck_orch_qc_evaluation_prompt_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="rubric_digest"),
            name="ck_orch_qc_evaluation_rubric_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="implementation_digest"),
            name="ck_orch_qc_evaluation_implementation",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="evaluator_bundle_digest"),
            name="ck_orch_qc_evaluation_evaluator",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="evaluation_digest"),
            name="ck_orch_qc_evaluation_digest",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_qc_evaluation_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["prompt_revision_id", "project_id", "prompt_digest"],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_prompt_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.qc_prompt_revisions.project_id",
                f"{ORCHESTRATION_SCHEMA}.qc_prompt_revisions.prompt_digest",
            ],
            name="fk_orch_qc_evaluation_prompt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "artifact_id",
                "project_id",
                "artifact_operation_run_id",
                "artifact_operation_attempt_id",
                "artifact_digest",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.operation_attempt_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.content_digest",
            ],
            name="fk_orch_qc_evaluation_artifact",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_qc_evaluation_artifact",
            "project_id",
            "workflow_run_id",
            "gate_key",
            "artifact_id",
            "evaluated_at",
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
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    gate_key: Mapped[str] = mapped_column(String(200), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    artifact_operation_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    evidence_pack_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    evidence_pack_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    expected_selection_version: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    prompt_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    prompt_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    rubric_revision_id: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    rubric_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str] = mapped_column(String(200), nullable=False)
    implementation_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    evaluator_bundle_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    judgment: Mapped[str] = mapped_column(String(8), nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    defects: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    recommended_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    repair_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    h3_qc: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evaluation_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QCCandidateVersionRecord(OrchestrationBase):
    __tablename__ = "qc_candidate_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            "ordinal",
            name="uq_orch_qc_candidate_ordinal",
        ),
        UniqueConstraint(
            "project_id",
            "artifact_id",
            "gate_key",
            name="uq_orch_qc_candidate_artifact",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_candidate_scope",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "gate_key",
            name="uq_orch_qc_candidate_gate_scope",
        ),
        CheckConstraint("ordinal > 0", name="ck_orch_qc_candidate_ordinal"),
        CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_candidate_stage",
        ),
        CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_qc_candidate_gate_key",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="candidate_digest"),
            name="ck_orch_qc_candidate_digest",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_qc_candidate_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "evaluation_id",
                "project_id",
                "artifact_id",
                "artifact_digest",
                "gate_key",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.id",
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.project_id",
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.artifact_id",
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.artifact_digest",
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.gate_key",
            ],
            name="fk_orch_qc_candidate_evaluation",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_qc_candidate_gate",
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            "ordinal",
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
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    gate_key: Mapped[str] = mapped_column(String(200), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    generation_usage: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    candidate_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class QCGoldDatasetRevisionRecord(OrchestrationBase):
    __tablename__ = "qc_gold_dataset_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "dataset_key",
            "revision",
            name="uq_orch_qc_gold_revision",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "dataset_digest",
            name="uq_orch_qc_gold_identity",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_gold_scope",
        ),
        CheckConstraint("revision > 0", name="ck_orch_qc_gold_revision"),
        CheckConstraint(
            SHA256_CHECK.format(column="dataset_digest"),
            name="ck_orch_qc_gold_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_qc_gold_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_gold_dataset_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.qc_gold_dataset_revisions.project_id",
            ],
            name="fk_orch_qc_gold_parent",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True)
    )
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    dataset_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class QCCalibrationReportRecord(OrchestrationBase):
    __tablename__ = "qc_calibration_reports"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "gold_dataset_revision_id",
            "evaluator_bundle_digest",
            name="uq_orch_qc_calibration_input",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_qc_calibration_scope"
        ),
        CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_calibration_stage",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="evaluator_bundle_digest"),
            name="ck_orch_qc_calibration_evaluator",
        ),
        ForeignKeyConstraint(
            [
                "gold_dataset_revision_id",
                "project_id",
                "gold_dataset_digest",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_gold_dataset_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.qc_gold_dataset_revisions.project_id",
                f"{ORCHESTRATION_SCHEMA}.qc_gold_dataset_revisions.dataset_digest",
            ],
            name="fk_orch_qc_calibration_gold",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    gold_dataset_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    gold_dataset_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    evaluator_bundle_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failures: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QCCertificationEventRecord(OrchestrationBase):
    __tablename__ = "qc_certification_events"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_certification_scope",
        ),
        CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_certification_stage",
        ),
        CheckConstraint(
            "status IN ('CERTIFIED', 'REVOKED')",
            name="ck_orch_qc_certification_status",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="evaluator_bundle_digest"),
            name="ck_orch_qc_certification_evaluator",
        ),
        ForeignKeyConstraint(
            ["calibration_report_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_calibration_reports.id",
                f"{ORCHESTRATION_SCHEMA}.qc_calibration_reports.project_id",
            ],
            name="fk_orch_qc_certification_report",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_qc_certification_current",
            "project_id",
            "stage",
            "evaluator_bundle_digest",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluator_bundle_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    calibration_report_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    gold_dataset_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    issued_by_actor: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QCGateDecisionRecord(OrchestrationBase):
    __tablename__ = "qc_gate_decisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            "decision_sequence",
            name="uq_orch_qc_gate_decision_sequence",
        ),
        CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_gate_decision_stage",
        ),
        CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_qc_gate_decision_gate_key",
        ),
        CheckConstraint(
            "outcome IN ('SELECTED', 'REWORK_PLANNED', 'WAITING_HUMAN', "
            "'DEGRADED_ACCEPTED', 'BLOCKED_UNCERTIFIED')",
            name="ck_orch_qc_gate_decision_outcome",
        ),
        CheckConstraint(
            "decision_sequence > 0",
            name="ck_orch_qc_gate_decision_sequence",
        ),
        CheckConstraint(
            "expected_selection_version >= 0",
            name="ck_orch_qc_gate_decision_selection_version",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_qc_gate_decision_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["policy_snapshot_id", "project_id", "gate_key"],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_gate_policy_snapshots.id",
                f"{ORCHESTRATION_SCHEMA}.qc_gate_policy_snapshots.project_id",
                f"{ORCHESTRATION_SCHEMA}.qc_gate_policy_snapshots.gate_key",
            ],
            name="fk_orch_qc_gate_decision_policy",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "project_id", "gate_key"],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_candidate_versions.id",
                f"{ORCHESTRATION_SCHEMA}.qc_candidate_versions.project_id",
                f"{ORCHESTRATION_SCHEMA}.qc_candidate_versions.gate_key",
            ],
            name="fk_orch_qc_gate_decision_candidate",
            ondelete="RESTRICT",
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
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    gate_key: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    candidate_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    decision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_selection_version: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HumanReviewTaskRecord(OrchestrationBase):
    """Durable, project-scoped authority for one quality-gate review."""

    __tablename__ = "human_review_tasks"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_human_review_task_scope"
        ),
        UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            "policy_snapshot_id",
            name="uq_orch_human_review_gate",
        ),
        CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_human_review_stage",
        ),
        CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_human_review_gate_key",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'DECIDED', 'CANCELLED')",
            name="ck_orch_human_review_status",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('ACCEPT', 'REWORK', 'REJECT')",
            name="ck_orch_human_review_decision",
        ),
        CheckConstraint(
            "(status = 'OPEN' AND decision IS NULL "
            "AND decided_by_actor IS NULL AND decided_at IS NULL) OR "
            "(status = 'DECIDED' AND decision IS NOT NULL "
            "AND decided_by_actor IS NOT NULL AND decided_at IS NOT NULL) OR "
            "(status = 'CANCELLED' AND decision IS NULL)",
            name="ck_orch_human_review_terminal",
        ),
        CheckConstraint(
            "expected_selection_version >= 0",
            name="ck_orch_human_review_selection_version",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_orch_human_review_state_version",
        ),
        CheckConstraint(
            "(gate_operation_run_id IS NULL "
            "AND gate_operation_attempt_id IS NULL) OR "
            "(gate_operation_run_id IS NOT NULL "
            "AND gate_operation_attempt_id IS NOT NULL)",
            name="ck_orch_human_review_gate_binding_pair",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="artifact_digest"),
            name="ck_orch_human_review_artifact_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="candidate_set_digest"),
            name="ck_orch_human_review_candidates_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="policy_digest"),
            name="ck_orch_human_review_policy_digest",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_human_review_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "gate_operation_attempt_id",
                "gate_operation_run_id",
                "project_id",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_human_review_gate_attempt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["policy_snapshot_id", "project_id", "gate_key"],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_gate_policy_snapshots.id",
                f"{ORCHESTRATION_SCHEMA}.qc_gate_policy_snapshots.project_id",
                f"{ORCHESTRATION_SCHEMA}.qc_gate_policy_snapshots.gate_key",
            ],
            name="fk_orch_human_review_policy",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["selection_head_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.selection_heads.id",
                f"{ORCHESTRATION_SCHEMA}.selection_heads.project_id",
            ],
            name="fk_orch_human_review_selection",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "artifact_id",
                "project_id",
                "artifact_operation_run_id",
                "artifact_operation_attempt_id",
                "artifact_digest",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.operation_attempt_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.content_digest",
            ],
            name="fk_orch_human_review_artifact",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_human_review_project_status",
            "project_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_orch_human_review_workflow_stage",
            "workflow_run_id",
            "stage",
            "gate_key",
            "created_at",
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
    gate_operation_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True)
    )
    gate_operation_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True)
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    gate_key: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    artifact_operation_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    candidate_set: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False
    )
    candidate_set_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    selection_head_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    expected_selection_version: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    creation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    remaining_defects: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", server_default="OPEN"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    decision: Mapped[str | None] = mapped_column(String(16))
    selected_candidate_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True)
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_by_actor: Mapped[str | None] = mapped_column(String(200))
    decided_by_role: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class HumanReviewEventRecord(OrchestrationBase):
    __tablename__ = "human_review_events"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "sequence", name="uq_orch_human_review_event_sequence"
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_human_review_event_scope"
        ),
        CheckConstraint(
            "event_type IN ('TASK_OPENED', 'TASK_DECIDED', 'TASK_CANCELLED')",
            name="ck_orch_human_review_event_type",
        ),
        CheckConstraint(
            "sequence > 0", name="ck_orch_human_review_event_sequence"
        ),
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.human_review_tasks.id",
                f"{ORCHESTRATION_SCHEMA}.human_review_tasks.project_id",
            ],
            name="fk_orch_human_review_event_task",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_human_review_event_task",
            "task_id",
            "sequence",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HumanReviewNotificationRecord(OrchestrationBase):
    """In-app inbox item. No external delivery address is stored."""

    __tablename__ = "human_review_notifications"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "recipient_role",
            name="uq_orch_human_review_notification_role",
        ),
        CheckConstraint(
            "recipient_role IN ('owner', 'reviewer')",
            name="ck_orch_human_review_notification_role",
        ),
        ForeignKeyConstraint(
            ["event_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.human_review_events.id",
                f"{ORCHESTRATION_SCHEMA}.human_review_events.project_id",
            ],
            name="fk_orch_human_review_notification_event",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.human_review_tasks.id",
                f"{ORCHESTRATION_SCHEMA}.human_review_tasks.project_id",
            ],
            name="fk_orch_human_review_notification_task",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_human_review_notification_inbox",
            "project_id",
            "recipient_role",
            "created_at",
            "id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HumanReviewOutboxRecord(OrchestrationBase):
    """Transactional outbox for in-app notification projection only."""

    __tablename__ = "human_review_outbox"
    __table_args__ = (
        UniqueConstraint(
            "event_id", name="uq_orch_human_review_outbox_event"
        ),
        CheckConstraint(
            "topic = 'in_app.human_review'",
            name="ck_orch_human_review_outbox_topic",
        ),
        ForeignKeyConstraint(
            ["event_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.human_review_events.id",
                f"{ORCHESTRATION_SCHEMA}.human_review_events.project_id",
            ],
            name="fk_orch_human_review_outbox_event",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_human_review_outbox_pending",
            "published_at",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    topic: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="in_app.human_review",
        server_default="in_app.human_review",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class ProjectTemplateRecord(OrchestrationBase):
    """Immutable, versioned project template (folders + workflow contract)."""

    __tablename__ = "project_templates"
    __table_args__ = (
        UniqueConstraint(
            "template_key",
            "version",
            name="uq_orch_project_templates_key_version",
        ),
        UniqueConstraint(
            "id",
            "template_key",
            "version",
            "digest",
            name="uq_orch_project_templates_identity",
        ),
        CheckConstraint(
            "length(template_key) BETWEEN 1 AND 120",
            name="ck_orch_project_templates_key_length",
        ),
        CheckConstraint(
            "version > 0", name="ck_orch_project_templates_version"
        ),
        CheckConstraint(
            "length(work_unit_kind) BETWEEN 1 AND 64",
            name="ck_orch_project_templates_work_unit_kind",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_project_templates_digest",
        ),
        Index(
            "ix_orch_project_templates_key_version",
            "template_key",
            "version",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    template_key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    work_unit_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    folder_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    workflow_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


@event.listens_for(ProjectTemplateRecord.__table__, "after_create")
def _seed_builtin_project_templates(_target, connection, **_kwargs) -> None:
    """Keep ORM-created test/development schemas consistent with migrations."""

    connection.execute(
        ProjectTemplateRecord.__table__.insert(),
        [
            {
                "id": GENERAL_VIDEO_TEMPLATE_ID,
                "template_key": "general_video",
                "version": 1,
                "work_unit_kind": "clip",
                "folder_schema": {},
                "workflow_schema": {"key": "general_video"},
                "digest": GENERAL_VIDEO_TEMPLATE_DIGEST,
                "created_by_actor": "system.backfill",
            },
            {
                "id": SHORT_DRAMA_TEMPLATE_ID,
                "template_key": "short_drama",
                "version": 2,
                "work_unit_kind": "episode",
                "folder_schema": {"roles": list(SHORT_DRAMA_FOLDER_ROLES)},
                "workflow_schema": {"key": "short_drama"},
                "digest": SHORT_DRAMA_TEMPLATE_DIGEST,
                "created_by_actor": "system.product-backfill",
            },
        ],
    )


class FactoryProjectBindingRecord(OrchestrationBase):
    """One-to-one binding between a Hub project and a Factory project."""

    __tablename__ = "factory_project_bindings"
    __table_args__ = (
        UniqueConstraint(
            "project_id", name="uq_orch_factory_bindings_project"
        ),
        UniqueConstraint(
            "factory_project_key",
            name="uq_orch_factory_bindings_factory_key",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_factory_bindings_scope"
        ),
        CheckConstraint(
            "length(factory_project_key) BETWEEN 1 AND 200",
            name="ck_orch_factory_bindings_factory_key_length",
        ),
        CheckConstraint(
            "length(factory_revision) BETWEEN 1 AND 200",
            name="ck_orch_factory_bindings_revision_length",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_factory_bindings_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_factory_bindings_factory_key",
            "factory_project_key",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    factory_project_key: Mapped[str] = mapped_column(String(200), nullable=False)
    factory_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkUnitRecord(OrchestrationBase):
    """Scoped work unit (episode / scene / shot) inside a project."""

    __tablename__ = "work_units"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "kind",
            "external_key",
            name="uq_orch_work_units_project_kind_key",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_work_units_scope"
        ),
        CheckConstraint(
            "length(kind) BETWEEN 1 AND 64",
            name="ck_orch_work_units_kind_length",
        ),
        CheckConstraint(
            "length(external_key) BETWEEN 1 AND 200",
            name="ck_orch_work_units_external_key_length",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED')",
            name="ck_orch_work_units_status",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_work_units_version"
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_work_units_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_work_units_project_kind",
            "project_id",
            "kind",
            "external_key",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    external_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="DRAFT", server_default="DRAFT"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
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


class FolderProjectionRecord(OrchestrationBase):
    """Materialized folder projection for one work unit node."""

    __tablename__ = "folder_projections"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "work_unit_id",
            "node_key",
            name="uq_orch_folder_projections_node",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_folder_projections_scope"
        ),
        CheckConstraint(
            "length(node_key) BETWEEN 1 AND 200",
            name="ck_orch_folder_projections_node_key",
        ),
        CheckConstraint(
            "parent_key IS NULL OR length(parent_key) BETWEEN 1 AND 200",
            name="ck_orch_folder_projections_parent_key",
        ),
        CheckConstraint(
            "length(role) BETWEEN 1 AND 64",
            name="ck_orch_folder_projections_role",
        ),
        CheckConstraint(
            "projection_version > 0",
            name="ck_orch_folder_projections_projection_version",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_folder_projections_version"
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_folder_projections_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["work_unit_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.work_units.id",
                f"{ORCHESTRATION_SCHEMA}.work_units.project_id",
            ],
            name="fk_orch_folder_projections_work_unit",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_folder_projections_work_unit",
            "project_id",
            "work_unit_id",
            "node_key",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    work_unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_key: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    projection_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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


class SkillRecord(OrchestrationBase):
    """Stable skill registry keyed by ``skill_key``."""

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("skill_key", name="uq_orch_skills_key"),
        CheckConstraint(
            "length(skill_key) BETWEEN 1 AND 160",
            name="ck_orch_skills_key_length",
        ),
        CheckConstraint(
            "lifecycle IN ('DRAFT', 'APPROVED', 'DEPRECATED', 'RETIRED')",
            name="ck_orch_skills_lifecycle",
        ),
        CheckConstraint(
            "current_revision IS NULL OR current_revision > 0",
            name="ck_orch_skills_current_revision",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_skills_version"
        ),
        Index(
            "ix_orch_skills_lifecycle",
            "lifecycle",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    skill_key: Mapped[str] = mapped_column(String(160), nullable=False)
    lifecycle: Mapped[str] = mapped_column(
        String(16), nullable=False, default="DRAFT", server_default="DRAFT"
    )
    current_revision: Mapped[int | None] = mapped_column(Integer)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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


class SkillRevisionRecord(OrchestrationBase):
    """Immutable, approved revision of a skill fragment."""

    __tablename__ = "skill_revisions"
    __table_args__ = (
        UniqueConstraint(
            "skill_id",
            "revision",
            name="uq_orch_skill_revisions_number",
        ),
        UniqueConstraint(
            "id",
            "skill_id",
            "revision",
            "digest",
            name="uq_orch_skill_revisions_identity",
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_skill_revisions_positive"
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'DEPRECATED', 'RETIRED')",
            name="ck_orch_skill_revisions_status",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_skill_revisions_digest",
        ),
        ForeignKeyConstraint(
            ["skill_id"],
            [f"{ORCHESTRATION_SCHEMA}.skills.id"],
            name="fk_orch_skill_revisions_skill",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_skill_revisions_skill_revision",
            "skill_id",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    skill_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    applicability: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    risks: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectSkillBindingRecord(OrchestrationBase):
    """Approved-only binding of a skill revision to a project scope."""

    __tablename__ = "project_skill_bindings"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_project_skill_bindings_command",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_project_skill_bindings_scope"
        ),
        CheckConstraint(
            "scope IN ('project', 'work_unit')",
            name="ck_orch_project_skill_bindings_scope",
        ),
        CheckConstraint(
            "(scope = 'project' AND scope_ref IS NULL) OR "
            "(scope = 'work_unit' AND scope_ref IS NOT NULL)",
            name="ck_orch_project_skill_bindings_scope_shape",
        ),
        CheckConstraint(
            "priority >= 0", name="ck_orch_project_skill_bindings_priority"
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_project_skill_bindings_command_length",
        ),
        CheckConstraint(
            "state_version >= 0", name="ck_orch_project_skill_bindings_version"
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_project_skill_bindings_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["skill_revision_id"],
            [f"{ORCHESTRATION_SCHEMA}.skill_revisions.id"],
            name="fk_orch_project_skill_bindings_revision",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_project_skill_bindings_project_priority",
            "project_id",
            "priority",
        ),
        Index(
            "uq_orch_project_skill_bindings_project_scope",
            "project_id",
            "skill_revision_id",
            unique=True,
            postgresql_where=text("scope = 'project'"),
            sqlite_where=text("scope = 'project'"),
        ),
        Index(
            "uq_orch_project_skill_bindings_work_unit_scope",
            "project_id",
            "skill_revision_id",
            "scope_ref",
            unique=True,
            postgresql_where=text("scope = 'work_unit'"),
            sqlite_where=text("scope = 'work_unit'"),
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    skill_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="project", server_default="project"
    )
    scope_ref: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RunSkillSnapshotRecord(OrchestrationBase):
    """Immutable, ordered skill snapshot frozen for one workflow run."""

    __tablename__ = "run_skill_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "workflow_run_id",
            name="uq_orch_run_skill_snapshots_run",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_run_skill_snapshots_scope"
        ),
        CheckConstraint(
            "status IN ('FROZEN', 'UNKNOWN', 'STALE')",
            name="ck_orch_run_skill_snapshots_status",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_run_skill_snapshots_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_run_skill_snapshots_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_run_skill_snapshots_project_run",
            "project_id",
            "workflow_run_id",
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
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="UNKNOWN",
        server_default="UNKNOWN",
    )
    ordered_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectSkillProfileRevisionRecord(OrchestrationBase):
    """Immutable full Skill selection for a project.

    Unlike the legacy append-only binding rows, each revision carries the
    complete ordered profile.  Removing, reordering, or changing scope creates
    a new revision and never mutates the profile used by an earlier run.
    """

    __tablename__ = "project_skill_profile_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "revision",
            name="uq_orch_project_skill_profiles_number",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_project_skill_profiles_command",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_project_skill_profiles_scope"
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_project_skill_profiles_positive"
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_project_skill_profiles_command_length",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_project_skill_profiles_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_project_skill_profiles_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.project_skill_profile_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.project_skill_profile_revisions.project_id",
            ],
            name="fk_orch_project_skill_profiles_previous",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_project_skill_profiles_project_revision",
            "project_id",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MethodologySnapshotRecord(OrchestrationBase):
    """Immutable executable methodology frozen before any creative model call."""

    __tablename__ = "methodology_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "snapshot_key",
            name="uq_orch_methodology_snapshots_key",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_methodology_snapshots_scope"
        ),
        CheckConstraint(
            "status IN ('FROZEN', 'STALE')",
            name="ck_orch_methodology_snapshots_status",
        ),
        CheckConstraint(
            "length(snapshot_key) BETWEEN 1 AND 255",
            name="ck_orch_methodology_snapshots_key_length",
        ),
        CheckConstraint(
            "length(purpose) BETWEEN 1 AND 120",
            name="ck_orch_methodology_snapshots_purpose_length",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_methodology_snapshots_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_methodology_snapshots_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["work_unit_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.work_units.id",
                f"{ORCHESTRATION_SCHEMA}.work_units.project_id",
            ],
            name="fk_orch_methodology_snapshots_work_unit",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["profile_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.project_skill_profile_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.project_skill_profile_revisions.project_id",
            ],
            name="fk_orch_methodology_snapshots_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_methodology_snapshots_run",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_methodology_snapshots_project_work_unit",
            "project_id",
            "work_unit_id",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    work_unit_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    profile_revision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    workflow_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    snapshot_key: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="FROZEN", server_default="FROZEN"
    )
    ordered_cards: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    legacy_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PromptCompilationRecord(OrchestrationBase):
    """Immutable GLM direction and provider-prompt lineage fact."""

    __tablename__ = "prompt_compilations"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "cache_key",
            name="uq_orch_prompt_compilations_cache",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_prompt_compilations_scope"
        ),
        CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED')",
            name="ck_orch_prompt_compilations_status",
        ),
        CheckConstraint(
            "compilation_mode IN ('legacy', 'shadow', 'enforced')",
            name="ck_orch_prompt_compilations_mode",
        ),
        CheckConstraint(
            "modality IN ('text', 'image', 'video')",
            name="ck_orch_prompt_compilations_modality",
        ),
        CheckConstraint(
            "length(operation) BETWEEN 1 AND 120",
            name="ck_orch_prompt_compilations_operation_length",
        ),
        CheckConstraint(
            "length(target_model_family) BETWEEN 1 AND 120",
            name="ck_orch_prompt_compilations_target_length",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="input_digest"),
            name="ck_orch_prompt_compilations_input_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="cache_key"),
            name="ck_orch_prompt_compilations_cache_key",
        ),
        CheckConstraint(
            "(status = 'SUCCEEDED' AND direction_contract IS NOT NULL "
            "AND compiled_bundle IS NOT NULL AND failure IS NULL) OR "
            "(status = 'FAILED' AND compiled_bundle IS NULL "
            "AND failure IS NOT NULL)",
            name="ck_orch_prompt_compilations_result_shape",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_prompt_compilations_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["work_unit_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.work_units.id",
                f"{ORCHESTRATION_SCHEMA}.work_units.project_id",
            ],
            name="fk_orch_prompt_compilations_work_unit",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["methodology_snapshot_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.methodology_snapshots.id",
                f"{ORCHESTRATION_SCHEMA}.methodology_snapshots.project_id",
            ],
            name="fk_orch_prompt_compilations_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["shot_plan_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.shot_plan_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.shot_plan_revisions.project_id",
            ],
            name="fk_orch_prompt_compilations_shot_plan",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.id",
                f"{ORCHESTRATION_SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_prompt_compilations_run",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_prompt_compilations_project_work_unit",
            "project_id",
            "work_unit_id",
            "created_at",
        ),
        Index(
            "ix_orch_prompt_compilations_snapshot_operation",
            "methodology_snapshot_id",
            "operation",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    work_unit_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    methodology_snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    shot_plan_revision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    workflow_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    unit_key: Mapped[str | None] = mapped_column(String(200))
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    target_model_family: Mapped[str] = mapped_column(String(120), nullable=False)
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    compilation_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    compiler_model: Mapped[str] = mapped_column(String(120), nullable=False)
    compiler_model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    credential_revision_ref: Mapped[str | None] = mapped_column(String(200))
    adapter_key: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(120), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    methodology_brief: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    direction_contract: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True)
    )
    applied_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    omitted_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    compiled_bundle: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True)
    )
    failure: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True)
    )
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceArtifactRecord(OrchestrationBase):
    """Content-addressed source artifact (DOCX, image, transcript, ...)."""

    __tablename__ = "source_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "content_digest",
            "source_kind",
            name="uq_orch_source_artifacts_content",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_source_artifacts_scope"
        ),
        CheckConstraint(
            "length(source_kind) BETWEEN 1 AND 64",
            name="ck_orch_source_artifacts_kind",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="content_digest"),
            name="ck_orch_source_artifacts_digest",
        ),
        CheckConstraint(
            "byte_size > 0", name="ck_orch_source_artifacts_byte_size"
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_source_artifacts_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_source_artifacts_project_digest",
            "project_id",
            "content_digest",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    logical_role: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceImportRevisionRecord(OrchestrationBase):
    """Immutable import revision referencing a source artifact."""

    __tablename__ = "source_import_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_artifact_id",
            "revision",
            name="uq_orch_source_import_revisions_number",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_source_import_revisions_scope"
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_source_import_revisions_positive"
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_source_import_revisions_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_source_import_revisions_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_artifact_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.source_artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.source_artifacts.project_id",
            ],
            name="fk_orch_source_import_revisions_artifact",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_source_import_revisions_artifact",
            "project_id",
            "source_artifact_id",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_artifact_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShotPlanRevisionRecord(OrchestrationBase):
    """Immutable shot-plan revision for one work unit."""

    __tablename__ = "shot_plan_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "work_unit_id",
            "revision",
            name="uq_orch_shot_plan_revisions_number",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_shot_plan_revisions_command",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_shot_plan_revisions_scope"
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_shot_plan_revisions_positive"
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_shot_plan_revisions_command_length",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_shot_plan_revisions_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_shot_plan_revisions_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["work_unit_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.work_units.id",
                f"{ORCHESTRATION_SCHEMA}.work_units.project_id",
            ],
            name="fk_orch_shot_plan_revisions_work_unit",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_shot_plan_revisions_work_unit",
            "project_id",
            "work_unit_id",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    work_unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShotPlanUnitRecord(OrchestrationBase):
    """Ordered unit inside one immutable shot-plan revision."""

    __tablename__ = "shot_plan_units"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "shot_plan_revision_id",
            "ordinal",
            name="uq_orch_shot_plan_units_ordinal",
        ),
        UniqueConstraint(
            "project_id",
            "shot_plan_revision_id",
            "unit_key",
            name="uq_orch_shot_plan_units_key",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_shot_plan_units_scope"
        ),
        CheckConstraint(
            "ordinal > 0", name="ck_orch_shot_plan_units_ordinal"
        ),
        CheckConstraint(
            "length(unit_key) BETWEEN 1 AND 200",
            name="ck_orch_shot_plan_units_unit_key",
        ),
        CheckConstraint(
            "length(unit_kind) BETWEEN 1 AND 64",
            name="ck_orch_shot_plan_units_unit_kind",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_shot_plan_units_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["shot_plan_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.shot_plan_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.shot_plan_revisions.project_id",
            ],
            name="fk_orch_shot_plan_units_revision",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_shot_plan_units_revision_ordinal",
            "project_id",
            "shot_plan_revision_id",
            "ordinal",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    shot_plan_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_key: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GenerationStrategyRevisionRecord(OrchestrationBase):
    """Immutable generation-strategy policy revision for a project."""

    __tablename__ = "generation_strategy_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "strategy_key",
            "revision",
            name="uq_orch_generation_strategy_number",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_generation_strategy_command",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_generation_strategy_scope"
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_generation_strategy_positive"
        ),
        CheckConstraint(
            "length(strategy_key) BETWEEN 1 AND 120",
            name="ck_orch_generation_strategy_key_length",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_generation_strategy_command_length",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_generation_strategy_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_generation_strategy_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_generation_strategy_project_key",
            "project_id",
            "strategy_key",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    strategy_key: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FactoryQCPolicyRevisionRecord(OrchestrationBase):
    """Immutable Factory QC policy revision for a project."""

    __tablename__ = "factory_qc_policy_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "policy_key",
            "revision",
            name="uq_orch_factory_qc_policy_number",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_factory_qc_policy_command",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_factory_qc_policy_scope"
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_factory_qc_policy_positive"
        ),
        CheckConstraint(
            "length(policy_key) BETWEEN 1 AND 120",
            name="ck_orch_factory_qc_policy_key_length",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_factory_qc_policy_command_length",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_factory_qc_policy_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_factory_qc_policy_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_factory_qc_policy_project_key",
            "project_id",
            "policy_key",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_key: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RepairProposalRecord(OrchestrationBase):
    """Immutable repair proposal for a targeted fact or run."""

    __tablename__ = "repair_proposals"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "proposal_key",
            "revision",
            name="uq_orch_repair_proposals_number",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_repair_proposals_scope"
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_repair_proposals_positive"
        ),
        CheckConstraint(
            "length(proposal_key) BETWEEN 1 AND 120",
            name="ck_orch_repair_proposals_key_length",
        ),
        CheckConstraint(
            "target_kind IN ('shot_plan', 'operation_run', 'artifact', "
            "'selection')",
            name="ck_orch_repair_proposals_target_kind",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_repair_proposals_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_repair_proposals_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_repair_proposals_project_key",
            "project_id",
            "proposal_key",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposal_key: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModeChangeProposalRecord(OrchestrationBase):
    """Immutable mode-change proposal for a project."""

    __tablename__ = "mode_change_proposals"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "proposal_key",
            "revision",
            name="uq_orch_mode_change_proposals_number",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_mode_change_proposals_scope"
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_mode_change_proposals_positive"
        ),
        CheckConstraint(
            "length(proposal_key) BETWEEN 1 AND 120",
            name="ck_orch_mode_change_proposals_key_length",
        ),
        CheckConstraint(
            "mode IN ('draft', 'assisted', 'autonomous')",
            name="ck_orch_mode_change_proposals_mode",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_mode_change_proposals_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_mode_change_proposals_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_mode_change_proposals_project_key",
            "project_id",
            "proposal_key",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposal_key: Mapped[str] = mapped_column(String(120), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeliveryRevisionRecord(OrchestrationBase):
    """Immutable delivery revision for a project."""

    __tablename__ = "delivery_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "revision",
            name="uq_orch_delivery_revisions_number",
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_orch_delivery_revisions_scope"
        ),
        CheckConstraint(
            "revision > 0", name="ck_orch_delivery_revisions_positive"
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="digest"),
            name="ck_orch_delivery_revisions_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_delivery_revisions_project",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_delivery_revisions_project_revision",
            "project_id",
            "revision",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductCommandLedgerRecord(OrchestrationBase):
    """Durable BFF command ledger for the ``/api/v2`` product surface.

    Every product write command records its canonical payload digest and the
    exact response it returned so an identical replay returns the same result
    and a same-key/different-payload replay raises a deterministic conflict.
    The ledger is a BFF idempotency record; it never replaces the durable
    domain facts written through ``ProductService`` (shot plans, policies,
    repair/mode decisions, ...), which carry their own integrity guards.

    ``scope_key`` is a non-null string anchor (``"global"``,
    ``"project:<uuid>"`` or ``"work_unit:<project_uuid>:<wu_uuid>"``) so the
    command idempotency unique key works on both PostgreSQL and SQLite even
    when a command has no project (global research / cookie broker).
    """

    __tablename__ = "product_command_ledger"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "command_kind",
            "command_idempotency_key",
            name="uq_orch_product_command_ledger_command",
        ),
        UniqueConstraint(
            "id", "scope_key", name="uq_orch_product_command_ledger_scope"
        ),
        CheckConstraint(
            "length(scope_key) BETWEEN 1 AND 240",
            name="ck_orch_product_command_ledger_scope_key",
        ),
        CheckConstraint(
            "length(command_kind) BETWEEN 1 AND 64",
            name="ck_orch_product_command_ledger_kind",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_product_command_ledger_command_length",
        ),
        CheckConstraint(
            "length(actor_id) BETWEEN 1 AND 100",
            name="ck_orch_product_command_ledger_actor",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="payload_digest"),
            name="ck_orch_product_command_ledger_payload_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="result_digest"),
            name="ck_orch_product_command_ledger_result_digest",
        ),
        CheckConstraint(
            "status_code BETWEEN 200 AND 299",
            name="ck_orch_product_command_ledger_status",
        ),
        Index(
            "ix_orch_product_command_ledger_kind_created",
            "command_kind",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    scope_key: Mapped[str] = mapped_column(String(240), nullable=False)
    command_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Shidu facts deliberately live in the orchestration database.  Stable rows
# carry a project scope and every reference to another Shidu row repeats that
# scope, preventing an identifier from being spliced across projects.
class BookRecord(OrchestrationBase):
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_books_scope"),
        UniqueConstraint(
            "project_id", "identity_digest", name="uq_orch_books_identity"
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_books_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_books_command_length",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="identity_digest"),
            name="ck_orch_books_identity_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_books_project",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    identity_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    edition: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    translator: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BookMergeRecord(OrchestrationBase):
    """Append-only alias decision; neither Book identity is rewritten."""

    __tablename__ = "book_merge_records"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_book_merges_scope"),
        UniqueConstraint(
            "project_id", "source_book_id", name="uq_orch_book_merges_source"
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_book_merges_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_book_merges_command_length",
        ),
        CheckConstraint(
            "source_book_id <> target_book_id", name="ck_orch_book_merges_distinct"
        ),
        ForeignKeyConstraint(
            ["source_book_id", "project_id"],
            [f"{ORCHESTRATION_SCHEMA}.books.id", f"{ORCHESTRATION_SCHEMA}.books.project_id"],
            name="fk_orch_book_merges_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_book_id", "project_id"],
            [f"{ORCHESTRATION_SCHEMA}.books.id", f"{ORCHESTRATION_SCHEMA}.books.project_id"],
            name="fk_orch_book_merges_target",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_book_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_book_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InputResolutionRecord(OrchestrationBase):
    __tablename__ = "input_resolutions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_input_resolutions_scope"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_input_resolutions_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_input_resolutions_command_length"),
        CheckConstraint("status IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED')", name="ck_orch_input_resolutions_status"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_input_resolutions_digest"),
        ForeignKeyConstraint(["project_id"], [f"{ORCHESTRATION_SCHEMA}.projects.id"], name="fk_orch_input_resolutions_project", ondelete="RESTRICT"),
        ForeignKeyConstraint(["selected_book_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.books.id", f"{ORCHESTRATION_SCHEMA}.books.project_id"], name="fk_orch_input_resolutions_book", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_input: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate_book_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    selected_book_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BookDiscoveryCandidateRecord(OrchestrationBase):
    """Immutable Reader-verified identity offered for one input resolution."""

    __tablename__ = "book_discovery_candidates"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_book_discovery_candidates_scope"
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "input_resolution_id",
            name="uq_orch_book_discovery_candidates_resolution_scope",
        ),
        UniqueConstraint(
            "input_resolution_id",
            "project_id",
            "ordinal",
            name="uq_orch_book_discovery_candidates_ordinal",
        ),
        UniqueConstraint(
            "input_resolution_id",
            "project_id",
            "identity_digest",
            name="uq_orch_book_discovery_candidates_identity",
        ),
        CheckConstraint(
            "ordinal > 0", name="ck_orch_book_discovery_candidates_ordinal"
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="identity_digest"),
            name="ck_orch_book_discovery_candidates_identity_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="reader_content_digest"),
            name="ck_orch_book_discovery_candidates_content_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="search_schema_digest"),
            name="ck_orch_book_discovery_candidates_search_schema",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="reader_schema_digest"),
            name="ck_orch_book_discovery_candidates_reader_schema",
        ),
        CheckConstraint(
            "length(title) BETWEEN 1 AND 300",
            name="ck_orch_book_discovery_candidates_title_length",
        ),
        CheckConstraint(
            "length(author) BETWEEN 1 AND 200",
            name="ck_orch_book_discovery_candidates_author_length",
        ),
        CheckConstraint(
            "length(language) BETWEEN 1 AND 32",
            name="ck_orch_book_discovery_candidates_language_length",
        ),
        CheckConstraint(
            "length(edition) <= 200 AND length(translator) <= 200",
            name="ck_orch_book_discovery_candidates_optional_identity_length",
        ),
        CheckConstraint(
            "length(search_provider) BETWEEN 1 AND 200",
            name="ck_orch_book_discovery_candidates_search_provider_length",
        ),
        CheckConstraint(
            "length(reader_provider) BETWEEN 1 AND 200",
            name="ck_orch_book_discovery_candidates_reader_provider_length",
        ),
        CheckConstraint(
            "canonical_url LIKE 'https://%' AND length(canonical_url) <= 2048",
            name="ck_orch_book_discovery_candidates_https_url",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_book_discovery_candidates_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["input_resolution_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.input_resolutions.id",
                f"{ORCHESTRATION_SCHEMA}.input_resolutions.project_id",
            ],
            name="fk_orch_book_discovery_candidates_resolution",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_book_discovery_candidates_resolution",
            "project_id",
            "input_resolution_id",
            "ordinal",
        ),
        Index(
            "ix_orch_book_discovery_candidates_identity",
            "project_id",
            "identity_digest",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    input_resolution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    edition: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    translator: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    identity_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    reader_content_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 of the exact Reader body observed and verified locally",
    )
    search_provider: Mapped[str] = mapped_column(String(200), nullable=False)
    search_schema_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reader_provider: Mapped[str] = mapped_column(String(200), nullable=False)
    reader_schema_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BookDiscoverySelectionRecord(OrchestrationBase):
    """Immutable selection of a persisted Reader-verified candidate."""

    __tablename__ = "book_discovery_selections"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_book_discovery_selections_scope"
        ),
        UniqueConstraint(
            "project_id",
            "input_resolution_id",
            name="uq_orch_book_discovery_selections_resolution",
        ),
        UniqueConstraint(
            "project_id",
            "input_resolution_id",
            "candidate_id",
            "book_id",
            name="uq_orch_book_discovery_selections_fact",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_book_discovery_selections_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_book_discovery_selections_command_length",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_book_discovery_selections_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["input_resolution_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.input_resolutions.id",
                f"{ORCHESTRATION_SCHEMA}.input_resolutions.project_id",
            ],
            name="fk_orch_book_discovery_selections_resolution",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "project_id", "input_resolution_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.book_discovery_candidates.id",
                f"{ORCHESTRATION_SCHEMA}.book_discovery_candidates.project_id",
                f"{ORCHESTRATION_SCHEMA}.book_discovery_candidates.input_resolution_id",
            ],
            name="fk_orch_book_discovery_selections_candidate",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["book_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.books.id",
                f"{ORCHESTRATION_SCHEMA}.books.project_id",
            ],
            name="fk_orch_book_discovery_selections_book",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_book_discovery_selections_resolution",
            "project_id",
            "input_resolution_id",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    input_resolution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    candidate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    book_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResearchJobRecord(OrchestrationBase):
    __tablename__ = "research_jobs"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_research_jobs_scope"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_research_jobs_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_research_jobs_command_length"),
        CheckConstraint("status IN ('queued', 'resolving', 'searching', 'reading', 'extracting', 'synthesizing', 'ready', 'insufficient', 'retryable_failed', 'failed')", name="ck_orch_research_jobs_status"),
        CheckConstraint("query_budget >= 0 AND reader_budget >= 0 AND retry_budget >= 0", name="ck_orch_research_jobs_budgets"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_research_jobs_digest"),
        ForeignKeyConstraint(["book_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.books.id", f"{ORCHESTRATION_SCHEMA}.books.project_id"], name="fk_orch_research_jobs_book", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    book_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", server_default="queued")
    query_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=4, server_default="4")
    reader_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=8, server_default="8")
    retry_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SearchQueryRecord(OrchestrationBase):
    __tablename__ = "search_queries"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_search_queries_scope"),
        UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_search_queries_job_scope"),
        UniqueConstraint("research_job_id", "project_id", "ordinal", name="uq_orch_search_queries_ordinal"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_search_queries_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_search_queries_command_length"),
        CheckConstraint("ordinal > 0", name="ck_orch_search_queries_ordinal"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_search_queries_digest"),
        ForeignKeyConstraint(["research_job_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.research_jobs.id", f"{ORCHESTRATION_SCHEMA}.research_jobs.project_id"], name="fk_orch_search_queries_job", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(160), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SearchHitRecord(OrchestrationBase):
    __tablename__ = "search_hits"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_search_hits_scope"),
        UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_search_hits_job_scope"),
        UniqueConstraint("search_query_id", "project_id", "research_job_id", "ordinal", name="uq_orch_search_hits_ordinal"),
        CheckConstraint("ordinal > 0", name="ck_orch_search_hits_ordinal"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_search_hits_digest"),
        ForeignKeyConstraint(["search_query_id", "project_id", "research_job_id"], [f"{ORCHESTRATION_SCHEMA}.search_queries.id", f"{ORCHESTRATION_SCHEMA}.search_queries.project_id", f"{ORCHESTRATION_SCHEMA}.search_queries.research_job_id"], name="fk_orch_search_hits_query", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    search_query_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SourceFailureRecord(OrchestrationBase):
    __tablename__ = "source_failures"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_source_failures_scope"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_source_failures_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_source_failures_command_length"),
        CheckConstraint("stage IN ('search', 'url_guard', 'reader', 'redirect')", name="ck_orch_source_failures_stage"),
        CheckConstraint("attempts >= 0", name="ck_orch_source_failures_attempts"),
        ForeignKeyConstraint(["research_job_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.research_jobs.id", f"{ORCHESTRATION_SCHEMA}.research_jobs.project_id"], name="fk_orch_source_failures_job", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SourceDocumentRevisionRecord(OrchestrationBase):
    __tablename__ = "source_document_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_source_documents_scope"),
        UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_source_documents_job_scope"),
        UniqueConstraint("project_id", "canonical_url", "revision", name="uq_orch_source_documents_revision"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_source_documents_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_source_documents_command_length"),
        CheckConstraint("revision > 0", name="ck_orch_source_documents_revision"),
        CheckConstraint(
            "(interaction_observed = true AND interaction_signal IS NOT NULL "
            "AND interaction_signal >= 0.0 AND interaction_signal <= 1.0) OR "
            "(interaction_observed = false AND interaction_signal IS NULL)",
            name="ck_orch_source_documents_interaction",
        ),
        CheckConstraint(SHA256_CHECK.format(column="content_digest"), name="ck_orch_source_documents_content_digest"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_source_documents_digest"),
        ForeignKeyConstraint(["research_job_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.research_jobs.id", f"{ORCHESTRATION_SCHEMA}.research_jobs.project_id"], name="fk_orch_source_documents_job", ondelete="RESTRICT"),
        ForeignKeyConstraint(["search_hit_id", "project_id", "research_job_id"], [f"{ORCHESTRATION_SCHEMA}.search_hits.id", f"{ORCHESTRATION_SCHEMA}.search_hits.project_id", f"{ORCHESTRATION_SCHEMA}.search_hits.research_job_id"], name="fk_orch_source_documents_search_hit", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_classification_version: Mapped[str] = mapped_column(String(100), nullable=False)
    registered_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    search_hit_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    interaction_observed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    interaction_signal: Mapped[float | None] = mapped_column(Float)
    interaction_metrics: Mapped[dict[str, int] | None] = mapped_column(JSON)
    interaction_normalization_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="shidu-public-interaction-v1",
        server_default="shidu-public-interaction-v1",
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvidenceClaimRecord(OrchestrationBase):
    __tablename__ = "evidence_claims"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_evidence_claims_scope"),
        UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_evidence_claims_job_scope"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_evidence_claims_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_evidence_claims_command_length"),
        CheckConstraint("claim_type IN ('plot_node', 'emotional_reaction', 'style_judgement', 'reader_fit', 'factual_context')", name="ck_orch_evidence_claims_type"),
        CheckConstraint("spoiler_level IN ('none', 'light', 'moderate', 'critical')", name="ck_orch_evidence_claims_spoiler"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_orch_evidence_claims_confidence"),
        CheckConstraint("conflict_severity IS NULL OR conflict_severity IN ('minor', 'major', 'critical')", name="ck_orch_evidence_claims_conflict_severity"),
        CheckConstraint(SHA256_CHECK.format(column="excerpt_digest"), name="ck_orch_evidence_claims_excerpt_digest"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_evidence_claims_digest"),
        ForeignKeyConstraint(["research_job_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.research_jobs.id", f"{ORCHESTRATION_SCHEMA}.research_jobs.project_id"], name="fk_orch_evidence_claims_job", ondelete="RESTRICT"),
        ForeignKeyConstraint(["source_document_revision_id", "project_id", "research_job_id"], [f"{ORCHESTRATION_SCHEMA}.source_document_revisions.id", f"{ORCHESTRATION_SCHEMA}.source_document_revisions.project_id", f"{ORCHESTRATION_SCHEMA}.source_document_revisions.research_job_id"], name="fk_orch_evidence_claims_document", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_document_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False, default="plot_node", server_default="plot_node")
    normalized_claim: Mapped[str] = mapped_column(Text, nullable=False)
    source_span: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    excerpt_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    is_direct_quote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    spoiler_level: Mapped[str] = mapped_column(String(16), nullable=False, default="light", server_default="light")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    conflict_group_key: Mapped[str | None] = mapped_column(String(160))
    conflict_severity: Mapped[str | None] = mapped_column(String(16))
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvidenceConflictAdjudicationRevisionRecord(OrchestrationBase):
    __tablename__ = "evidence_conflict_adjudication_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_evidence_adjudications_scope"),
        UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_evidence_adjudications_job_scope"),
        UniqueConstraint("research_job_id", "project_id", "revision", name="uq_orch_evidence_adjudications_revision"),
        UniqueConstraint("project_id", "research_job_id", "evidence_set_digest", "adjudicator_version", name="uq_orch_evidence_adjudications_semantic"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_evidence_adjudications_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_evidence_adjudications_command_length"),
        CheckConstraint("revision > 0", name="ck_orch_evidence_adjudications_revision"),
        CheckConstraint(SHA256_CHECK.format(column="evidence_set_digest"), name="ck_orch_evidence_adjudications_set_digest"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_evidence_adjudications_digest"),
        ForeignKeyConstraint(["research_job_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.research_jobs.id", f"{ORCHESTRATION_SCHEMA}.research_jobs.project_id"], name="fk_orch_evidence_adjudications_job", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_set_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    adjudicator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvidenceConflictAdjudicationMembershipRecord(OrchestrationBase):
    __tablename__ = "evidence_conflict_adjudication_memberships"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_evidence_adjudication_memberships_scope"),
        UniqueConstraint("adjudication_revision_id", "project_id", "research_job_id", "ordinal", name="uq_orch_evidence_adjudication_memberships_ordinal"),
        UniqueConstraint("adjudication_revision_id", "project_id", "research_job_id", "evidence_claim_id", name="uq_orch_evidence_adjudication_memberships_claim"),
        CheckConstraint("ordinal > 0", name="ck_orch_evidence_adjudication_memberships_ordinal"),
        ForeignKeyConstraint(["adjudication_revision_id", "project_id", "research_job_id"], [f"{ORCHESTRATION_SCHEMA}.evidence_conflict_adjudication_revisions.id", f"{ORCHESTRATION_SCHEMA}.evidence_conflict_adjudication_revisions.project_id", f"{ORCHESTRATION_SCHEMA}.evidence_conflict_adjudication_revisions.research_job_id"], name="fk_orch_evidence_adjudication_memberships_revision", ondelete="RESTRICT"),
        ForeignKeyConstraint(["evidence_claim_id", "project_id", "research_job_id"], [f"{ORCHESTRATION_SCHEMA}.evidence_claims.id", f"{ORCHESTRATION_SCHEMA}.evidence_claims.project_id", f"{ORCHESTRATION_SCHEMA}.evidence_claims.research_job_id"], name="fk_orch_evidence_adjudication_memberships_claim", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    adjudication_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvidencePackRevisionRecord(OrchestrationBase):
    __tablename__ = "evidence_pack_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_evidence_packs_scope"),
        UniqueConstraint("id", "project_id", "research_job_id", name="uq_orch_evidence_packs_job_scope"),
        UniqueConstraint("research_job_id", "project_id", "revision", name="uq_orch_evidence_packs_revision"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_evidence_packs_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_evidence_packs_command_length"),
        CheckConstraint("revision > 0", name="ck_orch_evidence_packs_revision"),
        CheckConstraint("evidence_count >= 0", name="ck_orch_evidence_packs_count"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_evidence_packs_digest"),
        ForeignKeyConstraint(["research_job_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.research_jobs.id", f"{ORCHESTRATION_SCHEMA}.research_jobs.project_id"], name="fk_orch_evidence_packs_job", ondelete="RESTRICT"),
        ForeignKeyConstraint(["conflict_adjudication_revision_id", "project_id", "research_job_id"], [f"{ORCHESTRATION_SCHEMA}.evidence_conflict_adjudication_revisions.id", f"{ORCHESTRATION_SCHEMA}.evidence_conflict_adjudication_revisions.project_id", f"{ORCHESTRATION_SCHEMA}.evidence_conflict_adjudication_revisions.research_job_id"], name="fk_orch_evidence_packs_adjudication", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    conflict_adjudication_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    adjudicator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    conflict_metadata: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    publishable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    insufficiency_reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvidencePackMembershipRecord(OrchestrationBase):
    __tablename__ = "evidence_pack_memberships"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_evidence_memberships_scope"),
        UniqueConstraint("evidence_pack_revision_id", "project_id", "research_job_id", "ordinal", name="uq_orch_evidence_memberships_ordinal"),
        UniqueConstraint("evidence_pack_revision_id", "project_id", "research_job_id", "evidence_claim_id", name="uq_orch_evidence_memberships_claim"),
        CheckConstraint("ordinal > 0", name="ck_orch_evidence_memberships_ordinal"),
        ForeignKeyConstraint(["evidence_pack_revision_id", "project_id", "research_job_id"], [f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.id", f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.project_id", f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.research_job_id"], name="fk_orch_evidence_memberships_pack", ondelete="RESTRICT"),
        ForeignKeyConstraint(["evidence_claim_id", "project_id", "research_job_id"], [f"{ORCHESTRATION_SCHEMA}.evidence_claims.id", f"{ORCHESTRATION_SCHEMA}.evidence_claims.project_id", f"{ORCHESTRATION_SCHEMA}.evidence_claims.research_job_id"], name="fk_orch_evidence_memberships_claim", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    research_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_pack_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResonanceDirectionRevisionRecord(OrchestrationBase):
    __tablename__ = "resonance_direction_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_resonance_directions_scope"),
        UniqueConstraint("project_id", "direction_key", "revision", name="uq_orch_resonance_directions_revision"),
        UniqueConstraint("project_id", "command_idempotency_key", "publication_ordinal", name="uq_orch_resonance_directions_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_resonance_directions_command_length"),
        CheckConstraint("revision > 0 AND publication_ordinal > 0", name="ck_orch_resonance_directions_ordinals"),
        CheckConstraint("evidence_count > 0", name="ck_orch_resonance_directions_evidence_count"),
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_orch_resonance_directions_score"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_resonance_directions_digest"),
        ForeignKeyConstraint(["evidence_pack_revision_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.id", f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.project_id"], name="fk_orch_resonance_directions_pack", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_pack_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    direction_key: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    publication_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_version: Mapped[str] = mapped_column(String(100), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TrialMethodologyRevisionRecord(OrchestrationBase):
    __tablename__ = "trial_methodology_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_trial_methodologies_scope"),
        UniqueConstraint("project_id", "methodology_key", "revision", name="uq_orch_trial_methodologies_revision"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_trial_methodologies_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_trial_methodologies_command_length"),
        CheckConstraint("revision > 0", name="ck_orch_trial_methodologies_revision"),
        CheckConstraint(SHA256_CHECK.format(column="prompt_digest"), name="ck_orch_trial_methodologies_prompt_digest"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_trial_methodologies_digest"),
        ForeignKeyConstraint(["project_id"], [f"{ORCHESTRATION_SCHEMA}.projects.id"], name="fk_orch_trial_methodologies_project", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    methodology_key: Mapped[str] = mapped_column(String(160), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TrialScriptRevisionRecord(OrchestrationBase):
    __tablename__ = "trial_script_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_trial_scripts_scope"),
        UniqueConstraint("project_id", "book_id", "revision", name="uq_orch_trial_scripts_revision"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_trial_scripts_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_trial_scripts_command_length"),
        CheckConstraint("revision > 0", name="ck_orch_trial_scripts_revision"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_trial_scripts_digest"),
        CheckConstraint(
            SHA256_CHECK.format(column="source_safety_decision_digest"),
            name="ck_orch_trial_scripts_source_safety_digest",
        ),
        CheckConstraint(
            "(source_trial_script_revision_id IS NULL AND "
            "source_safety_decision_digest IS NULL) OR "
            "(source_trial_script_revision_id IS NOT NULL AND "
            "source_safety_decision_digest IS NOT NULL)",
            name="ck_orch_trial_scripts_source_pair",
        ),
        CheckConstraint(
            "source_trial_script_revision_id IS NULL OR "
            "source_trial_script_revision_id <> id",
            name="ck_orch_trial_scripts_source_not_self",
        ),
        ForeignKeyConstraint(["book_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.books.id", f"{ORCHESTRATION_SCHEMA}.books.project_id"], name="fk_orch_trial_scripts_book", ondelete="RESTRICT"),
        ForeignKeyConstraint(["evidence_pack_revision_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.id", f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.project_id"], name="fk_orch_trial_scripts_pack", ondelete="RESTRICT"),
        ForeignKeyConstraint(["methodology_revision_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.trial_methodology_revisions.id", f"{ORCHESTRATION_SCHEMA}.trial_methodology_revisions.project_id"], name="fk_orch_trial_scripts_methodology", ondelete="RESTRICT"),
        ForeignKeyConstraint(["resonance_direction_revision_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.resonance_direction_revisions.id", f"{ORCHESTRATION_SCHEMA}.resonance_direction_revisions.project_id"], name="fk_orch_trial_scripts_direction", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["source_trial_script_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.trial_script_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.trial_script_revisions.project_id",
            ],
            name="fk_orch_trial_scripts_source",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    book_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_pack_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    resonance_direction_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    methodology_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    validator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_trial_script_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    source_safety_decision_digest: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VoicePresetRevisionRecord(OrchestrationBase):
    __tablename__ = "voice_preset_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_voice_presets_scope"),
        UniqueConstraint("project_id", "preset_key", "revision", name="uq_orch_voice_presets_revision"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_voice_presets_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_voice_presets_command_length"),
        CheckConstraint("revision > 0", name="ck_orch_voice_presets_revision"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_voice_presets_digest"),
        CheckConstraint(SHA256_CHECK.format(column="model_digest"), name="ck_orch_voice_presets_model_digest"),
        CheckConstraint(SHA256_CHECK.format(column="instruction_digest"), name="ck_orch_voice_presets_instruction_digest"),
        CheckConstraint(SHA256_CHECK.format(column="discovery_schema_digest"), name="ck_orch_voice_presets_discovery_schema_digest"),
        CheckConstraint("provider = 'qwen3-tts-custom-voice-mcp'", name="ck_orch_voice_presets_provider"),
        CheckConstraint("model_id = 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice'", name="ck_orch_voice_presets_model"),
        CheckConstraint("language = 'Chinese'", name="ck_orch_voice_presets_language"),
        CheckConstraint("discovery_tool_name = 'qwen_tts.custom_voice'", name="ck_orch_voice_presets_tool"),
        CheckConstraint("discovery_schema_digest = '99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa'", name="ck_orch_voice_presets_schema"),
        CheckConstraint("speaker IN ('Serena', 'Uncle_Fu', 'Vivian', 'Dylan')", name="ck_orch_voice_presets_speaker"),
        ForeignKeyConstraint(["project_id"], [f"{ORCHESTRATION_SCHEMA}.projects.id"], name="fk_orch_voice_presets_project", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    preset_key: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    speaker: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(100), nullable=False)
    instruction_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    discovery_service_version: Mapped[str] = mapped_column(String(100), nullable=False)
    discovery_tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    discovery_schema_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TTSTakeRecord(OrchestrationBase):
    __tablename__ = "tts_takes"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_tts_takes_scope"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_tts_takes_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_tts_takes_command_length"),
        CheckConstraint(SHA256_CHECK.format(column="audio_digest"), name="ck_orch_tts_takes_audio_digest"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_tts_takes_digest"),
        CheckConstraint(SHA256_CHECK.format(column="actual_schema_digest"), name="ck_orch_tts_takes_schema_digest"),
        CheckConstraint(SHA256_CHECK.format(column="instruction_digest"), name="ck_orch_tts_takes_instruction_digest"),
        CheckConstraint("audio_byte_size > 44", name="ck_orch_tts_takes_audio_size"),
        CheckConstraint("sample_rate_hz = 24000", name="ck_orch_tts_takes_sample_rate"),
        CheckConstraint("channels = 1", name="ck_orch_tts_takes_channels"),
        CheckConstraint("pcm_sample_width_bytes = 2", name="ck_orch_tts_takes_pcm_width"),
        CheckConstraint("duration_seconds > 0 AND duration_seconds <= 300", name="ck_orch_tts_takes_duration"),
        CheckConstraint("peak_amplitude >= 0 AND peak_amplitude <= 1", name="ck_orch_tts_takes_peak"),
        CheckConstraint("clipping_ratio >= 0 AND clipping_ratio <= 1", name="ck_orch_tts_takes_clipping"),
        CheckConstraint("silence_ratio >= 0 AND silence_ratio <= 1", name="ck_orch_tts_takes_silence"),
        CheckConstraint("leading_silence_seconds >= 0 AND trailing_silence_seconds >= 0", name="ck_orch_tts_takes_edge_silence"),
        CheckConstraint("qc_accepted", name="ck_orch_tts_takes_qc_accepted"),
        CheckConstraint("retry_count BETWEEN 0 AND 3", name="ck_orch_tts_takes_retry_count"),
        CheckConstraint("NOT lipsync_required", name="ck_orch_tts_takes_no_lipsync"),
        CheckConstraint("requested_provider = 'qwen3-tts-custom-voice-mcp' AND actual_provider = 'qwen3-tts-custom-voice-mcp'", name="ck_orch_tts_takes_provider"),
        CheckConstraint("requested_model_id = 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice' AND actual_model_id = 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice'", name="ck_orch_tts_takes_model"),
        CheckConstraint("actual_tool_name = 'qwen_tts.custom_voice'", name="ck_orch_tts_takes_tool"),
        CheckConstraint("actual_schema_digest = '99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa'", name="ck_orch_tts_takes_schema"),
        CheckConstraint("speaker IN ('Serena', 'Uncle_Fu', 'Vivian', 'Dylan')", name="ck_orch_tts_takes_speaker"),
        CheckConstraint("language = 'Chinese'", name="ck_orch_tts_takes_language"),
        CheckConstraint("error_classification IS NULL", name="ck_orch_tts_takes_success_error"),
        ForeignKeyConstraint(["trial_script_revision_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.trial_script_revisions.id", f"{ORCHESTRATION_SCHEMA}.trial_script_revisions.project_id"], name="fk_orch_tts_takes_script", ondelete="RESTRICT"),
        ForeignKeyConstraint(["voice_preset_revision_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.voice_preset_revisions.id", f"{ORCHESTRATION_SCHEMA}.voice_preset_revisions.project_id"], name="fk_orch_tts_takes_preset", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    trial_script_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    voice_preset_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    cue_key: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actual_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    actual_model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actual_service_version: Mapped[str] = mapped_column(String(100), nullable=False)
    actual_tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    actual_schema_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    speaker: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[str] = mapped_column(String(100), nullable=False)
    instruction_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    audio_artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    audio_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    audio_byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sample_rate_hz: Mapped[int] = mapped_column(Integer, nullable=False)
    channels: Mapped[int] = mapped_column(Integer, nullable=False)
    pcm_sample_width_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    peak_amplitude: Mapped[float] = mapped_column(Float, nullable=False)
    clipping_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    silence_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    leading_silence_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    trailing_silence_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    qc_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_classification: Mapped[str | None] = mapped_column(String(100))
    lipsync_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VideoJobProjectionRecord(OrchestrationBase):
    __tablename__ = "video_job_projections"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_video_jobs_scope"),
        UniqueConstraint("project_id", "external_job_id", name="uq_orch_video_jobs_external"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_video_jobs_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_video_jobs_command_length"),
        ForeignKeyConstraint(["book_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.books.id", f"{ORCHESTRATION_SCHEMA}.books.project_id"], name="fk_orch_video_jobs_book", ondelete="RESTRICT"),
        ForeignKeyConstraint(["trial_script_revision_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.trial_script_revisions.id", f"{ORCHESTRATION_SCHEMA}.trial_script_revisions.project_id"], name="fk_orch_video_jobs_script", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    book_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    trial_script_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    external_job_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ReaderFeedbackRecord(OrchestrationBase):
    __tablename__ = "reader_feedback"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_reader_feedback_scope"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_reader_feedback_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_reader_feedback_command_length"),
        CheckConstraint(SHA256_CHECK.format(column="digest"), name="ck_orch_reader_feedback_digest"),
        ForeignKeyConstraint(["book_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.books.id", f"{ORCHESTRATION_SCHEMA}.books.project_id"], name="fk_orch_reader_feedback_book", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    book_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VideoBookBindingRecord(OrchestrationBase):
    """Append-only association; one book may truthfully own many videos."""

    __tablename__ = "video_book_bindings"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_orch_video_book_bindings_scope"),
        UniqueConstraint("project_id", "video_id", "book_id", name="uq_orch_video_book_bindings_pair"),
        UniqueConstraint("project_id", "command_idempotency_key", name="uq_orch_video_book_bindings_command"),
        CheckConstraint("length(command_idempotency_key) BETWEEN 1 AND 255", name="ck_orch_video_book_bindings_command_length"),
        ForeignKeyConstraint(["book_id", "project_id"], [f"{ORCHESTRATION_SCHEMA}.books.id", f"{ORCHESTRATION_SCHEMA}.books.project_id"], name="fk_orch_video_book_bindings_book", ondelete="RESTRICT"),
        {"schema": ORCHESTRATION_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    video_id: Mapped[str] = mapped_column(String(200), nullable=False)
    book_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProjectCreativeIRRevisionRecord(OrchestrationBase):
    """Immutable ProjectCreativeIRV1 authority bound to its Shidu sources."""

    __tablename__ = "project_creative_ir_revisions"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_project_creative_ir_scope"
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "revision_digest",
            name="uq_orch_project_creative_ir_identity",
        ),
        UniqueConstraint(
            "project_id",
            "revision_digest",
            name="uq_orch_project_creative_ir_digest",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_project_creative_ir_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_project_creative_ir_command_length",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="revision_digest"),
            name="ck_orch_project_creative_ir_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_project_creative_ir_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["evidence_pack_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.evidence_pack_revisions.project_id",
            ],
            name="fk_orch_project_creative_ir_evidence_pack",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["trial_script_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.trial_script_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.trial_script_revisions.project_id",
            ],
            name="fk_orch_project_creative_ir_trial_script",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_project_creative_ir_project_created",
            "project_id",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_pack_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    trial_script_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    revision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CharacterSourceAssetRecord(OrchestrationBase):
    """Verified historical portrait source backed by a project artifact."""

    __tablename__ = "character_source_assets"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_character_source_assets_scope"
        ),
        UniqueConstraint(
            "project_id",
            "artifact_id",
            name="uq_orch_character_source_assets_artifact",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_character_source_assets_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_character_source_assets_command_length",
        ),
        CheckConstraint(
            "verified AND historical AND NOT ai_derived",
            name="ck_orch_character_source_assets_provenance",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="content_digest"),
            name="ck_orch_character_source_assets_digest",
        ),
        CheckConstraint(
            "length(uploaded_by) BETWEEN 1 AND 160",
            name="ck_orch_character_source_assets_uploader",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_character_source_assets_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_character_source_assets_artifact",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    historical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ai_derived: Mapped[bool] = mapped_column(Boolean, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(160), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CharacterReferenceSetRevisionRecord(OrchestrationBase):
    """Immutable CharacterReferenceSetV1 revision and cross-view QC."""

    __tablename__ = "character_reference_set_revisions"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_character_reference_sets_scope",
        ),
        UniqueConstraint(
            "project_id",
            "reference_set_id",
            "reference_set_digest",
            name="uq_orch_character_reference_sets_revision",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_character_reference_sets_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_character_reference_sets_command_length",
        ),
        CheckConstraint(
            "state IN ('draft', 'generating', 'qc_pending', "
            "'needs_manual_source_fix', 'frozen')",
            name="ck_orch_character_reference_sets_state",
        ),
        CheckConstraint(
            "model_family = 'flux2-dev' AND "
            "model_revision = 'flux2-dev-fp8mixed.v1'",
            name="ck_orch_character_reference_sets_model",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="workflow_digest"),
            name="ck_orch_character_reference_sets_workflow_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="reference_set_digest"),
            name="ck_orch_character_reference_sets_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_character_reference_sets_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_asset_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.character_source_assets.id",
                f"{ORCHESTRATION_SCHEMA}.character_source_assets.project_id",
            ],
            name="fk_orch_character_reference_sets_source",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_character_reference_sets_character",
            "project_id",
            "character_id",
            "age_stage",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reference_set_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    character_id: Mapped[str] = mapped_column(String(160), nullable=False)
    age_stage: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    model_family: Mapped[str] = mapped_column(String(64), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reference_set_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CharacterReferenceViewAssetRecord(OrchestrationBase):
    """One immutable generated FLUX reference view and its artifact binding."""

    __tablename__ = "character_reference_view_assets"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_character_reference_views_scope",
        ),
        UniqueConstraint(
            "reference_set_revision_id",
            "project_id",
            "view_name",
            name="uq_orch_character_reference_views_name",
        ),
        UniqueConstraint(
            "project_id",
            "artifact_id",
            name="uq_orch_character_reference_views_artifact",
        ),
        CheckConstraint(
            "view_name IN ('front', 'three_quarter_left', 'profile_left')",
            name="ck_orch_character_reference_views_name",
        ),
        CheckConstraint(
            "attempt_ordinal BETWEEN 0 AND 1",
            name="ck_orch_character_reference_views_attempt",
        ),
        CheckConstraint(
            "ai_derived AND NOT historical AND identity_control",
            name="ck_orch_character_reference_views_provenance",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="image_digest"),
            name="ck_orch_character_reference_views_digest",
        ),
        ForeignKeyConstraint(
            ["reference_set_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.character_reference_set_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.character_reference_set_revisions.project_id",
            ],
            name="fk_orch_character_reference_views_set",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_character_reference_views_artifact",
            ondelete="RESTRICT",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reference_set_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    view_name: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    image_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_derived: Mapped[bool] = mapped_column(Boolean, nullable=False)
    historical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    identity_control: Mapped[bool] = mapped_column(Boolean, nullable=False)
    single_view_qc_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EpisodeGenerationIRRevisionRecord(OrchestrationBase):
    """Immutable EpisodeGenerationIRV1 authority."""

    __tablename__ = "episode_generation_ir_revisions"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_episode_generation_ir_scope"
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "revision_digest",
            name="uq_orch_episode_generation_ir_identity",
        ),
        UniqueConstraint(
            "project_id",
            "revision_digest",
            name="uq_orch_episode_generation_ir_digest",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_episode_generation_ir_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_episode_generation_ir_command_length",
        ),
        CheckConstraint(
            "model_family = 'minimax-h3'",
            name="ck_orch_episode_generation_ir_model",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="project_ir_revision_digest"),
            name="ck_orch_episode_generation_ir_project_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="duration_allocation_digest"),
            name="ck_orch_episode_generation_ir_duration_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="revision_digest"),
            name="ck_orch_episode_generation_ir_digest",
        ),
        ForeignKeyConstraint(
            ["project_id"],
            [f"{ORCHESTRATION_SCHEMA}.projects.id"],
            name="fk_orch_episode_generation_ir_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_ir_id", "project_id", "project_ir_revision_digest"],
            [
                f"{ORCHESTRATION_SCHEMA}.project_creative_ir_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.project_creative_ir_revisions.project_id",
                f"{ORCHESTRATION_SCHEMA}.project_creative_ir_revisions.revision_digest",
            ],
            name="fk_orch_episode_generation_ir_project_ir",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_episode_generation_ir_project_created",
            "project_id",
            "created_at",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_ir_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_ir_revision_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    model_family: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_allocation_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    revision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class H3SequenceRevisionRecord(OrchestrationBase):
    """Frozen logical H3 sequence; mutable execution state lives elsewhere."""

    __tablename__ = "h3_sequence_revisions"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_h3_sequence_revisions_scope"
        ),
        UniqueConstraint(
            "episode_revision_id",
            "project_id",
            "sequence_id",
            name="uq_orch_h3_sequence_revisions_sequence",
        ),
        UniqueConstraint(
            "episode_revision_id",
            "project_id",
            "ordinal",
            name="uq_orch_h3_sequence_revisions_ordinal",
        ),
        UniqueConstraint(
            "project_id",
            "selection_head_id",
            name="uq_orch_h3_sequence_revisions_selection",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_h3_sequence_revisions_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_h3_sequence_revisions_command_length",
        ),
        CheckConstraint(
            "ordinal > 0", name="ck_orch_h3_sequence_revisions_ordinal"
        ),
        CheckConstraint(
            "mode = 'ref2va' AND fps = 24",
            name="ck_orch_h3_sequence_revisions_mode",
        ),
        CheckConstraint(
            "frame_count BETWEEN 73 AND 362 AND frame_count % 17 = 5",
            name="ck_orch_h3_sequence_revisions_frame_grid",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="plan_digest"),
            name="ck_orch_h3_sequence_revisions_plan_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="prompt_digest"),
            name="ck_orch_h3_sequence_revisions_prompt_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="workflow_digest"),
            name="ck_orch_h3_sequence_revisions_workflow_digest",
        ),
        ForeignKeyConstraint(
            ["episode_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.episode_generation_ir_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.episode_generation_ir_revisions.project_id",
            ],
            name="fk_orch_h3_sequence_revisions_episode",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["selection_head_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.selection_heads.id",
                f"{ORCHESTRATION_SCHEMA}.selection_heads.project_id",
            ],
            name="fk_orch_h3_sequence_revisions_selection",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_h3_sequence_revisions_episode",
            "project_id",
            "episode_revision_id",
            "ordinal",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    episode_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    sequence_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fps: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    plan_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    selection_head_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class H3RuntimeAttemptRecord(OrchestrationBase):
    """Final H3 attempt lineage bound to generic durable runtime facts."""

    __tablename__ = "h3_runtime_attempts"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", name="uq_orch_h3_runtime_attempts_scope"
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "sequence_revision_id",
            name="uq_orch_h3_runtime_attempts_sequence_scope",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "sequence_revision_id",
            "attempt_ordinal",
            name="uq_orch_h3_runtime_attempts_repair_scope",
        ),
        UniqueConstraint(
            "sequence_revision_id",
            "project_id",
            "attempt_ordinal",
            name="uq_orch_h3_runtime_attempts_ordinal",
        ),
        UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_h3_runtime_attempts_command",
        ),
        CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_h3_runtime_attempts_command_length",
        ),
        CheckConstraint(
            "attempt_ordinal BETWEEN 0 AND 1",
            name="ck_orch_h3_runtime_attempts_ordinal",
        ),
        CheckConstraint(
            "(attempt_ordinal = 0 AND repair_of_attempt_id IS NULL "
            "AND repair_of_attempt_ordinal IS NULL "
            "AND json_array_length(repair_trigger_codes) = 0) OR "
            "(attempt_ordinal = 1 AND repair_of_attempt_id IS NOT NULL "
            "AND repair_of_attempt_ordinal = 0 "
            "AND json_array_length(repair_trigger_codes) > 0)",
            name="ck_orch_h3_runtime_attempts_repair",
        ),
        CheckConstraint(
            "length(trim(qc_gate_key)) > 0",
            name="ck_orch_h3_runtime_attempts_qc_gate",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="artifact_digest"),
            name="ck_orch_h3_runtime_attempts_artifact_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="prompt_digest"),
            name="ck_orch_h3_runtime_attempts_prompt_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="workflow_digest"),
            name="ck_orch_h3_runtime_attempts_workflow_digest",
        ),
        CheckConstraint(
            SHA256_CHECK.format(column="source_lineage_digest"),
            name="ck_orch_h3_runtime_attempts_lineage_digest",
        ),
        ForeignKeyConstraint(
            ["sequence_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.h3_sequence_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.h3_sequence_revisions.project_id",
            ],
            name="fk_orch_h3_runtime_attempts_sequence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["operation_attempt_id", "operation_run_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_h3_runtime_attempts_operation_attempt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "artifact_id",
                "project_id",
                "operation_run_id",
                "operation_attempt_id",
                "artifact_digest",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.artifacts.id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.project_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.operation_run_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.operation_attempt_id",
                f"{ORCHESTRATION_SCHEMA}.artifacts.content_digest",
            ],
            name="fk_orch_h3_runtime_attempts_artifact",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "qc_evaluation_id",
                "project_id",
                "artifact_id",
                "artifact_digest",
                "qc_gate_key",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.id",
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.project_id",
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.artifact_id",
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.artifact_digest",
                f"{ORCHESTRATION_SCHEMA}.qc_evaluation_facts.gate_key",
            ],
            name="fk_orch_h3_runtime_attempts_qc",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "repair_of_attempt_id",
                "project_id",
                "sequence_revision_id",
                "repair_of_attempt_ordinal",
            ],
            [
                f"{ORCHESTRATION_SCHEMA}.h3_runtime_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.h3_runtime_attempts.project_id",
                f"{ORCHESTRATION_SCHEMA}.h3_runtime_attempts.sequence_revision_id",
                f"{ORCHESTRATION_SCHEMA}.h3_runtime_attempts.attempt_ordinal",
            ],
            name="fk_orch_h3_runtime_attempts_repair_parent_ordinal",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_h3_runtime_attempts_sequence",
            "project_id",
            "sequence_revision_id",
            "attempt_ordinal",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    attempt_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    operation_attempt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    qc_evaluation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    qc_gate_key: Mapped[str] = mapped_column(String(200), nullable=False)
    repair_of_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    repair_of_attempt_ordinal: Mapped[int | None] = mapped_column(Integer)
    repair_trigger_codes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    prompt_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_lineage_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    source_lineage_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VideoJobSequenceProjectionRecord(OrchestrationBase):
    """Mutable product projection; never used as H3 lineage authority."""

    __tablename__ = "video_job_sequence_projections"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_video_job_sequence_projections_scope",
        ),
        UniqueConstraint(
            "video_job_projection_id",
            "project_id",
            "sequence_revision_id",
            name="uq_orch_video_job_sequence_projections_sequence",
        ),
        UniqueConstraint(
            "video_job_projection_id",
            "project_id",
            "ordinal",
            name="uq_orch_video_job_sequence_projections_ordinal",
        ),
        CheckConstraint(
            "ordinal > 0",
            name="ck_orch_video_job_sequence_projections_ordinal",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_orch_video_job_sequence_projections_version",
        ),
        CheckConstraint(
            "status IN ('planned', 'generating_initial', 'qc_initial', "
            "'repair_planned', 'generating_repair', 'qc_repair', "
            "'selecting_best', 'selected_clean', "
            "'selected_with_qc_exception', 'ready_for_assembly', "
            "'assembled', 'delivered', 'runtime_error')",
            name="ck_orch_video_job_sequence_projections_status",
        ),
        ForeignKeyConstraint(
            ["video_job_projection_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.video_job_projections.id",
                f"{ORCHESTRATION_SCHEMA}.video_job_projections.project_id",
            ],
            name="fk_orch_video_job_sequence_projections_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["sequence_revision_id", "project_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.h3_sequence_revisions.id",
                f"{ORCHESTRATION_SCHEMA}.h3_sequence_revisions.project_id",
            ],
            name="fk_orch_video_job_sequence_projections_sequence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["selected_attempt_id", "project_id", "sequence_revision_id"],
            [
                f"{ORCHESTRATION_SCHEMA}.h3_runtime_attempts.id",
                f"{ORCHESTRATION_SCHEMA}.h3_runtime_attempts.project_id",
                f"{ORCHESTRATION_SCHEMA}.h3_runtime_attempts.sequence_revision_id",
            ],
            name="fk_orch_video_job_sequence_projections_attempt",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_orch_video_job_sequence_projections_job",
            "project_id",
            "video_job_projection_id",
            "ordinal",
        ),
        {"schema": ORCHESTRATION_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    video_job_projection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    sequence_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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
