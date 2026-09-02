"""Persist artifact GC roots and bind selections to committed artifacts.

Revision ID: orch_0010
Revises: orch_0009
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0010"
down_revision = "orch_0009"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    # orch_0002 predates the immutable migration rule and creates this table
    # from the live ORM model.  A fresh install can therefore already contain
    # this newer index, while an existing installation upgraded from the
    # original orch_0002 does not.  Keep this migration safe for both paths.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_gpu_leases_one_active_per_gpu
        ON orchestration.gpu_leases (gpu_index)
        WHERE status = 'active' AND gpu_index IS NOT NULL
        """
    )
    op.create_unique_constraint(
        "uq_orch_budget_reservations_project_scope",
        "budget_reservations",
        ["id", "project_id"],
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_orch_provider_invocations_reservation",
        "provider_invocations",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_orch_provider_invocations_reservation",
        "provider_invocations",
        "budget_reservations",
        ["reservation_id", "project_id"],
        ["id", "project_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )

    op.execute(
        """
        CREATE FUNCTION orchestration.enforce_current_artifact_attempt()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_attempt uuid;
            current_number integer;
            current_fence bigint;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    NEW.project_id::text || ':' ||
                    NEW.operation_run_id::text,
                    0
                )
            );
            SELECT id, attempt_number, fencing_token
              INTO current_attempt, current_number, current_fence
              FROM orchestration.operation_attempts
             WHERE project_id = NEW.project_id
               AND operation_run_id = NEW.operation_run_id
             ORDER BY fencing_token DESC, attempt_number DESC
             LIMIT 1;
            IF current_attempt IS NULL
               OR NEW.operation_attempt_id <> current_attempt
               OR NEW.attempt_number <> current_number
               OR NEW.fencing_token <> current_fence THEN
                RAISE EXCEPTION 'stale artifact operation attempt'
                    USING ERRCODE = '40001';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifact_claim_current_attempt
        BEFORE INSERT ON orchestration.artifact_publication_claims
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.enforce_current_artifact_attempt()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifacts_current_attempt_insert
        BEFORE INSERT ON orchestration.artifacts
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.enforce_current_artifact_attempt()
        """
    )
    op.execute(
        """
        CREATE FUNCTION orchestration.enforce_current_artifact_finalize()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_attempt uuid;
            current_number integer;
            current_fence bigint;
        BEGIN
            IF OLD.status = 'PENDING' AND NEW.status = 'COMMITTED' THEN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(
                        NEW.project_id::text || ':' ||
                        NEW.operation_run_id::text,
                        0
                    )
                );
                SELECT id, attempt_number, fencing_token
                  INTO current_attempt, current_number, current_fence
                  FROM orchestration.operation_attempts
                 WHERE project_id = NEW.project_id
                   AND operation_run_id = NEW.operation_run_id
                 ORDER BY fencing_token DESC, attempt_number DESC
                 LIMIT 1;
                IF current_attempt IS NULL
                   OR NEW.operation_attempt_id <> current_attempt
                   OR NEW.attempt_number <> current_number
                   OR NEW.fencing_token <> current_fence THEN
                    RAISE EXCEPTION 'stale artifact finalize attempt'
                        USING ERRCODE = '40001';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifacts_current_attempt_finalize
        BEFORE UPDATE ON orchestration.artifacts
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.enforce_current_artifact_finalize()
        """
    )

    op.create_unique_constraint(
        "uq_orch_artifacts_selection_identity",
        "artifacts",
        [
            "id",
            "project_id",
            "operation_run_id",
            "operation_attempt_id",
            "content_digest",
        ],
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_selection_revisions_artifact",
        "selection_revisions",
        "artifacts",
        [
            "artifact_id",
            "project_id",
            "selected_operation_run_id",
            "selected_attempt_id",
            "artifact_digest",
        ],
        [
            "id",
            "project_id",
            "operation_run_id",
            "operation_attempt_id",
            "content_digest",
        ],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )

    op.create_table(
        "artifact_protection_versions",
        sa.Column(
            "project_id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "version",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_orch_artifact_protection_version",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_artifact_protection_version_project",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "artifact_protection_roots",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("artifact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('selected', 'canonical', 'open_review_evidence', "
            "'open_qc_evidence', 'replay_manifest')",
            name="ck_orch_artifact_protection_kind",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.artifact_protection_versions.project_id"],
            name="fk_orch_artifact_protection_root_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "project_id"],
            [f"{SCHEMA}.artifacts.id", f"{SCHEMA}.artifacts.project_id"],
            name="fk_orch_artifact_protection_root_artifact",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "kind",
            "artifact_id",
            name="uq_orch_artifact_protection_root",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_artifact_protection_roots_project_kind",
        "artifact_protection_roots",
        ["project_id", "kind"],
        schema=SCHEMA,
    )

    # Repository checks provide precise application errors. This trigger makes
    # the invariant unavoidable for direct SQL and future code paths too.
    op.execute(
        """
        CREATE FUNCTION orchestration.validate_selection_artifact()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                  FROM orchestration.selection_heads head
                  JOIN orchestration.operation_runs operation
                    ON operation.id = NEW.selected_operation_run_id
                   AND operation.project_id = NEW.project_id
                   AND operation.workflow_run_id = head.workflow_run_id
                  JOIN orchestration.operation_attempt_states attempt_state
                    ON attempt_state.attempt_id = NEW.selected_attempt_id
                   AND attempt_state.operation_run_id =
                       NEW.selected_operation_run_id
                   AND attempt_state.project_id = NEW.project_id
                   AND attempt_state.status = 'SUCCEEDED'
                  JOIN orchestration.artifacts artifact
                    ON artifact.id = NEW.artifact_id
                   AND artifact.project_id = NEW.project_id
                   AND artifact.operation_run_id =
                       NEW.selected_operation_run_id
                   AND artifact.operation_attempt_id =
                       NEW.selected_attempt_id
                   AND artifact.content_digest = NEW.artifact_digest
                   AND artifact.status = 'COMMITTED'
                 WHERE head.id = NEW.selection_head_id
                   AND head.project_id = NEW.project_id
            ) THEN
                RAISE EXCEPTION
                    'selection must reference a successful committed artifact '
                    'from the same workflow'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_selection_revisions_artifact_integrity
        BEFORE INSERT ON orchestration.selection_revisions
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.validate_selection_artifact()
        """
    )

    op.execute(
        """
        REVOKE ALL ON TABLE
            orchestration.artifact_protection_versions,
            orchestration.artifact_protection_roots
        FROM PUBLIC
        """
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
                    ON orchestration.artifact_protection_versions
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT, DELETE
                    ON orchestration.artifact_protection_roots
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
            "SELECT 1 FROM orchestration.artifact_protection_roots)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete artifact protection roots; "
            "set ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after "
            "backup"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifacts_current_attempt_finalize "
        "ON orchestration.artifacts"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.enforce_current_artifact_finalize()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifacts_current_attempt_insert "
        "ON orchestration.artifacts"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifact_claim_current_attempt "
        "ON orchestration.artifact_publication_claims"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.enforce_current_artifact_attempt()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_selection_revisions_artifact_integrity "
        "ON orchestration.selection_revisions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.validate_selection_artifact()"
    )
    op.drop_index(
        "ix_orch_artifact_protection_roots_project_kind",
        table_name="artifact_protection_roots",
        schema=SCHEMA,
    )
    op.drop_table("artifact_protection_roots", schema=SCHEMA)
    op.drop_table("artifact_protection_versions", schema=SCHEMA)
    op.drop_constraint(
        "fk_orch_selection_revisions_artifact",
        "selection_revisions",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_orch_artifacts_selection_identity",
        "artifacts",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_orch_provider_invocations_reservation",
        "provider_invocations",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_orch_provider_invocations_reservation",
        "provider_invocations",
        "budget_reservations",
        ["reservation_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_orch_budget_reservations_project_scope",
        "budget_reservations",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_index(
        "uq_gpu_leases_one_active_per_gpu",
        table_name="gpu_leases",
        schema=SCHEMA,
    )
