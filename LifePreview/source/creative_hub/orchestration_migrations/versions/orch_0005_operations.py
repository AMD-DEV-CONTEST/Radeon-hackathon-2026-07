"""Add operation runs, immutable attempts, state projections, and events.

Revision ID: orch_0005
Revises: orch_0004
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0005"
down_revision = "orch_0004"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.create_table(
        "operation_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("node_key", sa.String(200), nullable=False),
        sa.Column("op_type", sa.String(160), nullable=False),
        sa.Column("op_version", sa.String(64), nullable=False),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("operation_input_digest", sa.String(64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="CREATED",
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("accepted_attempt_id", sa.Uuid(as_uuid=True)),
        sa.Column("accepted_attempt_number", sa.Integer()),
        sa.Column("parent_operation_run_id", sa.Uuid(as_uuid=True)),
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
        sa.CheckConstraint(
            "status IN ('CREATED', 'QUEUED', 'LEASED', 'RUNNING', "
            "'MATERIALIZING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_orch_operation_runs_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_operation_runs_version"
        ),
        sa.CheckConstraint(
            "length(operation_input_digest) = 64",
            name="ck_orch_operation_runs_input_digest",
        ),
        sa.CheckConstraint(
            "(accepted_attempt_id IS NULL "
            "AND accepted_attempt_number IS NULL) "
            "OR (accepted_attempt_id IS NOT NULL "
            "AND accepted_attempt_number IS NOT NULL)",
            name="ck_orch_operation_runs_accepted_pair",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{SCHEMA}.workflow_runs.id",
                f"{SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_operation_runs_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_operation_run_id", "project_id"],
            [
                f"{SCHEMA}.operation_runs.id",
                f"{SCHEMA}.operation_runs.project_id",
            ],
            name="fk_orch_operation_runs_parent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_operation_runs_command",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_operation_runs_id_project"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_operation_runs_workflow_status",
        "operation_runs",
        ["workflow_run_id", "status", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_operation_runs_project_type",
        "operation_runs",
        ["project_id", "op_type", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "operation_attempts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.String(160), nullable=False),
        sa.Column("implementation_digest", sa.String(64), nullable=False),
        sa.Column("provider_task_id", sa.String(255)),
        sa.Column("submission_nonce", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_orch_operation_attempts_number",
        ),
        sa.CheckConstraint(
            "fencing_token >= 0",
            name="ck_orch_operation_attempts_fencing",
        ),
        sa.CheckConstraint(
            "length(implementation_digest) = 64",
            name="ck_orch_operation_attempts_implementation",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_orch_operation_attempts_request_digest",
        ),
        sa.ForeignKeyConstraint(
            ["operation_run_id", "project_id"],
            [
                f"{SCHEMA}.operation_runs.id",
                f"{SCHEMA}.operation_runs.project_id",
            ],
            name="fk_orch_operation_attempts_run",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "operation_run_id",
            "attempt_number",
            name="uq_orch_operation_attempts_number",
        ),
        sa.UniqueConstraint(
            "id",
            "operation_run_id",
            "attempt_number",
            "project_id",
            name="uq_orch_operation_attempts_accept_scope",
        ),
        sa.UniqueConstraint(
            "id",
            "operation_run_id",
            "project_id",
            name="uq_orch_operation_attempts_run_scope",
        ),
        sa.UniqueConstraint(
            "project_id",
            "submission_nonce",
            name="uq_orch_operation_attempts_nonce",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_operation_attempts_run_created",
        "operation_attempts",
        ["operation_run_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_operation_attempts_provider_task",
        "operation_attempts",
        ["provider_task_id"],
        schema=SCHEMA,
    )

    op.create_foreign_key(
        "fk_orch_operation_runs_accepted_attempt",
        "operation_runs",
        "operation_attempts",
        [
            "accepted_attempt_id",
            "id",
            "accepted_attempt_number",
            "project_id",
        ],
        ["id", "operation_run_id", "attempt_number", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "operation_attempt_states",
        sa.Column(
            "attempt_id", sa.Uuid(as_uuid=True), primary_key=True
        ),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="PREPARED",
        ),
        sa.Column(
            "stage",
            sa.String(64),
            nullable=False,
            server_default="PREPARED",
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("provider_state", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("cost_micros", sa.BigInteger()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('PREPARED', 'SUBMITTED', 'OUTCOME_UNKNOWN', "
            "'OBSERVED_TERMINAL', 'MATERIALIZING', 'SUCCEEDED', 'FAILED', "
            "'CANCELLED', 'STALE')",
            name="ck_orch_attempt_states_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_attempt_states_version"
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_orch_attempt_states_duration",
        ),
        sa.CheckConstraint(
            "cost_micros IS NULL OR cost_micros >= 0",
            name="ck_orch_attempt_states_cost",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "operation_run_id", "project_id"],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_attempt_states_attempt",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_attempt_states_project_status",
        "operation_attempt_states",
        ["project_id", "status", "updated_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "operation_attempt_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("data_digest", sa.String(64), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "sequence > 0", name="ck_orch_attempt_events_sequence"
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_attempt_events_version"
        ),
        sa.CheckConstraint(
            "length(data_digest) = 64",
            name="ck_orch_attempt_events_digest",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "operation_run_id", "project_id"],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_attempt_events_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "attempt_id",
            "sequence",
            name="uq_orch_attempt_events_sequence",
        ),
        sa.UniqueConstraint(
            "attempt_id",
            "state_version",
            name="uq_orch_attempt_events_state_version",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_attempt_events_attempt_sequence",
        "operation_attempt_events",
        ["attempt_id", "sequence"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_attempt_events_project_occurred",
        "operation_attempt_events",
        ["project_id", "occurred_at"],
        schema=SCHEMA,
    )

    for table in ("operation_attempts", "operation_attempt_events"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON orchestration.{table}
            FOR EACH ROW
            EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
            """
        )
    op.execute(
        "REVOKE ALL ON TABLE orchestration.operation_runs, "
        "orchestration.operation_attempts, "
        "orchestration.operation_attempt_states, "
        "orchestration.operation_attempt_events FROM PUBLIC"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname = 'creative_orchestrator_app'
            ) THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON orchestration.operation_runs,
                       orchestration.operation_attempt_states
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON orchestration.operation_attempts,
                       orchestration.operation_attempt_events
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
            "SELECT 1 FROM orchestration.operation_attempt_events "
            "UNION ALL SELECT 1 FROM orchestration.operation_attempt_states "
            "UNION ALL SELECT 1 FROM orchestration.operation_attempts "
            "UNION ALL SELECT 1 FROM orchestration.operation_runs)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete operation/attempt facts; "
            "set ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after "
            "backup"
        )
    for table in ("operation_attempt_events", "operation_attempts"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable "
            f"ON orchestration.{table}"
        )
    op.drop_constraint(
        "fk_orch_operation_runs_accepted_attempt",
        "operation_runs",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_table("operation_attempt_events", schema=SCHEMA)
    op.drop_table("operation_attempt_states", schema=SCHEMA)
    op.drop_table("operation_attempts", schema=SCHEMA)
    op.drop_table("operation_runs", schema=SCHEMA)
