"""Add immutable AMD H3 episode and runtime domain bindings.

Revision ID: orch_0033
Revises: orch_0032
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "orch_0033"
down_revision = "orch_0032"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"
ROLE = "creative_orchestrator_app"


def _sha256(column: str, name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} ~ '^[0-9a-f]{{64}}$'", name=name)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.add_column(
        "qc_evaluation_facts",
        sa.Column("h3_qc", sa.JSON(), nullable=True),
        schema=SCHEMA,
    )
    op.create_table(
        "project_creative_ir_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_pack_revision_id", sa.Uuid(), nullable=False),
        sa.Column("trial_script_revision_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("revision_digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_project_creative_ir_scope"
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "revision_digest",
            name="uq_orch_project_creative_ir_identity",
        ),
        sa.UniqueConstraint(
            "project_id",
            "revision_digest",
            name="uq_orch_project_creative_ir_digest",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_project_creative_ir_command",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_project_creative_ir_command_length",
        ),
        _sha256("revision_digest", "ck_orch_project_creative_ir_digest"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_project_creative_ir_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_pack_revision_id", "project_id"],
            [
                f"{SCHEMA}.evidence_pack_revisions.id",
                f"{SCHEMA}.evidence_pack_revisions.project_id",
            ],
            name="fk_orch_project_creative_ir_evidence_pack",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trial_script_revision_id", "project_id"],
            [
                f"{SCHEMA}.trial_script_revisions.id",
                f"{SCHEMA}.trial_script_revisions.project_id",
            ],
            name="fk_orch_project_creative_ir_trial_script",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_project_creative_ir_project_created",
        "project_creative_ir_revisions",
        ["project_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "character_source_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("historical", sa.Boolean(), nullable=False),
        sa.Column("ai_derived", sa.Boolean(), nullable=False),
        sa.Column("uploaded_by", sa.String(160), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_character_source_assets_scope"
        ),
        sa.UniqueConstraint(
            "project_id",
            "artifact_id",
            name="uq_orch_character_source_assets_artifact",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_character_source_assets_command",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_character_source_assets_command_length",
        ),
        sa.CheckConstraint(
            "verified AND historical AND NOT ai_derived",
            name="ck_orch_character_source_assets_provenance",
        ),
        sa.CheckConstraint(
            "length(uploaded_by) BETWEEN 1 AND 160",
            name="ck_orch_character_source_assets_uploader",
        ),
        _sha256("content_digest", "ck_orch_character_source_assets_digest"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_character_source_assets_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "project_id"],
            [f"{SCHEMA}.artifacts.id", f"{SCHEMA}.artifacts.project_id"],
            name="fk_orch_character_source_assets_artifact",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "character_reference_set_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("reference_set_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(160), nullable=False),
        sa.Column("age_stage", sa.String(160), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("model_family", sa.String(64), nullable=False),
        sa.Column("model_revision", sa.String(100), nullable=False),
        sa.Column("workflow_digest", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reference_set_digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_character_reference_sets_scope",
        ),
        sa.UniqueConstraint(
            "project_id",
            "reference_set_id",
            "reference_set_digest",
            name="uq_orch_character_reference_sets_revision",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_character_reference_sets_command",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_character_reference_sets_command_length",
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'generating', 'qc_pending', "
            "'needs_manual_source_fix', 'frozen')",
            name="ck_orch_character_reference_sets_state",
        ),
        sa.CheckConstraint(
            "model_family = 'flux2-dev' AND "
            "model_revision = 'flux2-dev-fp8mixed.v1'",
            name="ck_orch_character_reference_sets_model",
        ),
        _sha256(
            "workflow_digest", "ck_orch_character_reference_sets_workflow_digest"
        ),
        _sha256(
            "reference_set_digest", "ck_orch_character_reference_sets_digest"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_character_reference_sets_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "project_id"],
            [
                f"{SCHEMA}.character_source_assets.id",
                f"{SCHEMA}.character_source_assets.project_id",
            ],
            name="fk_orch_character_reference_sets_source",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_character_reference_sets_character",
        "character_reference_set_revisions",
        ["project_id", "character_id", "age_stage", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "character_reference_view_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("reference_set_revision_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("view_name", sa.String(32), nullable=False),
        sa.Column("attempt_ordinal", sa.Integer(), nullable=False),
        sa.Column("image_digest", sa.String(64), nullable=False),
        sa.Column("ai_derived", sa.Boolean(), nullable=False),
        sa.Column("historical", sa.Boolean(), nullable=False),
        sa.Column("identity_control", sa.Boolean(), nullable=False),
        sa.Column("single_view_qc_passed", sa.Boolean(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_character_reference_views_scope"
        ),
        sa.UniqueConstraint(
            "reference_set_revision_id",
            "project_id",
            "view_name",
            name="uq_orch_character_reference_views_name",
        ),
        sa.UniqueConstraint(
            "project_id",
            "artifact_id",
            name="uq_orch_character_reference_views_artifact",
        ),
        sa.CheckConstraint(
            "view_name IN ('front', 'three_quarter_left', 'profile_left')",
            name="ck_orch_character_reference_views_name",
        ),
        sa.CheckConstraint(
            "attempt_ordinal BETWEEN 0 AND 1",
            name="ck_orch_character_reference_views_attempt",
        ),
        sa.CheckConstraint(
            "ai_derived AND NOT historical AND identity_control",
            name="ck_orch_character_reference_views_provenance",
        ),
        _sha256("image_digest", "ck_orch_character_reference_views_digest"),
        sa.ForeignKeyConstraint(
            ["reference_set_revision_id", "project_id"],
            [
                f"{SCHEMA}.character_reference_set_revisions.id",
                f"{SCHEMA}.character_reference_set_revisions.project_id",
            ],
            name="fk_orch_character_reference_views_set",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "project_id"],
            [f"{SCHEMA}.artifacts.id", f"{SCHEMA}.artifacts.project_id"],
            name="fk_orch_character_reference_views_artifact",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "episode_generation_ir_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("project_ir_id", sa.Uuid(), nullable=False),
        sa.Column("project_ir_revision_digest", sa.String(64), nullable=False),
        sa.Column("model_family", sa.String(64), nullable=False),
        sa.Column("duration_allocation_digest", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("revision_digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_episode_generation_ir_scope"
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "revision_digest",
            name="uq_orch_episode_generation_ir_identity",
        ),
        sa.UniqueConstraint(
            "project_id",
            "revision_digest",
            name="uq_orch_episode_generation_ir_digest",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_episode_generation_ir_command",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_episode_generation_ir_command_length",
        ),
        sa.CheckConstraint(
            "model_family = 'minimax-h3'",
            name="ck_orch_episode_generation_ir_model",
        ),
        _sha256(
            "project_ir_revision_digest",
            "ck_orch_episode_generation_ir_project_digest",
        ),
        _sha256(
            "duration_allocation_digest",
            "ck_orch_episode_generation_ir_duration_digest",
        ),
        _sha256("revision_digest", "ck_orch_episode_generation_ir_digest"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{SCHEMA}.projects.id"],
            name="fk_orch_episode_generation_ir_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_ir_id", "project_id", "project_ir_revision_digest"],
            [
                f"{SCHEMA}.project_creative_ir_revisions.id",
                f"{SCHEMA}.project_creative_ir_revisions.project_id",
                f"{SCHEMA}.project_creative_ir_revisions.revision_digest",
            ],
            name="fk_orch_episode_generation_ir_project_ir",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_episode_generation_ir_project_created",
        "episode_generation_ir_revisions",
        ["project_id", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "h3_sequence_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("episode_revision_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("frame_count", sa.Integer(), nullable=False),
        sa.Column("fps", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("plan_payload", sa.JSON(), nullable=False),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column("prompt_digest", sa.String(64), nullable=False),
        sa.Column("workflow_digest", sa.String(64), nullable=False),
        sa.Column("selection_head_id", sa.Uuid(), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_h3_sequence_revisions_scope"
        ),
        sa.UniqueConstraint(
            "episode_revision_id",
            "project_id",
            "sequence_id",
            name="uq_orch_h3_sequence_revisions_sequence",
        ),
        sa.UniqueConstraint(
            "episode_revision_id",
            "project_id",
            "ordinal",
            name="uq_orch_h3_sequence_revisions_ordinal",
        ),
        sa.UniqueConstraint(
            "project_id",
            "selection_head_id",
            name="uq_orch_h3_sequence_revisions_selection",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_h3_sequence_revisions_command",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_h3_sequence_revisions_command_length",
        ),
        sa.CheckConstraint(
            "ordinal > 0", name="ck_orch_h3_sequence_revisions_ordinal"
        ),
        sa.CheckConstraint(
            "mode = 'ref2va' AND fps = 24",
            name="ck_orch_h3_sequence_revisions_mode",
        ),
        sa.CheckConstraint(
            "frame_count BETWEEN 124 AND 362 AND frame_count % 17 = 5",
            name="ck_orch_h3_sequence_revisions_frame_grid",
        ),
        _sha256("plan_digest", "ck_orch_h3_sequence_revisions_plan_digest"),
        _sha256("prompt_digest", "ck_orch_h3_sequence_revisions_prompt_digest"),
        _sha256(
            "workflow_digest", "ck_orch_h3_sequence_revisions_workflow_digest"
        ),
        sa.ForeignKeyConstraint(
            ["episode_revision_id", "project_id"],
            [
                f"{SCHEMA}.episode_generation_ir_revisions.id",
                f"{SCHEMA}.episode_generation_ir_revisions.project_id",
            ],
            name="fk_orch_h3_sequence_revisions_episode",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selection_head_id", "project_id"],
            [f"{SCHEMA}.selection_heads.id", f"{SCHEMA}.selection_heads.project_id"],
            name="fk_orch_h3_sequence_revisions_selection",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_h3_sequence_revisions_episode",
        "h3_sequence_revisions",
        ["project_id", "episode_revision_id", "ordinal"],
        schema=SCHEMA,
    )

    op.create_table(
        "h3_runtime_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_revision_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_ordinal", sa.Integer(), nullable=False),
        sa.Column("operation_run_id", sa.Uuid(), nullable=False),
        sa.Column("operation_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_digest", sa.String(64), nullable=False),
        sa.Column("qc_evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("qc_gate_key", sa.String(200), nullable=False),
        sa.Column("repair_of_attempt_id", sa.Uuid()),
        sa.Column("repair_of_attempt_ordinal", sa.Integer()),
        sa.Column(
            "repair_trigger_codes",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("prompt_digest", sa.String(64), nullable=False),
        sa.Column("workflow_digest", sa.String(64), nullable=False),
        sa.Column("source_lineage_payload", sa.JSON(), nullable=False),
        sa.Column("source_lineage_digest", sa.String(64), nullable=False),
        sa.Column("command_idempotency_key", sa.String(255), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_orch_h3_runtime_attempts_scope"
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "sequence_revision_id",
            name="uq_orch_h3_runtime_attempts_sequence_scope",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "sequence_revision_id",
            "attempt_ordinal",
            name="uq_orch_h3_runtime_attempts_repair_scope",
        ),
        sa.UniqueConstraint(
            "sequence_revision_id",
            "project_id",
            "attempt_ordinal",
            name="uq_orch_h3_runtime_attempts_ordinal",
        ),
        sa.UniqueConstraint(
            "project_id",
            "command_idempotency_key",
            name="uq_orch_h3_runtime_attempts_command",
        ),
        sa.CheckConstraint(
            "length(command_idempotency_key) BETWEEN 1 AND 255",
            name="ck_orch_h3_runtime_attempts_command_length",
        ),
        sa.CheckConstraint(
            "attempt_ordinal BETWEEN 0 AND 1",
            name="ck_orch_h3_runtime_attempts_ordinal",
        ),
        sa.CheckConstraint(
            "(attempt_ordinal = 0 AND repair_of_attempt_id IS NULL "
            "AND repair_of_attempt_ordinal IS NULL "
            "AND json_array_length(repair_trigger_codes) = 0) OR "
            "(attempt_ordinal = 1 AND repair_of_attempt_id IS NOT NULL "
            "AND repair_of_attempt_ordinal = 0 "
            "AND json_array_length(repair_trigger_codes) > 0)",
            name="ck_orch_h3_runtime_attempts_repair",
        ),
        sa.CheckConstraint(
            "length(trim(qc_gate_key)) > 0",
            name="ck_orch_h3_runtime_attempts_qc_gate",
        ),
        _sha256("artifact_digest", "ck_orch_h3_runtime_attempts_artifact_digest"),
        _sha256("prompt_digest", "ck_orch_h3_runtime_attempts_prompt_digest"),
        _sha256("workflow_digest", "ck_orch_h3_runtime_attempts_workflow_digest"),
        _sha256(
            "source_lineage_digest", "ck_orch_h3_runtime_attempts_lineage_digest"
        ),
        sa.ForeignKeyConstraint(
            ["sequence_revision_id", "project_id"],
            [
                f"{SCHEMA}.h3_sequence_revisions.id",
                f"{SCHEMA}.h3_sequence_revisions.project_id",
            ],
            name="fk_orch_h3_runtime_attempts_sequence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_attempt_id", "operation_run_id", "project_id"],
            [
                f"{SCHEMA}.operation_attempts.id",
                f"{SCHEMA}.operation_attempts.operation_run_id",
                f"{SCHEMA}.operation_attempts.project_id",
            ],
            name="fk_orch_h3_runtime_attempts_operation_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "artifact_id",
                "project_id",
                "operation_run_id",
                "operation_attempt_id",
                "artifact_digest",
            ],
            [
                f"{SCHEMA}.artifacts.id",
                f"{SCHEMA}.artifacts.project_id",
                f"{SCHEMA}.artifacts.operation_run_id",
                f"{SCHEMA}.artifacts.operation_attempt_id",
                f"{SCHEMA}.artifacts.content_digest",
            ],
            name="fk_orch_h3_runtime_attempts_artifact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "qc_evaluation_id",
                "project_id",
                "artifact_id",
                "artifact_digest",
                "qc_gate_key",
            ],
            [
                f"{SCHEMA}.qc_evaluation_facts.id",
                f"{SCHEMA}.qc_evaluation_facts.project_id",
                f"{SCHEMA}.qc_evaluation_facts.artifact_id",
                f"{SCHEMA}.qc_evaluation_facts.artifact_digest",
                f"{SCHEMA}.qc_evaluation_facts.gate_key",
            ],
            name="fk_orch_h3_runtime_attempts_qc",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "repair_of_attempt_id",
                "project_id",
                "sequence_revision_id",
                "repair_of_attempt_ordinal",
            ],
            [
                f"{SCHEMA}.h3_runtime_attempts.id",
                f"{SCHEMA}.h3_runtime_attempts.project_id",
                f"{SCHEMA}.h3_runtime_attempts.sequence_revision_id",
                f"{SCHEMA}.h3_runtime_attempts.attempt_ordinal",
            ],
            name="fk_orch_h3_runtime_attempts_repair_parent_ordinal",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_h3_runtime_attempts_sequence",
        "h3_runtime_attempts",
        ["project_id", "sequence_revision_id", "attempt_ordinal"],
        schema=SCHEMA,
    )

    op.create_table(
        "video_job_sequence_projections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("video_job_projection_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_revision_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("selected_attempt_id", sa.Uuid()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "state_version", sa.Integer(), nullable=False, server_default="0"
        ),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_video_job_sequence_projections_scope",
        ),
        sa.UniqueConstraint(
            "video_job_projection_id",
            "project_id",
            "sequence_revision_id",
            name="uq_orch_video_job_sequence_projections_sequence",
        ),
        sa.UniqueConstraint(
            "video_job_projection_id",
            "project_id",
            "ordinal",
            name="uq_orch_video_job_sequence_projections_ordinal",
        ),
        sa.CheckConstraint(
            "ordinal > 0",
            name="ck_orch_video_job_sequence_projections_ordinal",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_orch_video_job_sequence_projections_version",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'generating_initial', 'qc_initial', "
            "'repair_planned', 'generating_repair', 'qc_repair', "
            "'selecting_best', 'selected_clean', "
            "'selected_with_qc_exception', 'ready_for_assembly', "
            "'assembled', 'delivered', 'runtime_error')",
            name="ck_orch_video_job_sequence_projections_status",
        ),
        sa.ForeignKeyConstraint(
            ["video_job_projection_id", "project_id"],
            [
                f"{SCHEMA}.video_job_projections.id",
                f"{SCHEMA}.video_job_projections.project_id",
            ],
            name="fk_orch_video_job_sequence_projections_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sequence_revision_id", "project_id"],
            [
                f"{SCHEMA}.h3_sequence_revisions.id",
                f"{SCHEMA}.h3_sequence_revisions.project_id",
            ],
            name="fk_orch_video_job_sequence_projections_sequence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_attempt_id", "project_id", "sequence_revision_id"],
            [
                f"{SCHEMA}.h3_runtime_attempts.id",
                f"{SCHEMA}.h3_runtime_attempts.project_id",
                f"{SCHEMA}.h3_runtime_attempts.sequence_revision_id",
            ],
            name="fk_orch_video_job_sequence_projections_attempt",
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_video_job_sequence_projections_job",
        "video_job_sequence_projections",
        ["project_id", "video_job_projection_id", "ordinal"],
        schema=SCHEMA,
    )

    immutable_tables = (
        "project_creative_ir_revisions",
        "character_source_assets",
        "character_reference_set_revisions",
        "character_reference_view_assets",
        "episode_generation_ir_revisions",
        "h3_sequence_revisions",
        "h3_runtime_attempts",
    )
    for table in immutable_tables:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.reject_immutable_fact_mutation()
            """
        )
    all_tables = (*immutable_tables, "video_job_sequence_projections")
    op.execute(
        "REVOKE ALL ON TABLE "
        + ", ".join(f"{SCHEMA}.{table}" for table in all_tables)
        + " FROM PUBLIC"
    )
    immutable_sql = ", ".join(
        f"{SCHEMA}.{table}" for table in immutable_tables
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                GRANT SELECT, INSERT ON TABLE {immutable_sql} TO {ROLE};
                GRANT SELECT, INSERT, UPDATE ON TABLE
                    {SCHEMA}.video_job_sequence_projections TO {ROLE};
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    immutable_tables = (
        "h3_runtime_attempts",
        "h3_sequence_revisions",
        "episode_generation_ir_revisions",
        "character_reference_view_assets",
        "character_reference_set_revisions",
        "character_source_assets",
        "project_creative_ir_revisions",
    )
    op.drop_index(
        "ix_orch_video_job_sequence_projections_job",
        table_name="video_job_sequence_projections",
        schema=SCHEMA,
    )
    op.drop_table("video_job_sequence_projections", schema=SCHEMA)
    for table in immutable_tables:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {SCHEMA}.{table}"
        )
        if table == "h3_runtime_attempts":
            op.drop_index(
                "ix_orch_h3_runtime_attempts_sequence",
                table_name=table,
                schema=SCHEMA,
            )
        elif table == "h3_sequence_revisions":
            op.drop_index(
                "ix_orch_h3_sequence_revisions_episode",
                table_name=table,
                schema=SCHEMA,
            )
        elif table == "episode_generation_ir_revisions":
            op.drop_index(
                "ix_orch_episode_generation_ir_project_created",
                table_name=table,
                schema=SCHEMA,
            )
        elif table == "character_reference_set_revisions":
            op.drop_index(
                "ix_orch_character_reference_sets_character",
                table_name=table,
                schema=SCHEMA,
            )
        elif table == "project_creative_ir_revisions":
            op.drop_index(
                "ix_orch_project_creative_ir_project_created",
                table_name=table,
                schema=SCHEMA,
            )
        op.drop_table(table, schema=SCHEMA)
    op.drop_column("qc_evaluation_facts", "h3_qc", schema=SCHEMA)
