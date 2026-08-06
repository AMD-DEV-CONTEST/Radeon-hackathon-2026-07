"""Add proof-based cutover authority, imports, in-flight work and reconciliation.

Revision ID: orch_0014
Revises: orch_0013
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0014"
down_revision = "orch_0013"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.create_table(
        "cutover_epochs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("cutover_epoch", sa.String(160), nullable=False),
        sa.Column(
            "phase",
            sa.String(32),
            nullable=False,
            server_default="PLANNED",
        ),
        sa.Column(
            "state_version",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "legacy_admission_frozen",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "legacy_write_fence",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("source_snapshot_digest", sa.String(64)),
        sa.Column("created_by_actor", sa.String(160), nullable=False),
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
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("first_unified_write_at", sa.DateTime(timezone=True)),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "cutover_epoch",
            name="uq_orch_cutover_epoch",
        ),
        sa.CheckConstraint(
            "phase IN ('PLANNED', 'FROZEN', 'IMPORTING', 'RECONCILING', "
            "'DRAINING', 'READY', 'ACTIVATED', 'FORWARD_FIX', "
            "'ROLLED_BACK', 'RETIRED')",
            name="ck_orch_cutover_phase",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_cutover_state_version",
        ),
        sa.CheckConstraint(
            "source_snapshot_digest IS NULL "
            "OR length(source_snapshot_digest) = 64",
            name="ck_orch_cutover_snapshot_digest",
        ),
        sa.CheckConstraint(
            "first_unified_write_at IS NULL OR activated_at IS NOT NULL",
            name="ck_orch_cutover_first_write_after_activation",
        ),
        sa.CheckConstraint(
            "phase NOT IN ('ACTIVATED', 'FORWARD_FIX', 'RETIRED') "
            "OR (legacy_admission_frozen AND legacy_write_fence)",
            name="ck_orch_cutover_active_fences",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_cutover_phase_updated",
        "cutover_epochs",
        ["phase", "updated_at"],
        schema=SCHEMA,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_orch_one_active_cutover
        ON orchestration.cutover_epochs ((1))
        WHERE phase NOT IN ('ROLLED_BACK', 'RETIRED')
        """
    )

    op.create_table(
        "cutover_import_batches",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("cutover_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_identity", sa.String(500), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("source_manifest", sa.JSON(), nullable=False),
        sa.Column("imported_by_actor", sa.String(160), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "cutover_id",
            "source_kind",
            "source_identity",
            name="uq_orch_cutover_import_source",
        ),
        sa.CheckConstraint(
            "source_kind IN ('FACTORY_V3_FILE', 'LEGACY_DB_SNAPSHOT')",
            name="ck_orch_cutover_import_source_kind",
        ),
        sa.CheckConstraint(
            "length(source_digest) = 64",
            name="ck_orch_cutover_import_digest",
        ),
        sa.ForeignKeyConstraint(
            ["cutover_id"],
            [f"{SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_import_epoch",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_cutover_import_epoch_kind",
        "cutover_import_batches",
        ["cutover_id", "source_kind"],
        schema=SCHEMA,
    )

    op.create_table(
        "cutover_imported_facts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("cutover_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_identity", sa.String(500), nullable=False),
        sa.Column("fact_kind", sa.String(64), nullable=False),
        sa.Column("fact_digest", sa.String(64), nullable=False),
        sa.Column("proof_status", sa.String(16), nullable=False),
        sa.Column(
            "canon_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "cutover_id",
            "source_kind",
            "source_identity",
            name="uq_orch_cutover_imported_fact",
        ),
        sa.CheckConstraint(
            "source_kind IN ('FACTORY_V3_FILE', 'LEGACY_DB_SNAPSHOT')",
            name="ck_orch_cutover_fact_source",
        ),
        sa.CheckConstraint(
            "proof_status IN ('PROVEN', 'UNKNOWN')",
            name="ck_orch_cutover_fact_proof",
        ),
        sa.CheckConstraint(
            "length(fact_digest) = 64",
            name="ck_orch_cutover_fact_digest",
        ),
        sa.CheckConstraint(
            "NOT canon_eligible",
            name="ck_orch_cutover_fact_never_auto_canon",
        ),
        sa.ForeignKeyConstraint(
            ["cutover_id"],
            [f"{SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_fact_epoch",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_cutover_fact_epoch_kind",
        "cutover_imported_facts",
        ["cutover_id", "fact_kind", "proof_status"],
        schema=SCHEMA,
    )

    op.create_table(
        "cutover_inflight_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("cutover_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("item_kind", sa.String(32), nullable=False),
        sa.Column("source_identity", sa.String(500), nullable=False),
        sa.Column("classification", sa.String(64), nullable=False),
        sa.Column("evidence_digest", sa.String(64)),
        sa.Column(
            "must_not_resubmit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint(
            "cutover_id",
            "item_kind",
            "source_identity",
            name="uq_orch_cutover_inflight_identity",
        ),
        sa.CheckConstraint(
            "item_kind IN ('RUN', 'PROVIDER_TASK', 'LEASE', 'SELECTION', "
            "'REVIEW')",
            name="ck_orch_cutover_inflight_kind",
        ),
        sa.CheckConstraint(
            "classification IN ('ADOPT_REQUIRED', 'ADOPTED', "
            "'LEGACY_DRAIN', 'TERMINAL', 'RUNNING', 'HUNG_MANUAL', "
            "'COMPLETED_PENDING_COLLECTION', 'COLLECTED', 'FAILED', "
            "'OUTCOME_UNKNOWN', 'RECHECK_REQUIRED', 'EXPIRED', "
            "'HUMAN_CONFIRM_REQUIRED', 'ADOPTED_READ_ONLY', 'RESOLVED', "
            "'UNKNOWN')",
            name="ck_orch_cutover_inflight_classification",
        ),
        sa.CheckConstraint(
            "evidence_digest IS NULL OR length(evidence_digest) = 64",
            name="ck_orch_cutover_inflight_digest",
        ),
        sa.CheckConstraint(
            "item_kind <> 'PROVIDER_TASK' OR must_not_resubmit",
            name="ck_orch_cutover_provider_no_resubmit",
        ),
        sa.ForeignKeyConstraint(
            ["cutover_id"],
            [f"{SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_inflight_epoch",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_cutover_inflight_epoch_classification",
        "cutover_inflight_items",
        ["cutover_id", "classification", "item_kind"],
        schema=SCHEMA,
    )

    op.create_table(
        "cutover_reconciliations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("cutover_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("running_count", sa.Integer(), nullable=False),
        sa.Column("terminal_counts", sa.JSON(), nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), nullable=False),
        sa.Column("artifact_digests", sa.JSON(), nullable=False),
        sa.Column("selections", sa.JSON(), nullable=False),
        sa.Column("open_review_tasks", sa.JSON(), nullable=False),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "cutover_id",
            "side",
            name="uq_orch_cutover_reconciliation_side",
        ),
        sa.CheckConstraint(
            "side IN ('LEGACY', 'UNIFIED')",
            name="ck_orch_cutover_reconciliation_side",
        ),
        sa.CheckConstraint(
            "running_count >= 0 AND cost_micros >= 0",
            name="ck_orch_cutover_reconciliation_counts",
        ),
        sa.CheckConstraint(
            "length(snapshot_digest) = 64",
            name="ck_orch_cutover_reconciliation_digest",
        ),
        sa.ForeignKeyConstraint(
            ["cutover_id"],
            [f"{SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_reconciliation_epoch",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "cutover_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("cutover_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor", sa.String(160), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "cutover_id",
            "sequence",
            name="uq_orch_cutover_event_sequence",
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_orch_cutover_event_sequence",
        ),
        sa.CheckConstraint(
            "length(payload_digest) = 64",
            name="ck_orch_cutover_event_digest",
        ),
        sa.ForeignKeyConstraint(
            ["cutover_id"],
            [f"{SCHEMA}.cutover_epochs.id"],
            name="fk_orch_cutover_event_epoch",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_cutover_event_epoch_sequence",
        "cutover_events",
        ["cutover_id", "sequence"],
        schema=SCHEMA,
    )

    op.execute(
        """
        CREATE FUNCTION orchestration.enforce_cutover_one_way_boundary()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.first_unified_write_at IS NULL
               AND NEW.first_unified_write_at IS NOT NULL
               AND (
                   OLD.phase <> 'ACTIVATED'
                   OR NEW.phase <> 'FORWARD_FIX'
                   OR NOT NEW.legacy_admission_frozen
                   OR NOT NEW.legacy_write_fence
               ) THEN
                RAISE EXCEPTION
                    'first unified write requires activated authority'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.first_unified_write_at IS NOT NULL THEN
                IF NEW.first_unified_write_at IS DISTINCT FROM
                   OLD.first_unified_write_at THEN
                    RAISE EXCEPTION 'first unified write is immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.phase = 'ROLLED_BACK'
                   OR NOT NEW.legacy_admission_frozen
                   OR NOT NEW.legacy_write_fence THEN
                    RAISE EXCEPTION
                        'rollback boundary crossed; forward fix only'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_cutover_one_way_boundary
        BEFORE UPDATE ON orchestration.cutover_epochs
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.enforce_cutover_one_way_boundary()
        """
    )
    op.execute(
        """
        CREATE FUNCTION orchestration.reject_cutover_evidence_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'cutover evidence is append-only'
                USING ERRCODE = '55000';
        END
        $$;
        """
    )
    for table in (
        "cutover_import_batches",
        "cutover_imported_facts",
        "cutover_reconciliations",
        "cutover_events",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON orchestration.{table}
            FOR EACH ROW
            EXECUTE FUNCTION orchestration.reject_cutover_evidence_mutation()
            """
        )

    tables = (
        "cutover_epochs",
        "cutover_import_batches",
        "cutover_imported_facts",
        "cutover_inflight_items",
        "cutover_reconciliations",
        "cutover_events",
    )
    op.execute(
        "REVOKE ALL ON TABLE "
        + ", ".join(f"orchestration.{table}" for table in tables)
        + " FROM PUBLIC"
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
                    ON orchestration.cutover_epochs,
                       orchestration.cutover_inflight_items
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON orchestration.cutover_import_batches,
                       orchestration.cutover_imported_facts,
                       orchestration.cutover_reconciliations,
                       orchestration.cutover_events
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
            "SELECT 1 FROM orchestration.cutover_epochs)"
        )
    ).scalar_one()
    if populated and os.getenv("ALLOW_DESTRUCTIVE_CUTOVER_DOWNGRADE") != "YES":
        raise RuntimeError(
            "cutover downgrade would delete durable authority evidence; "
            "set ALLOW_DESTRUCTIVE_CUTOVER_DOWNGRADE=YES only after backup"
        )
    for table in (
        "cutover_events",
        "cutover_reconciliations",
        "cutover_imported_facts",
        "cutover_import_batches",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_append_only "
            f"ON orchestration.{table}"
        )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.reject_cutover_evidence_mutation()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_cutover_one_way_boundary "
        "ON orchestration.cutover_epochs"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.enforce_cutover_one_way_boundary()"
    )
    op.drop_index(
        "ix_orch_cutover_event_epoch_sequence",
        table_name="cutover_events",
        schema=SCHEMA,
    )
    op.drop_table("cutover_events", schema=SCHEMA)
    op.drop_table("cutover_reconciliations", schema=SCHEMA)
    op.drop_index(
        "ix_orch_cutover_inflight_epoch_classification",
        table_name="cutover_inflight_items",
        schema=SCHEMA,
    )
    op.drop_table("cutover_inflight_items", schema=SCHEMA)
    op.drop_index(
        "ix_orch_cutover_fact_epoch_kind",
        table_name="cutover_imported_facts",
        schema=SCHEMA,
    )
    op.drop_table("cutover_imported_facts", schema=SCHEMA)
    op.drop_index(
        "ix_orch_cutover_import_epoch_kind",
        table_name="cutover_import_batches",
        schema=SCHEMA,
    )
    op.drop_table("cutover_import_batches", schema=SCHEMA)
    op.drop_index(
        "uq_orch_one_active_cutover",
        table_name="cutover_epochs",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_orch_cutover_phase_updated",
        table_name="cutover_epochs",
        schema=SCHEMA,
    )
    op.drop_table("cutover_epochs", schema=SCHEMA)
