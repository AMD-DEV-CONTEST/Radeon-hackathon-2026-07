"""Add the durable product BFF command ledger.

Revision ID: orch_0021
Revises: orch_0020

This migration is expand-only: it introduces the ``product_command_ledger``
table that gives every ``/api/v2`` product write command a durable idempotency
record.  It stores the canonical payload digest and the exact response payload
so identical replays return the stored result and same-key/different-payload
replays raise a deterministic conflict.  No product logic lives here; the
ledger never replaces the durable domain facts written through
``ProductService``.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0021"
down_revision = "orch_0020"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"
SHA256 = "length({column}) = 64"


def upgrade() -> None:
    op.create_table(
        "product_command_ledger",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("scope_key", sa.String(240), nullable=False),
        sa.Column("command_kind", sa.String(64), nullable=False),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("result_digest", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(scope_key) BETWEEN 1 AND 240",
            name="ck_orch_product_command_ledger_scope_key",
        ),
        sa.CheckConstraint(
            "length(command_kind) BETWEEN 1 AND 64",
            name="ck_orch_product_command_ledger_kind",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_product_command_ledger_command_length",
        ),
        sa.CheckConstraint(
            "length(actor_id) BETWEEN 1 AND 100",
            name="ck_orch_product_command_ledger_actor",
        ),
        sa.CheckConstraint(
            SHA256.format(column="payload_digest"),
            name="ck_orch_product_command_ledger_payload_digest",
        ),
        sa.CheckConstraint(
            SHA256.format(column="result_digest"),
            name="ck_orch_product_command_ledger_result_digest",
        ),
        sa.CheckConstraint(
            "status_code BETWEEN 200 AND 299",
            name="ck_orch_product_command_ledger_status",
        ),
        sa.UniqueConstraint(
            "scope_key",
            "command_kind",
            "command_idempotency_key",
            name="uq_orch_product_command_ledger_command",
        ),
        sa.UniqueConstraint(
            "id", "scope_key", name="uq_orch_product_command_ledger_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_product_command_ledger_kind_created",
        "product_command_ledger",
        ["command_kind", "created_at"],
        schema=SCHEMA,
    )
    # The ledger is the BFF idempotency authority: it is append-only.  Mirror
    # the immutable-fact guard used by every other product table so a stray
    # UPDATE or DELETE can never corrupt a replay, and grant the application
    # role only SELECT/INSERT inside the same guarded block used by orch_0020.
    op.execute(
        f"""
        CREATE TRIGGER trg_product_command_ledger_immutable
        BEFORE UPDATE OR DELETE ON orchestration.product_command_ledger
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}'
            ) THEN
                GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE};
                GRANT SELECT, INSERT ON TABLE
                    {SCHEMA}.product_command_ledger TO {ROLE};
                ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA}
                    GRANT SELECT ON TABLES TO {ROLE};
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Expand-only contract: the downgrade is provided so a rehearsal can
    # return to the orch_0020 head, but it must never run against a database
    # that still references product command facts.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_product_command_ledger_immutable "
        "ON orchestration.product_command_ledger"
    )
    op.drop_table("product_command_ledger", schema=SCHEMA)
