"""Add durable provider invocation authority and one-shot grants.

Revision ID: orch_0009
Revises: orch_0008
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0009"
down_revision = "orch_0008"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.create_table(
        "provider_invocations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_attempt_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("client_token", sa.String(255), nullable=False),
        sa.Column("submission_nonce", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column(
            "supports_idempotent_submit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "supports_query_by_client_token",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "supports_query_by_task_id",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "phase",
            sa.String(32),
            nullable=False,
            server_default="PREPARED",
        ),
        sa.Column("provider_task_id", sa.String(255)),
        sa.Column("terminal_outcome", sa.String(16)),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("result_digest", sa.String(64)),
        sa.Column("materialized_payload", sa.JSON(), nullable=False),
        sa.Column("materialized_digest", sa.String(64)),
        sa.Column("cost_micros", sa.BigInteger()),
        sa.Column("reservation_id", sa.Uuid(as_uuid=True)),
        sa.Column(
            "human_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("safe_reason_code", sa.String(100)),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("submit_started_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_observed_at", sa.DateTime(timezone=True)),
        sa.Column("materializing_at", sa.DateTime(timezone=True)),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
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
            "phase IN ('PREPARED', 'SUBMITTED', 'OUTCOME_UNKNOWN', "
            "'OBSERVED_TERMINAL', 'MATERIALIZING', 'COMMITTED')",
            name="ck_orch_provider_invocations_phase",
        ),
        sa.CheckConstraint(
            "terminal_outcome IS NULL OR terminal_outcome IN "
            "('SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_orch_provider_invocations_terminal_outcome",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_provider_invocations_version",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name="ck_orch_provider_invocations_request_digest",
        ),
        sa.CheckConstraint(
            "result_digest IS NULL OR length(result_digest) = 64",
            name="ck_orch_provider_invocations_result_digest",
        ),
        sa.CheckConstraint(
            "materialized_digest IS NULL OR length(materialized_digest) = 64",
            name="ck_orch_provider_invocations_materialized_digest",
        ),
        sa.CheckConstraint(
            "cost_micros IS NULL OR cost_micros >= 0",
            name="ck_orch_provider_invocations_cost",
        ),
        sa.CheckConstraint(
            "(human_required = false AND safe_reason_code IS NULL) OR "
            "(human_required = true AND safe_reason_code IS NOT NULL)",
            name="ck_orch_provider_invocations_human_reason",
        ),
        sa.CheckConstraint(
            "(phase NOT IN ('OBSERVED_TERMINAL', 'MATERIALIZING', "
            "'COMMITTED')) OR (terminal_outcome IS NOT NULL AND "
            "result_digest IS NOT NULL AND terminal_observed_at IS NOT NULL)",
            name="ck_orch_provider_invocations_terminal_data",
        ),
        sa.CheckConstraint(
            "(phase <> 'COMMITTED') OR "
            "(terminal_outcome = 'SUCCEEDED' AND committed_at IS NOT NULL "
            "AND materialized_digest IS NOT NULL)",
            name="ck_orch_provider_invocations_committed",
        ),
        sa.ForeignKeyConstraint(
            ["operation_attempt_id", "operation_run_id", "project_id"],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_provider_invocations_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            [f"{SCHEMA}.budget_reservations.id"],
            name="fk_orch_provider_invocations_reservation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "operation_attempt_id",
            "provider",
            name="uq_orch_provider_invocations_attempt_provider",
        ),
        sa.UniqueConstraint(
            "provider",
            "client_token",
            name="uq_orch_provider_invocations_client_token",
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_task_id",
            name="uq_orch_provider_invocations_provider_task",
        ),
        sa.UniqueConstraint(
            "id",
            "operation_attempt_id",
            "operation_run_id",
            "project_id",
            name="uq_orch_provider_invocations_attempt_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_provider_invocations_project_phase",
        "provider_invocations",
        ["project_id", "phase", "updated_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_provider_invocations_reconcile",
        "provider_invocations",
        ["phase", "human_required", "updated_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "provider_invocation_grants",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("invocation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_attempt_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("granted_by_actor", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('SUBMIT', 'RECONCILE', 'MATERIALIZE')",
            name="ck_orch_provider_grants_action",
        ),
        sa.CheckConstraint(
            "length(granted_by_actor) BETWEEN 1 AND 200",
            name="ck_orch_provider_grants_actor",
        ),
        sa.ForeignKeyConstraint(
            [
                "invocation_id",
                "operation_attempt_id",
                "operation_run_id",
                "project_id",
            ],
            [
                f"{SCHEMA}.provider_invocations.id",
                f"{SCHEMA}.provider_invocations.operation_attempt_id",
                f"{SCHEMA}.provider_invocations.operation_run_id",
                f"{SCHEMA}.provider_invocations.project_id",
            ],
            name="fk_orch_provider_grants_invocation",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_provider_grants_invocation_action",
        "provider_invocation_grants",
        ["invocation_id", "action", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "provider_callback_receipts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("invocation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_attempt_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("callback_id", sa.String(255), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(payload_digest) = 64",
            name="ck_orch_provider_callbacks_digest",
        ),
        sa.ForeignKeyConstraint(
            [
                "invocation_id",
                "operation_attempt_id",
                "operation_run_id",
                "project_id",
            ],
            [
                f"{SCHEMA}.provider_invocations.id",
                f"{SCHEMA}.provider_invocations.operation_attempt_id",
                f"{SCHEMA}.provider_invocations.operation_run_id",
                f"{SCHEMA}.provider_invocations.project_id",
            ],
            name="fk_orch_provider_callbacks_invocation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "invocation_id",
            "callback_id",
            name="uq_orch_provider_callbacks_id",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_provider_callbacks_invocation_received",
        "provider_callback_receipts",
        ["invocation_id", "received_at"],
        schema=SCHEMA,
    )

    op.execute(
        """
        CREATE FUNCTION orchestration.enforce_provider_invocation_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id <> OLD.id
               OR NEW.project_id <> OLD.project_id
               OR NEW.operation_run_id <> OLD.operation_run_id
               OR NEW.operation_attempt_id <> OLD.operation_attempt_id
               OR NEW.provider <> OLD.provider
               OR NEW.client_token <> OLD.client_token
               OR NEW.submission_nonce <> OLD.submission_nonce
               OR NEW.request_digest <> OLD.request_digest
               OR NEW.request_payload::text
                  <> OLD.request_payload::text THEN
                RAISE EXCEPTION
                    'provider invocation immutable identity cannot change';
            END IF;
            IF NEW.state_version <> OLD.state_version + 1 THEN
                RAISE EXCEPTION
                    'provider invocation state version must advance by one';
            END IF;
            IF NOT (
                (OLD.phase = 'PREPARED'
                 AND NEW.phase IN (
                    'PREPARED', 'SUBMITTED', 'OUTCOME_UNKNOWN',
                    'OBSERVED_TERMINAL'
                 ))
                OR (OLD.phase = 'SUBMITTED'
                    AND NEW.phase IN (
                        'SUBMITTED', 'OUTCOME_UNKNOWN', 'OBSERVED_TERMINAL'
                    ))
                OR (OLD.phase = 'OUTCOME_UNKNOWN'
                    AND NEW.phase IN (
                        'OUTCOME_UNKNOWN', 'SUBMITTED', 'OBSERVED_TERMINAL'
                    ))
                OR (OLD.phase = 'OBSERVED_TERMINAL'
                    AND NEW.phase = 'MATERIALIZING')
                OR (OLD.phase = 'MATERIALIZING'
                    AND NEW.phase = 'COMMITTED')
            ) THEN
                RAISE EXCEPTION
                    'invalid provider invocation phase transition: % -> %',
                    OLD.phase, NEW.phase;
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_provider_invocations_transition
        BEFORE UPDATE ON orchestration.provider_invocations
        FOR EACH ROW
        EXECUTE FUNCTION
            orchestration.enforce_provider_invocation_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION orchestration.enforce_provider_grant_consumption()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id <> OLD.id
               OR NEW.invocation_id <> OLD.invocation_id
               OR NEW.project_id <> OLD.project_id
               OR NEW.operation_run_id <> OLD.operation_run_id
               OR NEW.operation_attempt_id <> OLD.operation_attempt_id
               OR NEW.action <> OLD.action
               OR NEW.granted_by_actor <> OLD.granted_by_actor
               OR NEW.reason <> OLD.reason
               OR NEW.created_at <> OLD.created_at
               OR OLD.consumed_at IS NOT NULL
               OR NEW.consumed_at IS NULL THEN
                RAISE EXCEPTION
                    'provider grant only permits first consumption';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_provider_grants_consume_once
        BEFORE UPDATE ON orchestration.provider_invocation_grants
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.enforce_provider_grant_consumption()
        """
    )
    for table in (
        "provider_invocation_grants",
        "provider_callback_receipts",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable_delete
            BEFORE DELETE ON orchestration.{table}
            FOR EACH ROW
            EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
            """
        )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "orchestration.enforce_provider_invocation_transition() "
        "FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "orchestration.enforce_provider_grant_consumption() "
        "FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON TABLE orchestration.provider_invocations, "
        "orchestration.provider_invocation_grants, "
        "orchestration.provider_callback_receipts FROM PUBLIC"
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
                    ON orchestration.provider_invocations,
                       orchestration.provider_invocation_grants
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON orchestration.provider_callback_receipts
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
            "SELECT 1 FROM orchestration.provider_callback_receipts "
            "UNION ALL SELECT 1 FROM orchestration.provider_invocation_grants "
            "UNION ALL SELECT 1 FROM orchestration.provider_invocations)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete provider invocation "
            "authority; set ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES "
            "only after backup"
        )
    for table in (
        "provider_callback_receipts",
        "provider_invocation_grants",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable_delete "
            f"ON orchestration.{table}"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_provider_grants_consume_once "
        "ON orchestration.provider_invocation_grants"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.enforce_provider_grant_consumption()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_provider_invocations_transition "
        "ON orchestration.provider_invocations"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.enforce_provider_invocation_transition()"
    )
    op.drop_table("provider_callback_receipts", schema=SCHEMA)
    op.drop_table("provider_invocation_grants", schema=SCHEMA)
    op.drop_table("provider_invocations", schema=SCHEMA)
