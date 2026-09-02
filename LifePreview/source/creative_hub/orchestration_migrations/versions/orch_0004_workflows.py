"""Add project-scoped workflow definitions, revisions, and runs.

Revision ID: orch_0004
Revises: orch_0003
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0004"
down_revision = "orch_0003"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("config_digest", sa.String(64), nullable=False),
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
            "length(project_key) BETWEEN 1 AND 100",
            name="ck_orch_projects_key_length",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_orch_projects_status",
        ),
        sa.CheckConstraint(
            "length(config_digest) = 64",
            name="ck_orch_projects_config_digest",
        ),
        sa.UniqueConstraint("project_key", name="uq_orch_projects_key"),
        sa.UniqueConstraint(
            "id", "project_key", name="uq_orch_projects_id_key"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_projects_status_created",
        "projects",
        ["status", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "current_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
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
            "length(workflow_key) BETWEEN 1 AND 160",
            name="ck_orch_workflow_defs_key_length",
        ),
        sa.CheckConstraint(
            "current_revision > 0",
            name="ck_orch_workflow_defs_revision",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_workflow_defs_project",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "workflow_key",
            name="uq_orch_workflow_defs_project_key",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_workflow_defs_id_project"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_workflow_defs_project_updated",
        "workflow_definitions",
        ["project_id", "updated_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "workflow_definition_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "workflow_definition_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("schema_revision", sa.String(64), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("definition_digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_workflow_revisions_positive"
        ),
        sa.CheckConstraint(
            "length(definition_digest) = 64",
            name="ck_orch_workflow_revisions_digest",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_workflow_revisions_command_length",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_definition_id", "project_id"],
            [
                f"{SCHEMA}.workflow_definitions.id",
                f"{SCHEMA}.workflow_definitions.project_id",
            ],
            name="fk_orch_workflow_revisions_definition",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workflow_definition_id",
            "revision",
            name="uq_orch_workflow_revisions_number",
        ),
        sa.UniqueConstraint(
            "id",
            "workflow_definition_id",
            "project_id",
            name="uq_orch_workflow_revisions_scope",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_workflow_revisions_command",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_workflow_revisions_definition_created",
        "workflow_definition_revisions",
        ["workflow_definition_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_workflow_defs_current_revision",
        "workflow_definitions",
        "workflow_definition_revisions",
        ["id", "current_revision"],
        ["workflow_definition_id", "revision"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "workflow_definition_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column(
            "workflow_revision_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Uuid(as_uuid=True), nullable=False),
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
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'RUNNING', 'WAITING_HUMAN', 'COMPLETED', "
            "'COMPLETED_WITH_WARNINGS', 'BLOCKED', 'FAILED', 'CANCELLED')",
            name="ck_orch_workflow_runs_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_workflow_runs_version"
        ),
        sa.CheckConstraint(
            "length(input_digest) = 64",
            name="ck_orch_workflow_runs_input_digest",
        ),
        sa.CheckConstraint(
            "length(policy_digest) = 64",
            name="ck_orch_workflow_runs_policy_digest",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_definition_id", "project_id"],
            [
                f"{SCHEMA}.workflow_definitions.id",
                f"{SCHEMA}.workflow_definitions.project_id",
            ],
            name="fk_orch_workflow_runs_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "workflow_revision_id",
                "workflow_definition_id",
                "project_id",
            ],
            [
                f"{SCHEMA}.workflow_definition_revisions.id",
                f"{SCHEMA}.workflow_definition_revisions.workflow_definition_id",
                f"{SCHEMA}.workflow_definition_revisions.project_id",
            ],
            name="fk_orch_workflow_runs_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_workflow_runs_command",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_workflow_runs_id_project"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_workflow_runs_project_status",
        "workflow_runs",
        ["project_id", "status", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_workflow_runs_definition_created",
        "workflow_runs",
        ["workflow_definition_id", "created_at"],
        schema=SCHEMA,
    )

    op.execute(
        """
        CREATE TRIGGER trg_workflow_definition_revisions_immutable
        BEFORE UPDATE OR DELETE
        ON orchestration.workflow_definition_revisions
        FOR EACH ROW
        EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE orchestration.projects, "
        "orchestration.workflow_definitions, "
        "orchestration.workflow_definition_revisions, "
        "orchestration.workflow_runs FROM PUBLIC"
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
                    ON orchestration.projects,
                       orchestration.workflow_definitions,
                       orchestration.workflow_runs
                    TO creative_orchestrator_app;
                GRANT SELECT, INSERT
                    ON orchestration.workflow_definition_revisions
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
            "SELECT 1 FROM orchestration.workflow_runs "
            "UNION ALL SELECT 1 FROM "
            "orchestration.workflow_definition_revisions "
            "UNION ALL SELECT 1 FROM orchestration.workflow_definitions "
            "UNION ALL SELECT 1 FROM orchestration.projects)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete project/workflow facts; "
            "set ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after "
            "backup"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_workflow_definition_revisions_immutable "
        "ON orchestration.workflow_definition_revisions"
    )
    op.drop_table("workflow_runs", schema=SCHEMA)
    op.drop_constraint(
        "fk_orch_workflow_defs_current_revision",
        "workflow_definitions",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_table("workflow_definition_revisions", schema=SCHEMA)
    op.drop_table("workflow_definitions", schema=SCHEMA)
    op.drop_table("projects", schema=SCHEMA)
