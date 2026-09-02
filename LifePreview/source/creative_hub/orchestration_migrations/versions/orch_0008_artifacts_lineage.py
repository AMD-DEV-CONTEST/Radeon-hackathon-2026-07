"""Add fenced artifact publication, lineage, and GC tombstones.

Revision ID: orch_0008
Revises: orch_0007
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0008"
down_revision = "orch_0007"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.create_table(
        "artifact_publication_claims",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_attempt_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("publication_key", sa.String(255), nullable=False),
        sa.Column("staging_token", sa.Uuid(as_uuid=True), nullable=False),
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
            "attempt_number > 0",
            name="ck_orch_artifact_claim_attempt_number",
        ),
        sa.CheckConstraint(
            "fencing_token >= 0",
            name="ck_orch_artifact_claim_fencing",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'REGISTERED', 'FINALIZED', 'SUPERSEDED')",
            name="ck_orch_artifact_claim_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_artifact_claim_version",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_attempt_id",
                "operation_run_id",
                "attempt_number",
                "project_id",
            ],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.attempt_number",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_artifact_claim_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "operation_attempt_id",
            "publication_key",
            name="uq_orch_artifact_claim_publication",
        ),
        sa.UniqueConstraint(
            "project_id",
            "staging_token",
            name="uq_orch_artifact_claim_staging_token",
        ),
        sa.UniqueConstraint(
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
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_artifact_claim_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_artifact_claim_recovery",
        "artifact_publication_claims",
        ["status", "updated_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_artifact_claim_current_fence",
        "artifact_publication_claims",
        ["project_id", "operation_run_id", "fencing_token"],
        schema=SCHEMA,
    )

    op.execute(
        """
        CREATE FUNCTION orchestration.reject_stale_artifact_claim()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            newest_fence bigint;
            newest_attempt uuid;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    NEW.project_id::text || ':' || NEW.operation_run_id::text,
                    0
                )
            );
            SELECT fencing_token, operation_attempt_id
              INTO newest_fence, newest_attempt
              FROM orchestration.artifact_publication_claims
             WHERE project_id = NEW.project_id
               AND operation_run_id = NEW.operation_run_id
             ORDER BY fencing_token DESC
             LIMIT 1;
            IF newest_fence IS NOT NULL
               AND (
                    NEW.fencing_token < newest_fence
                    OR (
                        NEW.fencing_token = newest_fence
                        AND NEW.operation_attempt_id <> newest_attempt
                    )
               ) THEN
                RAISE EXCEPTION 'stale artifact publication fence'
                    USING ERRCODE = '40001';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifact_claim_fencing
        BEFORE INSERT ON orchestration.artifact_publication_claims
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_stale_artifact_claim()
        """
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("publication_claim_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("operation_attempt_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("publication_key", sa.String(255), nullable=False),
        sa.Column("staging_token", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("logical_role", sa.String(200), nullable=False),
        sa.Column("retention_class", sa.String(16), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True)),
        sa.Column("staging_locator", sa.String(255), nullable=False),
        sa.Column("storage_uri", sa.String(255)),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="PENDING",
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
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_orch_artifacts_attempt_number",
        ),
        sa.CheckConstraint(
            "fencing_token >= 0",
            name="ck_orch_artifacts_fencing",
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name="ck_orch_artifacts_digest",
        ),
        sa.CheckConstraint(
            "byte_size > 0",
            name="ck_orch_artifacts_byte_size",
        ),
        sa.CheckConstraint(
            "mime_type ~ '^[a-z0-9][a-z0-9!#$&^_.+-]*/"
            "[a-z0-9][a-z0-9!#$&^_.+-]*$'",
            name="ck_orch_artifacts_mime",
        ),
        sa.CheckConstraint(
            "logical_role ~ '^[A-Za-z][A-Za-z0-9_.:-]{0,199}$'",
            name="ck_orch_artifacts_role",
        ),
        sa.CheckConstraint(
            "retention_class IN ('ephemeral', 'workflow', 'audit', 'canon')",
            name="ck_orch_artifacts_retention",
        ),
        sa.CheckConstraint(
            "staging_locator ~ '^\\.staging/"
            "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            "[0-9a-f]{4}-[0-9a-f]{12}\\.part$'",
            name="ck_orch_artifacts_staging_locator",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMMITTED', 'TOMBSTONED')",
            name="ck_orch_artifacts_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_artifacts_version",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND storage_uri IS NULL "
            "AND committed_at IS NULL AND tombstoned_at IS NULL) OR "
            "(status = 'COMMITTED' AND storage_uri IS NOT NULL "
            "AND committed_at IS NOT NULL AND tombstoned_at IS NULL) OR "
            "(status = 'TOMBSTONED' AND storage_uri IS NOT NULL "
            "AND committed_at IS NOT NULL AND tombstoned_at IS NOT NULL)",
            name="ck_orch_artifacts_publication_state",
        ),
        sa.CheckConstraint(
            "storage_uri IS NULL OR "
            "storage_uri ~ '^artifact://sha256/[0-9a-f]{64}$'",
            name="ck_orch_artifacts_storage_uri",
        ),
        sa.ForeignKeyConstraint(
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
                f"{SCHEMA}.artifact_publication_claims.id",
                f"{SCHEMA}.artifact_publication_claims.project_id",
                f"{SCHEMA}.artifact_publication_claims.operation_run_id",
                f"{SCHEMA}.artifact_publication_claims.operation_attempt_id",
                f"{SCHEMA}.artifact_publication_claims.attempt_number",
                f"{SCHEMA}.artifact_publication_claims.fencing_token",
                f"{SCHEMA}.artifact_publication_claims.publication_key",
                f"{SCHEMA}.artifact_publication_claims.staging_token",
            ],
            name="fk_orch_artifacts_claim",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "operation_attempt_id",
                "operation_run_id",
                "attempt_number",
                "project_id",
            ],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.attempt_number",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_artifacts_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_artifacts_scope",
        ),
        sa.UniqueConstraint(
            "project_id",
            "publication_claim_id",
            name="uq_orch_artifacts_claim",
        ),
        sa.UniqueConstraint(
            "project_id",
            "operation_attempt_id",
            "publication_key",
            name="uq_orch_artifacts_publication",
        ),
        sa.UniqueConstraint(
            "project_id",
            "staging_token",
            name="uq_orch_artifacts_staging_token",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_artifacts_project_status",
        "artifacts",
        ["project_id", "status", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_artifacts_project_digest",
        "artifacts",
        ["project_id", "content_digest"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_artifacts_gc",
        "artifacts",
        ["status", "retain_until", "state_version"],
        schema=SCHEMA,
    )

    op.execute(
        """
        CREATE FUNCTION orchestration.validate_artifact_registration()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            newest_fence bigint;
            newest_attempt uuid;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    NEW.project_id::text || ':' || NEW.operation_run_id::text,
                    0
                )
            );
            SELECT fencing_token, operation_attempt_id
              INTO newest_fence, newest_attempt
              FROM orchestration.artifact_publication_claims
             WHERE project_id = NEW.project_id
               AND operation_run_id = NEW.operation_run_id
             ORDER BY fencing_token DESC
             LIMIT 1;
            IF newest_fence IS NULL
               OR NEW.fencing_token <> newest_fence
               OR NEW.operation_attempt_id <> newest_attempt THEN
                RAISE EXCEPTION 'stale artifact registration fence'
                    USING ERRCODE = '40001';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifacts_registration_fence
        BEFORE INSERT ON orchestration.artifacts
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.validate_artifact_registration()
        """
    )
    op.execute(
        """
        CREATE FUNCTION orchestration.guard_artifact_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            newest_fence bigint;
            newest_attempt uuid;
        BEGIN
            IF ROW(
                OLD.id, OLD.project_id, OLD.publication_claim_id,
                OLD.operation_run_id, OLD.operation_attempt_id,
                OLD.attempt_number, OLD.fencing_token, OLD.publication_key,
                OLD.staging_token, OLD.content_digest, OLD.byte_size,
                OLD.mime_type, OLD.logical_role, OLD.retention_class,
                OLD.retain_until, OLD.staging_locator, OLD.created_at
            ) IS DISTINCT FROM ROW(
                NEW.id, NEW.project_id, NEW.publication_claim_id,
                NEW.operation_run_id, NEW.operation_attempt_id,
                NEW.attempt_number, NEW.fencing_token, NEW.publication_key,
                NEW.staging_token, NEW.content_digest, NEW.byte_size,
                NEW.mime_type, NEW.logical_role, NEW.retention_class,
                NEW.retain_until, NEW.staging_locator, NEW.created_at
            ) THEN
                RAISE EXCEPTION 'artifact identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.state_version <> OLD.state_version + 1 THEN
                RAISE EXCEPTION 'artifact state version must increment by one'
                    USING ERRCODE = '40001';
            END IF;
            IF OLD.status = 'PENDING' AND NEW.status = 'COMMITTED' THEN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(
                        NEW.project_id::text || ':' ||
                        NEW.operation_run_id::text,
                        0
                    )
                );
                SELECT fencing_token, operation_attempt_id
                  INTO newest_fence, newest_attempt
                  FROM orchestration.artifact_publication_claims
                 WHERE project_id = NEW.project_id
                   AND operation_run_id = NEW.operation_run_id
                 ORDER BY fencing_token DESC
                 LIMIT 1;
                IF NEW.fencing_token <> newest_fence
                   OR NEW.operation_attempt_id <> newest_attempt THEN
                    RAISE EXCEPTION 'stale artifact finalize fence'
                        USING ERRCODE = '40001';
                END IF;
            END IF;
            IF OLD.status = 'TOMBSTONED'
               OR (OLD.status = 'COMMITTED' AND NEW.status <> 'TOMBSTONED')
               OR (OLD.status = 'PENDING'
                   AND NEW.status NOT IN ('COMMITTED', 'TOMBSTONED')) THEN
                RAISE EXCEPTION 'invalid artifact state transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifacts_guard_identity
        BEFORE UPDATE ON orchestration.artifacts
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.guard_artifact_identity()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifacts_reject_delete
        BEFORE DELETE ON orchestration.artifacts
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
        """
    )

    op.create_table(
        "artifact_lineage_edges",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("output_artifact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("input_artifact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(200), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "output_artifact_id <> input_artifact_id",
            name="ck_orch_artifact_lineage_not_self",
        ),
        sa.CheckConstraint(
            "role ~ '^[A-Za-z][A-Za-z0-9_.:-]{0,199}$'",
            name="ck_orch_artifact_lineage_role",
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_orch_artifact_lineage_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["output_artifact_id", "project_id"],
            [
                f"{SCHEMA}.artifacts.id",
                f"{SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_artifact_lineage_output",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["input_artifact_id", "project_id"],
            [
                f"{SCHEMA}.artifacts.id",
                f"{SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_artifact_lineage_input",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "output_artifact_id",
            "role",
            "ordinal",
            name="uq_orch_artifact_lineage_role_order",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_artifact_lineage_input",
        "artifact_lineage_edges",
        ["project_id", "input_artifact_id"],
        schema=SCHEMA,
    )

    op.execute(
        """
        CREATE FUNCTION orchestration.reject_artifact_lineage_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            expected_ordinal integer;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.project_id::text, 0)
            );
            SELECT count(*)::integer
              INTO expected_ordinal
              FROM orchestration.artifact_lineage_edges
             WHERE project_id = NEW.project_id
               AND output_artifact_id = NEW.output_artifact_id
               AND role = NEW.role;
            IF NEW.ordinal <> expected_ordinal THEN
                RAISE EXCEPTION
                    'artifact lineage ordinal must be contiguous from zero'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                WITH RECURSIVE ancestors(artifact_id) AS (
                    SELECT NEW.input_artifact_id
                    UNION
                    SELECT edge.input_artifact_id
                      FROM orchestration.artifact_lineage_edges edge
                      JOIN ancestors parent
                        ON edge.output_artifact_id = parent.artifact_id
                     WHERE edge.project_id = NEW.project_id
                )
                SELECT 1
                  FROM ancestors
                 WHERE artifact_id = NEW.output_artifact_id
            ) THEN
                RAISE EXCEPTION 'artifact lineage cycle'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifact_lineage_cycle
        BEFORE INSERT ON orchestration.artifact_lineage_edges
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_artifact_lineage_cycle()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifact_lineage_immutable
        BEFORE UPDATE OR DELETE ON orchestration.artifact_lineage_edges
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
        """
    )

    op.create_table(
        "artifact_gc_tombstones",
        sa.Column(
            "artifact_id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("artifact_state_version", sa.Integer(), nullable=False),
        sa.Column(
            "tombstoned_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name="ck_orch_artifact_tombstone_digest",
        ),
        sa.CheckConstraint(
            "artifact_state_version > 0",
            name="ck_orch_artifact_tombstone_version",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "project_id"],
            [
                f"{SCHEMA}.artifacts.id",
                f"{SCHEMA}.artifacts.project_id",
            ],
            name="fk_orch_artifact_tombstone_artifact",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.execute(
        """
        CREATE FUNCTION orchestration.record_artifact_tombstone()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.status = 'TOMBSTONED'
               AND OLD.status <> 'TOMBSTONED' THEN
                INSERT INTO orchestration.artifact_gc_tombstones(
                    artifact_id, project_id, content_digest,
                    artifact_state_version, tombstoned_at
                ) VALUES (
                    NEW.id, NEW.project_id, NEW.content_digest,
                    NEW.state_version, NEW.tombstoned_at
                )
                ON CONFLICT (artifact_id) DO NOTHING;
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifacts_record_tombstone
        AFTER UPDATE ON orchestration.artifacts
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.record_artifact_tombstone()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_artifact_tombstones_immutable
        BEFORE UPDATE OR DELETE ON orchestration.artifact_gc_tombstones
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
        """
    )

    op.execute(
        """
        REVOKE ALL ON TABLE
            orchestration.artifact_publication_claims,
            orchestration.artifacts,
            orchestration.artifact_lineage_edges,
            orchestration.artifact_gc_tombstones
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
                    ON orchestration.artifact_publication_claims,
                       orchestration.artifacts
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON orchestration.artifact_lineage_edges
                    TO creative_orchestrator_app;
                GRANT SELECT
                    ON orchestration.artifact_gc_tombstones
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
            "SELECT 1 FROM orchestration.artifact_gc_tombstones "
            "UNION ALL SELECT 1 FROM orchestration.artifact_lineage_edges "
            "UNION ALL SELECT 1 FROM orchestration.artifacts "
            "UNION ALL SELECT 1 FROM "
            "orchestration.artifact_publication_claims)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete artifact and lineage facts; "
            "set ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after "
            "backup"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifact_tombstones_immutable "
        "ON orchestration.artifact_gc_tombstones"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifacts_record_tombstone "
        "ON orchestration.artifacts"
    )
    op.drop_table("artifact_gc_tombstones", schema=SCHEMA)
    op.execute(
        "DROP FUNCTION IF EXISTS orchestration.record_artifact_tombstone()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifact_lineage_immutable "
        "ON orchestration.artifact_lineage_edges"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifact_lineage_cycle "
        "ON orchestration.artifact_lineage_edges"
    )
    op.drop_table("artifact_lineage_edges", schema=SCHEMA)
    op.execute(
        "DROP FUNCTION IF EXISTS orchestration.reject_artifact_lineage_cycle()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifacts_reject_delete "
        "ON orchestration.artifacts"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifacts_guard_identity "
        "ON orchestration.artifacts"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifacts_registration_fence "
        "ON orchestration.artifacts"
    )
    op.drop_table("artifacts", schema=SCHEMA)
    op.execute(
        "DROP FUNCTION IF EXISTS orchestration.guard_artifact_identity()"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "orchestration.validate_artifact_registration()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_artifact_claim_fencing "
        "ON orchestration.artifact_publication_claims"
    )
    op.drop_table("artifact_publication_claims", schema=SCHEMA)
    op.execute(
        "DROP FUNCTION IF EXISTS orchestration.reject_stale_artifact_claim()"
    )
