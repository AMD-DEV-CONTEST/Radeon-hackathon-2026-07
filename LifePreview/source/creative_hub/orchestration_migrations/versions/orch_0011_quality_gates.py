"""Add immutable QC, gate policy, Gold, and certification facts.

Revision ID: orch_0011
Revises: orch_0010
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "orch_0011"
down_revision = "orch_0010"
branch_labels = None
depends_on = None
SCHEMA = "orchestration"
SHA256 = "length({column}) = 64"


def _project_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id"],
        [f"{SCHEMA}.projects.id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "qc_prompt_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("prompt_key", sa.String(120), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("prompt_digest", sa.String(64), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(as_uuid=True)),
        sa.Column("created_by_actor", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("revision > 0", name="ck_orch_qc_prompt_revision"),
        sa.CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_prompt_stage",
        ),
        sa.CheckConstraint(
            SHA256.format(column="prompt_digest"),
            name="ck_orch_qc_prompt_digest",
        ),
        _project_fk("fk_orch_qc_prompt_project"),
        sa.ForeignKeyConstraint(
            ["parent_revision_id", "project_id"],
            [
                f"{SCHEMA}.qc_prompt_revisions.id",
                f"{SCHEMA}.qc_prompt_revisions.project_id",
            ],
            name="fk_orch_qc_prompt_parent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "prompt_key",
            "stage",
            "revision",
            name="uq_orch_qc_prompt_revision",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "prompt_digest",
            name="uq_orch_qc_prompt_identity",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_prompt_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_qc_prompt_head",
        "qc_prompt_revisions",
        ["project_id", "prompt_key", "stage", "revision"],
        schema=SCHEMA,
    )

    op.create_table(
        "qc_gate_policy_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("gate_key", sa.String(200), nullable=False),
        sa.Column("review_mode", sa.String(24), nullable=False),
        sa.Column(
            "machine_qc_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("ranking_revision", sa.String(100), nullable=False),
        sa.Column("ranking_weights", sa.JSON(), nullable=False),
        sa.Column("prompt_revision_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rubric_revision_id", sa.String(200), nullable=False),
        sa.Column("evaluator_bundle_digest", sa.String(64), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_gate_policy_stage",
        ),
        sa.CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_qc_gate_policy_gate_key",
        ),
        sa.CheckConstraint(
            "review_mode IN ('ALL', 'EXCEPTIONS_ONLY', 'OFF')",
            name="ck_orch_qc_gate_policy_review",
        ),
        sa.CheckConstraint(
            "machine_qc_required = true",
            name="ck_orch_qc_gate_machine_mandatory",
        ),
        sa.CheckConstraint(
            SHA256.format(column="policy_digest"),
            name="ck_orch_qc_gate_policy_digest",
        ),
        sa.CheckConstraint(
            SHA256.format(column="evaluator_bundle_digest"),
            name="ck_orch_qc_gate_evaluator",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{SCHEMA}.workflow_runs.id",
                f"{SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_qc_gate_policy_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_revision_id", "project_id"],
            [
                f"{SCHEMA}.qc_prompt_revisions.id",
                f"{SCHEMA}.qc_prompt_revisions.project_id",
            ],
            name="fk_orch_qc_gate_policy_prompt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            name="uq_orch_qc_gate_policy_stage",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_gate_policy_scope",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "gate_key",
            name="uq_orch_qc_gate_policy_gate_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_qc_gate_policy_workflow",
        "qc_gate_policy_snapshots",
        ["project_id", "workflow_run_id", "gate_key"],
        schema=SCHEMA,
    )

    op.create_table(
        "qc_evaluation_facts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("gate_key", sa.String(200), nullable=False),
        sa.Column("artifact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("artifact_digest", sa.String(64), nullable=False),
        sa.Column(
            "artifact_operation_run_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column(
            "artifact_operation_attempt_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        sa.Column("evidence_pack_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evidence_pack_digest", sa.String(64), nullable=False),
        sa.Column("expected_selection_version", sa.Integer(), nullable=False),
        sa.Column("prompt_revision_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("prompt_digest", sa.String(64), nullable=False),
        sa.Column("rubric_revision_id", sa.String(200), nullable=False),
        sa.Column("rubric_digest", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("model_version", sa.String(200), nullable=False),
        sa.Column("implementation_digest", sa.String(64), nullable=False),
        sa.Column("evaluator_bundle_digest", sa.String(64), nullable=False),
        sa.Column("judgment", sa.String(8), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("defects", sa.JSON(), nullable=False),
        sa.Column("recommended_actions", sa.JSON(), nullable=False),
        sa.Column("repair_result", sa.JSON(), nullable=False),
        sa.Column("evaluation_digest", sa.String(64), nullable=False),
        sa.Column(
            "evaluated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_evaluation_stage",
        ),
        sa.CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_qc_evaluation_gate_key",
        ),
        sa.CheckConstraint(
            "judgment IN ('PASS', 'FAIL')",
            name="ck_orch_qc_evaluation_judgment",
        ),
        sa.CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1000000",
            name="ck_orch_qc_evaluation_score",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1000000",
            name="ck_orch_qc_evaluation_confidence",
        ),
        sa.CheckConstraint(
            "expected_selection_version >= 0",
            name="ck_orch_qc_evaluation_selection_version",
        ),
        sa.CheckConstraint(
            SHA256.format(column="artifact_digest"),
            name="ck_orch_qc_evaluation_artifact_digest",
        ),
        sa.CheckConstraint(
            SHA256.format(column="evidence_pack_digest"),
            name="ck_orch_qc_evaluation_evidence_digest",
        ),
        sa.CheckConstraint(
            SHA256.format(column="prompt_digest"),
            name="ck_orch_qc_evaluation_prompt_digest",
        ),
        sa.CheckConstraint(
            SHA256.format(column="rubric_digest"),
            name="ck_orch_qc_evaluation_rubric_digest",
        ),
        sa.CheckConstraint(
            SHA256.format(column="implementation_digest"),
            name="ck_orch_qc_evaluation_implementation",
        ),
        sa.CheckConstraint(
            SHA256.format(column="evaluator_bundle_digest"),
            name="ck_orch_qc_evaluation_evaluator",
        ),
        sa.CheckConstraint(
            SHA256.format(column="evaluation_digest"),
            name="ck_orch_qc_evaluation_digest",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{SCHEMA}.workflow_runs.id",
                f"{SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_qc_evaluation_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_revision_id", "project_id", "prompt_digest"],
            [
                f"{SCHEMA}.qc_prompt_revisions.id",
                f"{SCHEMA}.qc_prompt_revisions.project_id",
                f"{SCHEMA}.qc_prompt_revisions.prompt_digest",
            ],
            name="fk_orch_qc_evaluation_prompt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "artifact_id",
                "project_id",
                "artifact_operation_run_id",
                "artifact_operation_attempt_id",
                "artifact_digest",
            ],
            [
                f"{SCHEMA}.artifacts.id",
                f"{SCHEMA}.artifacts.project_id",
                f"{SCHEMA}.artifacts.operation_run_id",
                f"{SCHEMA}.artifacts.operation_attempt_id",
                f"{SCHEMA}.artifacts.content_digest",
            ],
            name="fk_orch_qc_evaluation_artifact",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "artifact_id",
            "artifact_digest",
            "gate_key",
            name="uq_orch_qc_evaluation_identity",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_qc_evaluation_artifact",
        "qc_evaluation_facts",
        [
            "project_id",
            "workflow_run_id",
            "gate_key",
            "artifact_id",
            "evaluated_at",
        ],
        schema=SCHEMA,
    )

    op.create_table(
        "qc_candidate_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("gate_key", sa.String(200), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("artifact_digest", sa.String(64), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("generation_usage", sa.JSON(), nullable=False),
        sa.Column("candidate_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_candidate_stage",
        ),
        sa.CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_qc_candidate_gate_key",
        ),
        sa.CheckConstraint(
            "ordinal > 0", name="ck_orch_qc_candidate_ordinal"
        ),
        sa.CheckConstraint(
            SHA256.format(column="candidate_digest"),
            name="ck_orch_qc_candidate_digest",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{SCHEMA}.workflow_runs.id",
                f"{SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_qc_candidate_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "evaluation_id",
                "project_id",
                "artifact_id",
                "artifact_digest",
                "gate_key",
            ],
            [
                f"{SCHEMA}.qc_evaluation_facts.id",
                f"{SCHEMA}.qc_evaluation_facts.project_id",
                f"{SCHEMA}.qc_evaluation_facts.artifact_id",
                f"{SCHEMA}.qc_evaluation_facts.artifact_digest",
                f"{SCHEMA}.qc_evaluation_facts.gate_key",
            ],
            name="fk_orch_qc_candidate_evaluation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            "ordinal",
            name="uq_orch_qc_candidate_ordinal",
        ),
        sa.UniqueConstraint(
            "project_id",
            "artifact_id",
            name="uq_orch_qc_candidate_artifact",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_candidate_scope",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "gate_key",
            name="uq_orch_qc_candidate_gate_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_qc_candidate_gate",
        "qc_candidate_versions",
        ["project_id", "workflow_run_id", "stage", "gate_key", "ordinal"],
        schema=SCHEMA,
    )

    op.create_table(
        "qc_gold_dataset_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("dataset_key", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(as_uuid=True)),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("dataset_digest", sa.String(64), nullable=False),
        sa.Column("created_by_actor", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.CheckConstraint("revision > 0", name="ck_orch_qc_gold_revision"),
        sa.CheckConstraint(
            SHA256.format(column="dataset_digest"),
            name="ck_orch_qc_gold_digest",
        ),
        _project_fk("fk_orch_qc_gold_project"),
        sa.ForeignKeyConstraint(
            ["parent_revision_id", "project_id"],
            [
                f"{SCHEMA}.qc_gold_dataset_revisions.id",
                f"{SCHEMA}.qc_gold_dataset_revisions.project_id",
            ],
            name="fk_orch_qc_gold_parent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "dataset_key",
            "revision",
            name="uq_orch_qc_gold_revision",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "dataset_digest",
            name="uq_orch_qc_gold_identity",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_gold_scope",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "qc_calibration_reports",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column(
            "gold_dataset_revision_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column("gold_dataset_digest", sa.String(64), nullable=False),
        sa.Column("evaluator_bundle_digest", sa.String(64), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failures", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_calibration_stage",
        ),
        sa.CheckConstraint(
            SHA256.format(column="evaluator_bundle_digest"),
            name="ck_orch_qc_calibration_evaluator",
        ),
        sa.ForeignKeyConstraint(
            [
                "gold_dataset_revision_id",
                "project_id",
                "gold_dataset_digest",
            ],
            [
                f"{SCHEMA}.qc_gold_dataset_revisions.id",
                f"{SCHEMA}.qc_gold_dataset_revisions.project_id",
                f"{SCHEMA}.qc_gold_dataset_revisions.dataset_digest",
            ],
            name="fk_orch_qc_calibration_gold",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "gold_dataset_revision_id",
            "evaluator_bundle_digest",
            name="uq_orch_qc_calibration_input",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_calibration_scope",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "qc_certification_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("evaluator_bundle_digest", sa.String(64), nullable=False),
        sa.Column(
            "calibration_report_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column(
            "gold_dataset_revision_id", sa.Uuid(as_uuid=True), nullable=False
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("issued_by_actor", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_certification_stage",
        ),
        sa.CheckConstraint(
            "status IN ('CERTIFIED', 'REVOKED')",
            name="ck_orch_qc_certification_status",
        ),
        sa.CheckConstraint(
            SHA256.format(column="evaluator_bundle_digest"),
            name="ck_orch_qc_certification_evaluator",
        ),
        sa.ForeignKeyConstraint(
            ["calibration_report_id", "project_id"],
            [
                f"{SCHEMA}.qc_calibration_reports.id",
                f"{SCHEMA}.qc_calibration_reports.project_id",
            ],
            name="fk_orch_qc_certification_report",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            name="uq_orch_qc_certification_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_orch_qc_certification_current",
        "qc_certification_events",
        ["project_id", "stage", "evaluator_bundle_digest", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "qc_gate_decisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("gate_key", sa.String(200), nullable=False),
        sa.Column("policy_snapshot_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("candidate_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("decision_sequence", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("expected_selection_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "stage IN ('asset', 'keyframe', 'clip', 'final')",
            name="ck_orch_qc_gate_decision_stage",
        ),
        sa.CheckConstraint(
            "length(trim(gate_key)) > 0",
            name="ck_orch_qc_gate_decision_gate_key",
        ),
        sa.CheckConstraint(
            "outcome IN ('SELECTED', 'REWORK_PLANNED', 'WAITING_HUMAN', "
            "'DEGRADED_ACCEPTED', 'BLOCKED_UNCERTIFIED')",
            name="ck_orch_qc_gate_decision_outcome",
        ),
        sa.CheckConstraint(
            "decision_sequence > 0",
            name="ck_orch_qc_gate_decision_sequence",
        ),
        sa.CheckConstraint(
            "expected_selection_version >= 0",
            name="ck_orch_qc_gate_decision_selection_version",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id"],
            [
                f"{SCHEMA}.workflow_runs.id",
                f"{SCHEMA}.workflow_runs.project_id",
            ],
            name="fk_orch_qc_gate_decision_workflow",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_snapshot_id", "project_id", "gate_key"],
            [
                f"{SCHEMA}.qc_gate_policy_snapshots.id",
                f"{SCHEMA}.qc_gate_policy_snapshots.project_id",
                f"{SCHEMA}.qc_gate_policy_snapshots.gate_key",
            ],
            name="fk_orch_qc_gate_decision_policy",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "project_id", "gate_key"],
            [
                f"{SCHEMA}.qc_candidate_versions.id",
                f"{SCHEMA}.qc_candidate_versions.project_id",
                f"{SCHEMA}.qc_candidate_versions.gate_key",
            ],
            name="fk_orch_qc_gate_decision_candidate",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "workflow_run_id",
            "stage",
            "gate_key",
            "decision_sequence",
            name="uq_orch_qc_gate_decision_sequence",
        ),
        schema=SCHEMA,
    )

    immutable_tables = (
        "qc_prompt_revisions",
        "qc_gate_policy_snapshots",
        "qc_evaluation_facts",
        "qc_candidate_versions",
        "qc_gold_dataset_revisions",
        "qc_calibration_reports",
        "qc_certification_events",
        "qc_gate_decisions",
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

    op.execute(
        """
        REVOKE ALL ON TABLE
            orchestration.qc_prompt_revisions,
            orchestration.qc_gate_policy_snapshots,
            orchestration.qc_evaluation_facts,
            orchestration.qc_candidate_versions,
            orchestration.qc_gold_dataset_revisions,
            orchestration.qc_calibration_reports,
            orchestration.qc_certification_events,
            orchestration.qc_gate_decisions
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
                GRANT SELECT, INSERT ON
                    orchestration.qc_prompt_revisions,
                    orchestration.qc_gate_policy_snapshots,
                    orchestration.qc_evaluation_facts,
                    orchestration.qc_candidate_versions,
                    orchestration.qc_gold_dataset_revisions,
                    orchestration.qc_calibration_reports,
                    orchestration.qc_certification_events,
                    orchestration.qc_gate_decisions
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
            "SELECT 1 FROM orchestration.qc_prompt_revisions "
            "UNION ALL SELECT 1 FROM orchestration.qc_gate_policy_snapshots "
            "UNION ALL SELECT 1 FROM orchestration.qc_evaluation_facts "
            "UNION ALL SELECT 1 FROM orchestration.qc_candidate_versions "
            "UNION ALL SELECT 1 FROM orchestration.qc_gold_dataset_revisions "
            "UNION ALL SELECT 1 FROM orchestration.qc_calibration_reports "
            "UNION ALL SELECT 1 FROM orchestration.qc_certification_events "
            "UNION ALL SELECT 1 FROM orchestration.qc_gate_decisions)"
        )
    ).scalar_one()
    if (
        populated
        and os.getenv("ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE") != "YES"
    ):
        raise RuntimeError(
            "orchestration downgrade would delete immutable QC facts; set "
            "ALLOW_DESTRUCTIVE_ORCHESTRATION_DOWNGRADE=YES only after backup"
        )
    tables = (
        "qc_gate_decisions",
        "qc_certification_events",
        "qc_calibration_reports",
        "qc_gold_dataset_revisions",
        "qc_candidate_versions",
        "qc_evaluation_facts",
        "qc_gate_policy_snapshots",
        "qc_prompt_revisions",
    )
    for table_name in tables:
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable "
            f"ON orchestration.{table_name}"
        )
        op.drop_table(table_name, schema=SCHEMA)
