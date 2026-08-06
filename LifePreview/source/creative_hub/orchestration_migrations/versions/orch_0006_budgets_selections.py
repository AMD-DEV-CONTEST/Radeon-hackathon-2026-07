"""Add atomic cost accounting and immutable selection revisions.

Revision ID: orch_0006
Revises: orch_0005
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0006"
down_revision = "orch_0005"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.create_table(
        "budget_accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_key", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("limit_micros", sa.BigInteger(), nullable=False),
        sa.Column(
            "reserved_micros",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "settled_micros",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
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
            "length(account_key) BETWEEN 1 AND 100",
            name="ck_orch_budget_accounts_key_length",
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name="ck_orch_budget_accounts_currency",
        ),
        sa.CheckConstraint(
            "limit_micros >= 0 AND reserved_micros >= 0 "
            "AND settled_micros >= 0",
            name="ck_orch_budget_accounts_nonnegative",
        ),
        sa.CheckConstraint(
            "reserved_micros + settled_micros <= limit_micros",
            name="ck_orch_budget_accounts_limit",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_budget_accounts_version"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_budget_accounts_project",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "account_key",
            name="uq_orch_budget_accounts_key",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_budget_accounts_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_budget_accounts_project_updated",
        "budget_accounts",
        ["project_id", "updated_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True)),
        sa.Column("operation_attempt_id", sa.Uuid(as_uuid=True)),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="RESERVED",
        ),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("settled_micros", sa.BigInteger()),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
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
            "status IN ('RESERVED', 'RELEASED', 'SETTLED')",
            name="ck_orch_budget_reservations_status",
        ),
        sa.CheckConstraint(
            "amount_micros > 0",
            name="ck_orch_budget_reservations_amount",
        ),
        sa.CheckConstraint(
            "settled_micros IS NULL OR settled_micros >= 0",
            name="ck_orch_budget_reservations_settled",
        ),
        sa.CheckConstraint(
            "(status = 'SETTLED' AND settled_micros IS NOT NULL) "
            "OR (status <> 'SETTLED' AND settled_micros IS NULL)",
            name="ck_orch_budget_reservations_terminal",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_budget_reservations_version",
        ),
        sa.CheckConstraint(
            "(operation_attempt_id IS NULL AND operation_run_id IS NULL) "
            "OR (operation_attempt_id IS NOT NULL "
            "AND operation_run_id IS NOT NULL)",
            name="ck_orch_budget_reservations_attempt_pair",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "project_id"],
            [
                f"{SCHEMA}.budget_accounts.id",
                f"{SCHEMA}.budget_accounts.project_id",
            ],
            name="fk_orch_budget_reservations_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_attempt_id", "operation_run_id", "project_id"],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_budget_reservations_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_budget_reservations_command",
        ),
        sa.UniqueConstraint(
            "id",
            "account_id",
            "project_id",
            name="uq_orch_budget_reservations_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_budget_reservations_account_status",
        "budget_reservations",
        ["account_id", "status", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_budget_reservations_attempt",
        "budget_reservations",
        ["operation_attempt_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "budget_ledger_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reservation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("entry_type", sa.String(16), nullable=False),
        sa.Column("reserved_delta_micros", sa.BigInteger(), nullable=False),
        sa.Column("settled_delta_micros", sa.BigInteger(), nullable=False),
        sa.Column(
            "reserved_balance_micros", sa.BigInteger(), nullable=False
        ),
        sa.Column(
            "settled_balance_micros", sa.BigInteger(), nullable=False
        ),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("metadata_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "entry_type IN ('RESERVE', 'RELEASE', 'SETTLE')",
            name="ck_orch_budget_ledger_type",
        ),
        sa.CheckConstraint(
            "sequence > 0", name="ck_orch_budget_ledger_sequence"
        ),
        sa.CheckConstraint(
            "reserved_balance_micros >= 0 "
            "AND settled_balance_micros >= 0",
            name="ck_orch_budget_ledger_balances",
        ),
        sa.CheckConstraint(
            "length(metadata_digest) = 64",
            name="ck_orch_budget_ledger_digest",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "project_id"],
            [
                f"{SCHEMA}.budget_accounts.id",
                f"{SCHEMA}.budget_accounts.project_id",
            ],
            name="fk_orch_budget_ledger_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id", "account_id", "project_id"],
            [
                f"{SCHEMA}.budget_reservations.id",
                f"{SCHEMA}.budget_reservations.account_id",
                f"{SCHEMA}.budget_reservations.project_id",
            ],
            name="fk_orch_budget_ledger_reservation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "reservation_id",
            "sequence",
            name="uq_orch_budget_ledger_sequence",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_budget_ledger_command",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_budget_ledger_account_created",
        "budget_ledger_entries",
        ["account_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_budget_ledger_project_created",
        "budget_ledger_entries",
        ["project_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "selection_heads",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("selection_key", sa.String(200), nullable=False),
        sa.Column("current_revision", sa.Integer()),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="OPEN",
        ),
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
            "status IN ('OPEN', 'SEALED')",
            name="ck_orch_selection_heads_status",
        ),
        sa.CheckConstraint(
            "current_revision IS NULL OR current_revision > 0",
            name="ck_orch_selection_heads_revision",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_selection_heads_version"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{SCHEMA}.workflow_runs.id",
                f"{SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_selection_heads_workflow",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "selection_key",
            name="uq_orch_selection_heads_key",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_selection_heads_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_selection_heads_workflow_status",
        "selection_heads",
        ["workflow_run_id", "status"],
        schema=SCHEMA,
    )

    op.create_table(
        "selection_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("selection_head_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column(
            "selected_operation_run_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "selected_attempt_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column("artifact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("artifact_digest", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_selection_revisions_positive"
        ),
        sa.CheckConstraint(
            "decision IN ('SELECTED', 'DEGRADED_ACCEPTED', "
            "'HUMAN_SELECTED', 'REJECTED')",
            name="ck_orch_selection_revisions_decision",
        ),
        sa.CheckConstraint(
            "length(artifact_digest) = 64",
            name="ck_orch_selection_revisions_artifact",
        ),
        sa.CheckConstraint(
            "length(payload_digest) = 64",
            name="ck_orch_selection_revisions_payload",
        ),
        sa.ForeignKeyConstraint(
            ["selection_head_id", "project_id"],
            [
                f"{SCHEMA}.selection_heads.id",
                f"{SCHEMA}.selection_heads.project_id",
            ],
            name="fk_orch_selection_revisions_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "selected_attempt_id",
                "selected_operation_run_id",
                "project_id",
            ],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_selection_revisions_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "selection_head_id",
            "revision",
            "project_id",
            name="uq_orch_selection_revisions_number",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_selection_revisions_command",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_selection_revisions_head_created",
        "selection_revisions",
        ["selection_head_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_selection_revisions_attempt",
        "selection_revisions",
        ["selected_attempt_id"],
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_selection_heads_current",
        "selection_heads",
        "selection_revisions",
        ["id", "current_revision", "project_id"],
        ["selection_head_id", "revision", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    for table in ("budget_ledger_entries", "selection_revisions"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON orchestration.{table}
            FOR EACH ROW
            EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
            """
        )
    op.execute(
        "REVOKE ALL ON TABLE orchestration.budget_accounts, "
        "orchestration.budget_reservations, "
        "orchestration.budget_ledger_entries, "
        "orchestration.selection_heads, "
        "orchestration.selection_revisions FROM PUBLIC"
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
                    ON orchestration.budget_accounts,
                       orchestration.budget_reservations,
                       orchestration.selection_heads
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON orchestration.budget_ledger_entries,
                       orchestration.selection_revisions
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
            "SELECT 1 FROM orchestration.selection_revisions "
            "UNION ALL SELECT 1 FROM orchestration.selection_heads "
            "UNION ALL SELECT 1 FROM orchestration.budget_ledger_entries "
            "UNION ALL SELECT 1 FROM orchestration.budget_reservations "
            "UNION ALL SELECT 1 FROM orchestration.budget_accounts)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete budget/selection facts; "
            "set ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after "
            "backup"
        )
    for table in ("selection_revisions", "budget_ledger_entries"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable "
            f"ON orchestration.{table}"
        )
    op.drop_constraint(
        "fk_orch_selection_heads_current",
        "selection_heads",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_table("selection_revisions", schema=SCHEMA)
    op.drop_table("selection_heads", schema=SCHEMA)
    op.drop_table("budget_ledger_entries", schema=SCHEMA)
    op.drop_table("budget_reservations", schema=SCHEMA)
    op.drop_table("budget_accounts", schema=SCHEMA)
