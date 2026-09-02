"""Create only the legacy durable Hub jobs and append-only JobEvents.

Revision ID: orch_0001
Revises: None
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from creative_hub.models import ORCHESTRATION_SCHEMA


revision = "orch_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {ORCHESTRATION_SCHEMA}")
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=False),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("lock_owner", sa.String(100)),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "max_attempts", sa.Integer(), nullable=False, server_default="3"
        ),
        sa.Column(
            "lease_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
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
            "status IN ('queued', 'running', 'succeeded', 'failed', "
            "'cancelled', 'needs_human')",
            name="ck_hub_jobs_status",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0",
            name="ck_hub_jobs_lease_generation_nonnegative",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_hub_jobs_attempts",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_hub_jobs_idempotency_key"
        ),
        schema=ORCHESTRATION_SCHEMA,
    )
    op.create_index(
        "ix_hub_jobs_status_created",
        "jobs",
        ["status", "created_at"],
        schema=ORCHESTRATION_SCHEMA,
    )
    op.create_index(
        "ix_hub_jobs_expired_lease",
        "jobs",
        ["status", "lease_expires_at"],
        schema=ORCHESTRATION_SCHEMA,
    )
    op.create_table(
        "job_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "contract_major",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "contract_minor",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("request_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
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
            "sequence > 0", name="ck_hub_job_events_sequence_positive"
        ),
        sa.CheckConstraint(
            "contract_major = 1",
            name="ck_hub_job_events_contract_major_supported",
        ),
        sa.CheckConstraint(
            "contract_minor >= 0",
            name="ck_hub_job_events_contract_minor_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            [f"{ORCHESTRATION_SCHEMA}.jobs.id"],
            name="fk_hub_job_events_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "job_id",
            "sequence",
            name="uq_hub_job_events_job_sequence",
        ),
        schema=ORCHESTRATION_SCHEMA,
    )
    op.create_index(
        "ix_hub_job_events_job_sequence",
        "job_events",
        ["job_id", "sequence"],
        schema=ORCHESTRATION_SCHEMA,
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION orchestration.reject_job_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'job event is immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_job_events_immutable
        BEFORE UPDATE OR DELETE ON orchestration.job_events
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_job_event_mutation()
        """
    )
    op.execute("REVOKE CREATE ON SCHEMA orchestration FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON TABLE orchestration.jobs, "
        "orchestration.job_events FROM PUBLIC"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname = 'creative_orchestrator_app'
            ) THEN
                GRANT USAGE ON SCHEMA orchestration
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON orchestration.jobs
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON orchestration.job_events
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
            "SELECT EXISTS (SELECT 1 FROM orchestration.job_events "
            "UNION ALL SELECT 1 FROM orchestration.jobs)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete durable jobs; set "
            "ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after backup"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_job_events_immutable "
        "ON orchestration.job_events"
    )
    op.drop_table("job_events", schema=ORCHESTRATION_SCHEMA)
    op.drop_table("jobs", schema=ORCHESTRATION_SCHEMA)
    op.execute(
        "DROP FUNCTION IF EXISTS orchestration.reject_job_event_mutation()"
    )
