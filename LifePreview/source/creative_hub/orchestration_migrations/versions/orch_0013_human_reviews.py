"""Add durable human review tasks and in-app notification authority.

Revision ID: orch_0013
Revises: orch_0012
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0013"
down_revision = "orch_0012"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.create_table(
        "human_review_tasks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("gate_key", sa.String(200), nullable=False),
        sa.Column("policy_snapshot_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("artifact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("artifact_digest", sa.String(64), nullable=False),
        sa.Column(
            "artifact_operation_run_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column(
            "artifact_operation_attempt_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        sa.Column("candidate_set", sa.JSON(), nullable=False),
        sa.Column("candidate_set_digest", sa.String(64), nullable=False),
        sa.Column("selection_head_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("expected_selection_version", sa.Integer(), nullable=False),
        sa.Column("creation_reason", sa.Text(), nullable=False),
        sa.Column("remaining_defects", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("decision", sa.String(16)),
        sa.Column("selected_candidate_id", sa.Uuid(as_uuid=True)),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("decided_by_actor", sa.String(200)),
        sa.Column("decided_by_role", sa.String(16)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_human_review_task_scope"
        ),
        sa.UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            "policy_snapshot_id",
            name="uq_orch_human_review_gate",
        ),
        sa.CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_human_review_stage",
        ),
        sa.CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_human_review_gate_key",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'DECIDED', 'CANCELLED')",
            name="ck_orch_human_review_status",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('ACCEPT', 'REWORK', 'REJECT')",
            name="ck_orch_human_review_decision",
        ),
        sa.CheckConstraint(
            "(status = 'OPEN' AND decision IS NULL "
            "AND decided_by_actor IS NULL AND decided_at IS NULL) OR "
            "(status = 'DECIDED' AND decision IS NOT NULL "
            "AND decided_by_actor IS NOT NULL AND decided_at IS NOT NULL) OR "
            "(status = 'CANCELLED' AND decision IS NULL)",
            name="ck_orch_human_review_terminal",
        ),
        sa.CheckConstraint(
            "expected_selection_version >= 0",
            name="ck_orch_human_review_selection_version",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_human_review_state_version",
        ),
        sa.CheckConstraint(
            "length(artifact_digest) = 64",
            name="ck_orch_human_review_artifact_digest",
        ),
        sa.CheckConstraint(
            "length(candidate_set_digest) = 64",
            name="ck_orch_human_review_candidates_digest",
        ),
        sa.CheckConstraint(
            "length(policy_digest) = 64",
            name="ck_orch_human_review_policy_digest",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{SCHEMA}.workflow_runs.id",
                f"{SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_human_review_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_snapshot_id", "project_id", "gate_key"],
            [
                f"{SCHEMA}.qc_gate_policy_snapshots.id",
                f"{SCHEMA}.qc_gate_policy_snapshots.project_id",
                f"{SCHEMA}.qc_gate_policy_snapshots.gate_key",
            ],
            name="fk_orch_human_review_policy",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selection_head_id", "project_id"],
            [
                f"{SCHEMA}.selection_heads.id",
                f"{SCHEMA}.selection_heads.project_id",
            ],
            name="fk_orch_human_review_selection",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "artifact_id",
                "project_id",
                "artifact_operation_run_id",
                "artifact_operation_attempt_id",
                "artifact_digest",
            ],
            [
                f"{SCHEMA}.artifacts.id",
                f"{SCHEMA}.artifacts.project_id",
                f"{SCHEMA}.artifacts.operation_run_id",
                f"{SCHEMA}.artifacts.operation_attempt_id",
                f"{SCHEMA}.artifacts.content_digest",
            ],
            name="fk_orch_human_review_artifact",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_human_review_project_status",
        "human_review_tasks",
        ["project_id", "status", "created_at", "id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_human_review_workflow_stage",
        "human_review_tasks",
        ["workflow_run_id", "stage", "gate_key", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "human_review_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "task_id", "sequence", name="uq_orch_human_review_event_sequence"
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_human_review_event_scope"
        ),
        sa.CheckConstraint(
            "event_type IN ('TASK_OPENED', 'TASK_DECIDED', 'TASK_CANCELLED')",
            name="ck_orch_human_review_event_type",
        ),
        sa.CheckConstraint(
            "sequence > 0", name="ck_orch_human_review_event_sequence"
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "project_id"],
            [
                f"{SCHEMA}.human_review_tasks.id",
                f"{SCHEMA}.human_review_tasks.project_id",
            ],
            name="fk_orch_human_review_event_task",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_human_review_event_task",
        "human_review_events",
        ["task_id", "sequence"],
        schema=SCHEMA,
    )

    op.create_table(
        "human_review_notifications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("recipient_role", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "event_id",
            "recipient_role",
            name="uq_orch_human_review_notification_role",
        ),
        sa.CheckConstraint(
            "recipient_role IN ('owner', 'reviewer')",
            name="ck_orch_human_review_notification_role",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "project_id"],
            [
                f"{SCHEMA}.human_review_events.id",
                f"{SCHEMA}.human_review_events.project_id",
            ],
            name="fk_orch_human_review_notification_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "project_id"],
            [
                f"{SCHEMA}.human_review_tasks.id",
                f"{SCHEMA}.human_review_tasks.project_id",
            ],
            name="fk_orch_human_review_notification_task",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_human_review_notification_inbox",
        "human_review_notifications",
        ["project_id", "recipient_role", "created_at", "id"],
        schema=SCHEMA,
    )

    op.create_table(
        "human_review_outbox",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "topic",
            sa.String(64),
            nullable=False,
            server_default="in_app.human_review",
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "event_id", name="uq_orch_human_review_outbox_event"
        ),
        sa.CheckConstraint(
            "topic = 'in_app.human_review'",
            name="ck_orch_human_review_outbox_topic",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "project_id"],
            [
                f"{SCHEMA}.human_review_events.id",
                f"{SCHEMA}.human_review_events.project_id",
            ],
            name="fk_orch_human_review_outbox_event",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_human_review_outbox_pending",
        "human_review_outbox",
        ["published_at", "created_at"],
        schema=SCHEMA,
    )
    op.execute(
        """
        CREATE TRIGGER trg_human_review_events_immutable
        BEFORE UPDATE OR DELETE ON orchestration.human_review_events
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE "
        "orchestration.human_review_tasks, "
        "orchestration.human_review_events, "
        "orchestration.human_review_notifications, "
        "orchestration.human_review_outbox FROM PUBLIC"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname = 'creative_orchestrator_app'
            ) THEN
                GRANT SELECT, INSERT, UPDATE
                    ON orchestration.human_review_tasks,
                       orchestration.human_review_notifications,
                       orchestration.human_review_outbox
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON orchestration.human_review_events
                    TO creative_orchestrator_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        text(
            "SELECT EXISTS("
            "SELECT 1 FROM orchestration.human_review_tasks "
            "UNION ALL SELECT 1 FROM orchestration.human_review_events "
            "UNION ALL SELECT 1 FROM orchestration.human_review_notifications "
            "UNION ALL SELECT 1 FROM orchestration.human_review_outbox)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete human review authority; "
            "set ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after "
            "backup"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_human_review_events_immutable "
        "ON orchestration.human_review_events"
    )
    op.drop_index(
        "ix_orch_human_review_outbox_pending",
        table_name="human_review_outbox",
        schema=SCHEMA,
    )
    op.drop_table("human_review_outbox", schema=SCHEMA)
    op.drop_index(
        "ix_orch_human_review_notification_inbox",
        table_name="human_review_notifications",
        schema=SCHEMA,
    )
    op.drop_table("human_review_notifications", schema=SCHEMA)
    op.drop_index(
        "ix_orch_human_review_event_task",
        table_name="human_review_events",
        schema=SCHEMA,
    )
    op.drop_table("human_review_events", schema=SCHEMA)
    op.drop_index(
        "ix_orch_human_review_workflow_stage",
        table_name="human_review_tasks",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_orch_human_review_project_status",
        table_name="human_review_tasks",
        schema=SCHEMA,
    )
    op.drop_table("human_review_tasks", schema=SCHEMA)
