"""Add normalized P0 product facts and orchestration role grants.

Revision ID: orch_0020
Revises: orch_0019

This migration is expand-only: it creates the normalized product tables,
links existing projects to the versioned ``general_video@1`` template,
extracts configured Factory bindings into unique Hub bindings, and grants
the orchestration application role least-privilege access. No
product logic lives here; backfills are mechanical data extraction only.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0020"
down_revision = "orch_0019"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"
SHA256 = "length({column}) = 64"

GENERAL_VIDEO_TEMPLATE_KEY = "general_video"
GENERAL_VIDEO_TEMPLATE_VERSION = 1


def _canonical_digest(value: object) -> str:
    """Mirror ``creative_hub.db.canonical.canonical_json_digest`` for backfill."""

    canonical = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


GENERAL_VIDEO_DIGEST = _canonical_digest(
    {
        "folder_schema": {},
        "workflow_schema": {"key": GENERAL_VIDEO_TEMPLATE_KEY},
        "work_unit_kind": "clip",
    }
)

# Deterministic id so the fallback template seed is idempotent without
# relying on a server-side UUID generator.
GENERAL_VIDEO_TEMPLATE_ID = uuid.uuid5(
    uuid.NAMESPACE_URL,
    f"orchestration:project_templates:{GENERAL_VIDEO_TEMPLATE_KEY}@"
    f"{GENERAL_VIDEO_TEMPLATE_VERSION}",
)


def _project_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id"],
        [f"{SCHEMA}.projects.id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    # --- Template registry ---------------------------------------------------
    op.create_table(
        "project_templates",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("template_key", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("work_unit_kind", sa.String(64), nullable=False),
        sa.Column("folder_schema", sa.JSON(), nullable=False),
        sa.Column("workflow_schema", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(template_key) BETWEEN 1 AND 120",
            name="ck_orch_project_templates_key_length",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_orch_project_templates_version"
        ),
        sa.CheckConstraint(
            "length(work_unit_kind) BETWEEN 1 AND 64",
            name="ck_orch_project_templates_work_unit_kind",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_project_templates_digest",
        ),
        sa.UniqueConstraint(
            "template_key",
            "version",
            name="uq_orch_project_templates_key_version",
        ),
        sa.UniqueConstraint(
            "id",
            "template_key",
            "version",
            "digest",
            name="uq_orch_project_templates_identity",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_project_templates_key_version",
        "project_templates",
        ["template_key", "version"],
        schema=SCHEMA,
    )

    # Seed the fallback template before projects references it.
    op.execute(
        f"""
        INSERT INTO orchestration.project_templates (
            id, template_key, version, work_unit_kind,
            folder_schema, workflow_schema, digest, created_by_actor
        )
        SELECT '{GENERAL_VIDEO_TEMPLATE_ID}', '{GENERAL_VIDEO_TEMPLATE_KEY}',
               {GENERAL_VIDEO_TEMPLATE_VERSION}, 'clip',
               '{{}}'::jsonb, '{{"key":"{GENERAL_VIDEO_TEMPLATE_KEY}"}}'::jsonb,
               '{GENERAL_VIDEO_DIGEST}', 'system.backfill'
        WHERE NOT EXISTS (
            SELECT 1 FROM orchestration.project_templates
            WHERE template_key = '{GENERAL_VIDEO_TEMPLATE_KEY}'
              AND version = {GENERAL_VIDEO_TEMPLATE_VERSION}
        )
        """
    )

    # --- Link existing projects to the versioned template -------------------
    op.add_column(
        "projects",
        sa.Column(
            "template_key",
            sa.String(120),
            nullable=False,
            server_default=GENERAL_VIDEO_TEMPLATE_KEY,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "projects",
        sa.Column(
            "template_version",
            sa.Integer(),
            nullable=False,
            server_default=str(GENERAL_VIDEO_TEMPLATE_VERSION),
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_projects_template_key_length",
        "projects",
        "length(template_key) BETWEEN 1 AND 120",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_projects_template_version",
        "projects",
        "template_version > 0",
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_orch_projects_template",
        "projects",
        "project_templates",
        ["template_key", "template_version"],
        ["template_key", "version"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_orch_projects_template",
        "projects",
        ["template_key", "template_version"],
        schema=SCHEMA,
    )

    # --- Factory one-to-one binding -----------------------------------------
    op.create_table(
        "factory_project_bindings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "factory_project_key", sa.String(200), nullable=False
        ),
        sa.Column("factory_revision", sa.String(200), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
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
            "length(factory_project_key) BETWEEN 1 AND 200",
            name="ck_orch_factory_bindings_factory_key_length",
        ),
        sa.CheckConstraint(
            "length(factory_revision) BETWEEN 1 AND 200",
            name="ck_orch_factory_bindings_revision_length",
        ),
        _project_fk("fk_orch_factory_bindings_project"),
        sa.UniqueConstraint(
            "project_id", name="uq_orch_factory_bindings_project"
        ),
        sa.UniqueConstraint(
            "factory_project_key",
            name="uq_orch_factory_bindings_factory_key",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_factory_bindings_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_factory_bindings_factory_key",
        "factory_project_bindings",
        ["factory_project_key"],
        schema=SCHEMA,
    )

    # Mechanically extract the legacy config-based Factory binding into the
    # unique Hub binding without inferring any new product state.
    op.execute(
        """
        INSERT INTO orchestration.factory_project_bindings (
            id, project_id, factory_project_key, factory_revision,
            created_by_actor, created_at, updated_at
        )
        SELECT md5(
                   p.id::text || ':' || (p.config ->> 'factory_project_key')
               )::uuid,
               p.id,
               p.config ->> 'factory_project_key',
               COALESCE(
                   NULLIF(p.config ->> 'factory_revision', ''),
                   'backfill'
               ),
               'system.backfill', NOW(), NOW()
        FROM orchestration.projects p
        WHERE p.config ->> 'factory_project_key' IS NOT NULL
          AND btrim(p.config ->> 'factory_project_key') <> ''
        ON CONFLICT (factory_project_key) DO NOTHING
        """
    )

    # --- Work units and folder projections ----------------------------------
    op.create_table(
        "work_units",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("external_key", sa.String(200), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "state_version",
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
            "length(kind) BETWEEN 1 AND 64",
            name="ck_orch_work_units_kind_length",
        ),
        sa.CheckConstraint(
            "length(external_key) BETWEEN 1 AND 200",
            name="ck_orch_work_units_external_key_length",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED')",
            name="ck_orch_work_units_status",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_work_units_version"
        ),
        _project_fk("fk_orch_work_units_project"),
        sa.UniqueConstraint(
            "project_id",
            "kind",
            "external_key",
            name="uq_orch_work_units_project_kind_key",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_work_units_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_work_units_project_kind",
        "work_units",
        ["project_id", "kind", "external_key"],
        schema=SCHEMA,
    )

    op.create_table(
        "folder_projections",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("work_unit_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("node_key", sa.String(200), nullable=False),
        sa.Column("parent_key", sa.String(200)),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column(
            "projection_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
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
            "length(node_key) BETWEEN 1 AND 200",
            name="ck_orch_folder_projections_node_key",
        ),
        sa.CheckConstraint(
            "parent_key IS NULL OR length(parent_key) BETWEEN 1 AND 200",
            name="ck_orch_folder_projections_parent_key",
        ),
        sa.CheckConstraint(
            "length(role) BETWEEN 1 AND 64",
            name="ck_orch_folder_projections_role",
        ),
        sa.CheckConstraint(
            "projection_version > 0",
            name="ck_orch_folder_projections_projection_version",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_folder_projections_version"
        ),
        _project_fk("fk_orch_folder_projections_project"),
        sa.ForeignKeyConstraint(
            ["work_unit_id", "project_id"],
            [f"{SCHEMA}.work_units.id", f"{SCHEMA}.work_units.project_id"],
            name="fk_orch_folder_projections_work_unit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "work_unit_id",
            "node_key",
            name="uq_orch_folder_projections_node",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_folder_projections_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_folder_projections_work_unit",
        "folder_projections",
        ["project_id", "work_unit_id", "node_key"],
        schema=SCHEMA,
    )

    # --- Skills and run snapshots -------------------------------------------
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("skill_key", sa.String(160), nullable=False),
        sa.Column(
            "lifecycle",
            sa.String(16),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("current_revision", sa.Integer()),
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
            "length(skill_key) BETWEEN 1 AND 160",
            name="ck_orch_skills_key_length",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('DRAFT', 'APPROVED', 'DEPRECATED', 'RETIRED')",
            name="ck_orch_skills_lifecycle",
        ),
        sa.CheckConstraint(
            "current_revision IS NULL OR current_revision > 0",
            name="ck_orch_skills_current_revision",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_orch_skills_version"
        ),
        sa.UniqueConstraint("skill_key", name="uq_orch_skills_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_skills_lifecycle",
        "skills",
        ["lifecycle"],
        schema=SCHEMA,
    )

    op.create_table(
        "skill_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("skill_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("applicability", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_skill_revisions_positive"
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'DEPRECATED', 'RETIRED')",
            name="ck_orch_skill_revisions_status",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_skill_revisions_digest",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            [f"{SCHEMA}.skills.id"],
            name="fk_orch_skill_revisions_skill",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "skill_id", "revision", name="uq_orch_skill_revisions_number"
        ),
        sa.UniqueConstraint(
            "id",
            "skill_id",
            "revision",
            "digest",
            name="uq_orch_skill_revisions_identity",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_skill_revisions_skill_revision",
        "skill_revisions",
        ["skill_id", "revision"],
        schema=SCHEMA,
    )

    op.create_table(
        "project_skill_bindings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "skill_revision_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column(
            "scope",
            sa.String(16),
            nullable=False,
            server_default="project",
        ),
        sa.Column("scope_ref", sa.Uuid(as_uuid=True)),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "state_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
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
            "scope IN ('project', 'work_unit')",
            name="ck_orch_project_skill_bindings_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'project' AND scope_ref IS NULL) OR "
            "(scope = 'work_unit' AND scope_ref IS NOT NULL)",
            name="ck_orch_project_skill_bindings_scope_shape",
        ),
        sa.CheckConstraint(
            "priority >= 0",
            name="ck_orch_project_skill_bindings_priority",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_project_skill_bindings_command_length",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_project_skill_bindings_version",
        ),
        _project_fk("fk_orch_project_skill_bindings_project"),
        sa.ForeignKeyConstraint(
            ["skill_revision_id"],
            [f"{SCHEMA}.skill_revisions.id"],
            name="fk_orch_project_skill_bindings_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_project_skill_bindings_command",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_project_skill_bindings_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_project_skill_bindings_project_priority",
        "project_skill_bindings",
        ["project_id", "priority"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_orch_project_skill_bindings_project_scope",
        "project_skill_bindings",
        ["project_id", "skill_revision_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("scope = 'project'"),
    )
    op.create_index(
        "uq_orch_project_skill_bindings_work_unit_scope",
        "project_skill_bindings",
        ["project_id", "skill_revision_id", "scope_ref"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("scope = 'work_unit'"),
    )

    # Historical run skill snapshots start empty; the default status below
    # marks any future backfilled snapshot UNKNOWN without inferring a freeze.
    op.create_table(
        "run_skill_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column("ordered_items", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('FROZEN', 'UNKNOWN', 'STALE')",
            name="ck_orch_run_skill_snapshots_status",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_run_skill_snapshots_digest",
        ),
        _project_fk("fk_orch_run_skill_snapshots_project"),
        sa.UniqueConstraint(
            "project_id",
            "workflow_run_id",
            name="uq_orch_run_skill_snapshots_run",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_run_skill_snapshots_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_run_skill_snapshots_project_run",
        "run_skill_snapshots",
        ["project_id", "workflow_run_id"],
        schema=SCHEMA,
    )

    # --- Source artifacts and import revisions ------------------------------
    op.create_table(
        "source_artifacts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(200), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("logical_role", sa.String(200), nullable=False),
        sa.Column("storage_uri", sa.String(500), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(source_kind) BETWEEN 1 AND 64",
            name="ck_orch_source_artifacts_kind",
        ),
        sa.CheckConstraint(
            SHA256.format(column="content_digest"),
            name="ck_orch_source_artifacts_digest",
        ),
        sa.CheckConstraint(
            "byte_size > 0", name="ck_orch_source_artifacts_byte_size"
        ),
        _project_fk("fk_orch_source_artifacts_project"),
        sa.UniqueConstraint(
            "project_id",
            "content_digest",
            "source_kind",
            name="uq_orch_source_artifacts_content",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_source_artifacts_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_source_artifacts_project_digest",
        "source_artifacts",
        ["project_id", "content_digest"],
        schema=SCHEMA,
    )

    op.create_table(
        "source_import_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "source_artifact_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("imported_by_actor", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_source_import_revisions_positive"
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_source_import_revisions_digest",
        ),
        _project_fk("fk_orch_source_import_revisions_project"),
        sa.ForeignKeyConstraint(
            ["source_artifact_id", "project_id"],
            [
                f"{SCHEMA}.source_artifacts.id",
                f"{SCHEMA}.source_artifacts.project_id",
            ],
            name="fk_orch_source_import_revisions_artifact",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "source_artifact_id",
            "revision",
            name="uq_orch_source_import_revisions_number",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_source_import_revisions_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_source_import_revisions_artifact",
        "source_import_revisions",
        ["project_id", "source_artifact_id", "revision"],
        schema=SCHEMA,
    )

    # --- Shot plan revisions and ordered units ------------------------------
    op.create_table(
        "shot_plan_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("work_unit_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_shot_plan_revisions_positive"
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_shot_plan_revisions_command_length",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_shot_plan_revisions_digest",
        ),
        _project_fk("fk_orch_shot_plan_revisions_project"),
        sa.ForeignKeyConstraint(
            ["work_unit_id", "project_id"],
            [f"{SCHEMA}.work_units.id", f"{SCHEMA}.work_units.project_id"],
            name="fk_orch_shot_plan_revisions_work_unit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "work_unit_id",
            "revision",
            name="uq_orch_shot_plan_revisions_number",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_shot_plan_revisions_command",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_shot_plan_revisions_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_shot_plan_revisions_work_unit",
        "shot_plan_revisions",
        ["project_id", "work_unit_id", "revision"],
        schema=SCHEMA,
    )

    op.create_table(
        "shot_plan_units",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "shot_plan_revision_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("unit_key", sa.String(200), nullable=False),
        sa.Column("unit_kind", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "ordinal > 0", name="ck_orch_shot_plan_units_ordinal"
        ),
        sa.CheckConstraint(
            "length(unit_key) BETWEEN 1 AND 200",
            name="ck_orch_shot_plan_units_unit_key",
        ),
        sa.CheckConstraint(
            "length(unit_kind) BETWEEN 1 AND 64",
            name="ck_orch_shot_plan_units_unit_kind",
        ),
        _project_fk("fk_orch_shot_plan_units_project"),
        sa.ForeignKeyConstraint(
            ["shot_plan_revision_id", "project_id"],
            [
                f"{SCHEMA}.shot_plan_revisions.id",
                f"{SCHEMA}.shot_plan_revisions.project_id",
            ],
            name="fk_orch_shot_plan_units_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "shot_plan_revision_id",
            "ordinal",
            name="uq_orch_shot_plan_units_ordinal",
        ),
        sa.UniqueConstraint(
            "project_id",
            "shot_plan_revision_id",
            "unit_key",
            name="uq_orch_shot_plan_units_key",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_shot_plan_units_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_shot_plan_units_revision_ordinal",
        "shot_plan_units",
        ["project_id", "shot_plan_revision_id", "ordinal"],
        schema=SCHEMA,
    )

    # --- Separate generation and QC policy revisions ------------------------
    op.create_table(
        "generation_strategy_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("strategy_key", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_generation_strategy_positive"
        ),
        sa.CheckConstraint(
            "length(strategy_key) BETWEEN 1 AND 120",
            name="ck_orch_generation_strategy_key_length",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_generation_strategy_command_length",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_generation_strategy_digest",
        ),
        _project_fk("fk_orch_generation_strategy_project"),
        sa.UniqueConstraint(
            "project_id",
            "strategy_key",
            "revision",
            name="uq_orch_generation_strategy_number",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_generation_strategy_command",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_generation_strategy_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_generation_strategy_project_key",
        "generation_strategy_revisions",
        ["project_id", "strategy_key", "revision"],
        schema=SCHEMA,
    )

    op.create_table(
        "factory_qc_policy_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("policy_key", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "command_idempotency_key", sa.String(255), nullable=False
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_factory_qc_policy_positive"
        ),
        sa.CheckConstraint(
            "length(policy_key) BETWEEN 1 AND 120",
            name="ck_orch_factory_qc_policy_key_length",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_factory_qc_policy_command_length",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_factory_qc_policy_digest",
        ),
        _project_fk("fk_orch_factory_qc_policy_project"),
        sa.UniqueConstraint(
            "project_id",
            "policy_key",
            "revision",
            name="uq_orch_factory_qc_policy_number",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_factory_qc_policy_command",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_factory_qc_policy_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_factory_qc_policy_project_key",
        "factory_qc_policy_revisions",
        ["project_id", "policy_key", "revision"],
        schema=SCHEMA,
    )

    # --- Repair and mode-change proposals -----------------------------------
    op.create_table(
        "repair_proposals",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("proposal_key", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("target_kind", sa.String(32), nullable=False),
        sa.Column("target_ref", sa.String(200), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_repair_proposals_positive"
        ),
        sa.CheckConstraint(
            "length(proposal_key) BETWEEN 1 AND 120",
            name="ck_orch_repair_proposals_key_length",
        ),
        sa.CheckConstraint(
            "target_kind IN ('shot_plan', 'operation_run', 'artifact', "
            "'selection')",
            name="ck_orch_repair_proposals_target_kind",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_repair_proposals_digest",
        ),
        _project_fk("fk_orch_repair_proposals_project"),
        sa.UniqueConstraint(
            "project_id",
            "proposal_key",
            "revision",
            name="uq_orch_repair_proposals_number",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_repair_proposals_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_repair_proposals_project_key",
        "repair_proposals",
        ["project_id", "proposal_key", "revision"],
        schema=SCHEMA,
    )

    op.create_table(
        "mode_change_proposals",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("proposal_key", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_mode_change_proposals_positive"
        ),
        sa.CheckConstraint(
            "length(proposal_key) BETWEEN 1 AND 120",
            name="ck_orch_mode_change_proposals_key_length",
        ),
        sa.CheckConstraint(
            "mode IN ('draft', 'assisted', 'autonomous')",
            name="ck_orch_mode_change_proposals_mode",
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_mode_change_proposals_digest",
        ),
        _project_fk("fk_orch_mode_change_proposals_project"),
        sa.UniqueConstraint(
            "project_id",
            "proposal_key",
            "revision",
            name="uq_orch_mode_change_proposals_number",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_mode_change_proposals_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_mode_change_proposals_project_key",
        "mode_change_proposals",
        ["project_id", "proposal_key", "revision"],
        schema=SCHEMA,
    )

    # --- Delivery revisions --------------------------------------------------
    op.create_table(
        "delivery_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_orch_delivery_revisions_positive"
        ),
        sa.CheckConstraint(
            SHA256.format(column="digest"),
            name="ck_orch_delivery_revisions_digest",
        ),
        _project_fk("fk_orch_delivery_revisions_project"),
        sa.UniqueConstraint(
            "project_id",
            "revision",
            name="uq_orch_delivery_revisions_number",
        ),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_delivery_revisions_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_delivery_revisions_project_revision",
        "delivery_revisions",
        ["project_id", "revision"],
        schema=SCHEMA,
    )

    # --- Immutable fact guards ----------------------------------------------
    immutable_tables = (
        "project_templates",
        "skill_revisions",
        "run_skill_snapshots",
        "source_artifacts",
        "source_import_revisions",
        "shot_plan_revisions",
        "shot_plan_units",
        "generation_strategy_revisions",
        "factory_qc_policy_revisions",
        "repair_proposals",
        "mode_change_proposals",
        "delivery_revisions",
    )
    for table_name in immutable_tables:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON orchestration.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION orchestration.reject_immutable_fact_mutation()
            """
        )

    product_tables = immutable_tables + (
        "factory_project_bindings",
        "work_units",
        "folder_projections",
        "skills",
        "project_skill_bindings",
    )
    immutable_table_list = ", ".join(
        f"orchestration.{table}" for table in immutable_tables
    )
    mutable_table_list = ", ".join(
        f"orchestration.{table}"
        for table in product_tables
        if table not in immutable_tables
    )
    op.execute(
        "REVOKE ALL ON TABLE "
        + ", ".join(f"orchestration.{table}" for table in product_tables)
        + " FROM PUBLIC"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}'
            ) THEN
                GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE};
                GRANT SELECT, INSERT ON TABLE {immutable_table_list}
                    TO {ROLE};
                GRANT SELECT, INSERT, UPDATE ON TABLE {mutable_table_list}
                    TO {ROLE};
                ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA}
                    GRANT SELECT ON TABLES TO {ROLE};
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
            "SELECT 1 FROM orchestration.project_templates "
            "UNION ALL SELECT 1 FROM orchestration.factory_project_bindings "
            "UNION ALL SELECT 1 FROM orchestration.work_units "
            "UNION ALL SELECT 1 FROM orchestration.folder_projections "
            "UNION ALL SELECT 1 FROM orchestration.skills "
            "UNION ALL SELECT 1 FROM orchestration.skill_revisions "
            "UNION ALL SELECT 1 FROM orchestration.project_skill_bindings "
            "UNION ALL SELECT 1 FROM orchestration.run_skill_snapshots "
            "UNION ALL SELECT 1 FROM orchestration.source_artifacts "
            "UNION ALL SELECT 1 FROM orchestration.source_import_revisions "
            "UNION ALL SELECT 1 FROM orchestration.shot_plan_revisions "
            "UNION ALL SELECT 1 FROM orchestration.shot_plan_units "
            "UNION ALL SELECT 1 FROM orchestration.generation_strategy_revisions "
            "UNION ALL SELECT 1 FROM orchestration.factory_qc_policy_revisions "
            "UNION ALL SELECT 1 FROM orchestration.repair_proposals "
            "UNION ALL SELECT 1 FROM orchestration.mode_change_proposals "
            "UNION ALL SELECT 1 FROM orchestration.delivery_revisions)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_PRODUCT_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orch_0020 downgrade would delete durable product facts; set "
            "ALLOW_DESTRUCTIVE_PRODUCT_DOWNGRADE=YES only after backup"
        )

    immutable_tables = (
        "project_templates",
        "skill_revisions",
        "run_skill_snapshots",
        "source_artifacts",
        "source_import_revisions",
        "shot_plan_revisions",
        "shot_plan_units",
        "generation_strategy_revisions",
        "factory_qc_policy_revisions",
        "repair_proposals",
        "mode_change_proposals",
        "delivery_revisions",
    )
    for table_name in immutable_tables:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable "
            f"ON orchestration.{table_name}"
        )

    for table_name in (
        "delivery_revisions",
        "mode_change_proposals",
        "repair_proposals",
        "factory_qc_policy_revisions",
        "generation_strategy_revisions",
        "shot_plan_units",
        "shot_plan_revisions",
        "source_import_revisions",
        "source_artifacts",
        "run_skill_snapshots",
        "project_skill_bindings",
        "skill_revisions",
        "skills",
        "folder_projections",
        "work_units",
        "factory_project_bindings",
    ):
        op.drop_table(table_name, schema=SCHEMA)

    op.drop_index(
        "ix_orch_projects_template",
        table_name="projects",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_orch_projects_template",
        "projects",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_orch_projects_template_version",
        "projects",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_orch_projects_template_key_length",
        "projects",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column("projects", "template_version", schema=SCHEMA)
    op.drop_column("projects", "template_key", schema=SCHEMA)

    op.drop_index(
        "ix_orch_project_templates_key_version",
        table_name="project_templates",
        schema=SCHEMA,
    )
    op.drop_table("project_templates", schema=SCHEMA)
