from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


HUB_SCHEMA = "hub"
ORCHESTRATION_SCHEMA = "orchestration"


class HubBase(DeclarativeBase):
    metadata = MetaData(schema=HUB_SCHEMA)


class OrchestrationBase(DeclarativeBase):
    metadata = MetaData(schema=ORCHESTRATION_SCHEMA)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CreatedUpdatedAt(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KnowledgeCardRecord(CreatedUpdatedAt, HubBase):
    __tablename__ = "knowledge_cards"
    __table_args__ = (
        CheckConstraint(
            "current_revision >= 0",
            name="ck_knowledge_cards_current_revision_nonnegative",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    current_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )


class KnowledgeRevisionRecord(CreatedAt, HubBase):
    __tablename__ = "knowledge_revisions"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_id",
            "revision",
            name="uq_knowledge_revisions_card_revision",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_knowledge_revisions_idempotency_key",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_knowledge_revisions_revision_positive",
        ),
        CheckConstraint(
            "length(revision_sha256) = 64",
            name="ck_knowledge_revisions_sha256_length",
        ),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 255",
            name="ck_knowledge_revisions_idempotency_length",
        ),
        Index(
            "ix_knowledge_revisions_card_created",
            "knowledge_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    knowledge_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.knowledge_cards.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class KnowledgeReviewRecord(CreatedAt, HubBase):
    __tablename__ = "knowledge_reviews"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            name="uq_knowledge_reviews_revision_id",
        ),
        CheckConstraint(
            "length(revision_sha256) = 64",
            name="ck_knowledge_reviews_revision_sha256_length",
        ),
        CheckConstraint(
            "length(review_sha256) = 64",
            name="ck_knowledge_reviews_review_sha256_length",
        ),
        CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_knowledge_reviews_decision",
        ),
        CheckConstraint(
            "(decision = 'rejected' AND reason IS NOT NULL "
            "AND length(reason) > 0) OR decision = 'approved'",
            name="ck_knowledge_reviews_rejection_reason",
        ),
        Index(
            "ix_knowledge_reviews_decision_reviewed",
            "decision",
            "reviewed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.knowledge_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class KnowledgePackRecord(CreatedAt, HubBase):
    __tablename__ = "knowledge_packs"
    __table_args__ = (
        UniqueConstraint(
            "pack_sha256",
            name="uq_knowledge_packs_sha256",
        ),
        CheckConstraint(
            "length(pack_sha256) = 64",
            name="ck_knowledge_packs_sha256_length",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    pack_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ImportPlanRecord(CreatedAt, HubBase):
    __tablename__ = "import_plans"
    __table_args__ = (
        UniqueConstraint(
            "plan_sha256",
            name="uq_import_plans_sha256",
        ),
        CheckConstraint(
            "length(plan_sha256) = 64",
            name="ck_import_plans_sha256_length",
        ),
        CheckConstraint(
            "length(pack_sha256) = 64",
            name="ck_import_plans_pack_sha256_length",
        ),
        CheckConstraint(
            "length(target_snapshot_sha256) = 64",
            name="ck_import_plans_target_snapshot_sha256_length",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pack_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.knowledge_packs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pack_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    target_snapshot_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FactoryImportRecord(CreatedUpdatedAt, HubBase):
    """Read-only Hub mirror of the factory-owned immutable import revision."""

    __tablename__ = "factory_imports"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_factory_imports_idempotency_key",
        ),
        UniqueConstraint(
            "factory_project_id",
            "factory_revision_id",
            name="uq_factory_imports_revision",
        ),
        CheckConstraint(
            "status IN ('submitting', 'accepted', 'conflict', 'failed')",
            name="ck_factory_imports_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.import_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    factory_project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    factory_revision_id: Mapped[str | None] = mapped_column(String(255))
    factory_revision_sha256: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


class RubricDefinitionRecord(CreatedAt, HubBase):
    __tablename__ = "rubric_definitions"

    rubric_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    active_version: Mapped[int] = mapped_column(Integer, nullable=False)


class RubricVersionRecord(CreatedAt, HubBase):
    __tablename__ = "rubric_versions"
    __table_args__ = (
        UniqueConstraint(
            "rubric_id",
            "version",
            name="uq_rubric_versions_identity",
        ),
        CheckConstraint("version > 0", name="ck_rubric_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    rubric_id: Mapped[str] = mapped_column(
        ForeignKey(
            f"{HUB_SCHEMA}.rubric_definitions.rubric_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class RubricDimensionRecord(HubBase):
    __tablename__ = "rubric_dimensions"
    __table_args__ = (
        CheckConstraint(
            "display_order >= 0",
            name="ck_rubric_dimensions_display_order",
        ),
        CheckConstraint(
            "weight > 0",
            name="ck_rubric_dimensions_weight",
        ),
    )

    rubric_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.rubric_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dimension_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    core: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )


class StageApplicabilityRecord(HubBase):
    __tablename__ = "stage_applicability"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('factory_qc', 'hub_ai', 'hub_human')",
            name="ck_stage_applicability_stage",
        ),
    )

    rubric_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.rubric_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stage: Mapped[str] = mapped_column(String(32), primary_key=True)
    dimension_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )


class EvaluationRecord(CreatedAt, HubBase):
    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_evaluations_idempotency_key",
        ),
        CheckConstraint(
            "stage IN ('factory_qc', 'hub_ai', 'hub_human')",
            name="ck_evaluations_stage",
        ),
        CheckConstraint(
            "subject_type IN ('visual_take', 'delivery_take')",
            name="ck_evaluations_subject_type",
        ),
        CheckConstraint(
            "length(rubric_payload_sha256) = 64",
            name="ck_evaluations_rubric_sha256_length",
        ),
        CheckConstraint(
            "length(submission_sha256) = 64",
            name="ck_evaluations_submission_sha256_length",
        ),
        Index("ix_evaluations_take_stage_created", "take_id", "stage", "created_at"),
        Index("ix_evaluations_lineage_group", "lineage_group"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    take_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    rubric_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rubric_payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    submission_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_model: Mapped[str | None] = mapped_column(String(200))
    model_version: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(200))
    raw_response_ref: Mapped[str | None] = mapped_column(String(500))
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.evaluations.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    lineage_group: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(255))
    scene_id: Mapped[str | None] = mapped_column(String(255))
    knowledge_pack_version: Mapped[str | None] = mapped_column(String(255))


class EvaluationScoreRecord(HubBase):
    __tablename__ = "evaluation_scores"
    __table_args__ = (
        CheckConstraint(
            "score IS NULL OR (score >= 1 AND score <= 10)",
            name="ck_evaluation_scores_range",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_evaluation_scores_confidence",
        ),
        CheckConstraint(
            "(score IS NULL AND na_reason IS NOT NULL) OR "
            "(score IS NOT NULL AND na_reason IS NULL)",
            name="ck_evaluation_scores_na_reason",
        ),
    )

    evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.evaluations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dimension_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    score: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    na_reason: Mapped[str | None] = mapped_column(String(500))
    original_value: Mapped[float | None] = mapped_column(Float)
    original_scale: Mapped[str | None] = mapped_column(String(100))
    migration_version: Mapped[str | None] = mapped_column(String(100))


class EvaluationEvidenceRecord(HubBase):
    __tablename__ = "evaluation_evidence"
    __table_args__ = (
        Index(
            "ix_evaluation_evidence_evaluation_dimension",
            "evaluation_id",
            "dimension_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    dimension_id: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    span: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PreferenceEventRecord(CreatedAt, HubBase):
    __tablename__ = "preference_events"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_preference_events_idempotency_key",
        ),
        UniqueConstraint(
            "human_evaluation_id",
            name="uq_preference_events_human_evaluation",
        ),
        CheckConstraint(
            "action IS NULL OR action IN "
            "('keep', 'edit', 'reroll', 'rewrite')",
            name="ck_preference_events_action",
        ),
        Index("ix_preference_events_profile_created", "profile_id", "created_at"),
        Index("ix_preference_events_lineage_group", "lineage_group"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    take_id: Mapped[str] = mapped_column(String(255), nullable=False)
    lineage_group: Mapped[str] = mapped_column(String(255), nullable=False)
    human_evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.evaluations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ai_evaluation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.evaluations.id", ondelete="RESTRICT")
    )
    action: Mapped[str | None] = mapped_column(String(32))
    preferred_take_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    feedback: Mapped[str | None] = mapped_column(Text)
    score_deltas: Mapped[dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


class PreferenceProfileRecord(CreatedUpdatedAt, HubBase):
    __tablename__ = "preference_profiles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('collecting', 'fit_ready', 'validation_ready', 'shadow')",
            name="ck_preference_profiles_status",
        ),
    )

    profile_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    paired_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    lineage_groups: Mapped[int] = mapped_column(Integer, nullable=False)
    last_report: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


class CalibrationRunRecord(CreatedAt, HubBase):
    __tablename__ = "calibration_runs"
    __table_args__ = (
        UniqueConstraint(
            "input_sha256",
            name="uq_calibration_runs_input_sha256",
        ),
        CheckConstraint(
            "status IN ('insufficient', 'shadow', 'candidate')",
            name="ck_calibration_runs_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    training_lineages: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    validation_lineages: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ActivationCandidateRecord(CreatedAt, HubBase):
    __tablename__ = "activation_candidates"
    __table_args__ = (
        UniqueConstraint(
            "calibration_run_id",
            name="uq_activation_candidates_calibration_run",
        ),
        CheckConstraint(
            "status = 'awaiting_r4'",
            name="ck_activation_candidates_r3_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    calibration_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{HUB_SCHEMA}.calibration_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FactoryProjectRecord(CreatedUpdatedAt, HubBase):
    __tablename__ = "factory_projects"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    active_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FactoryRevisionRecord(CreatedAt, HubBase):
    __tablename__ = "factory_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "content_hash",
            name="uq_factory_revisions_project_content",
        ),
        CheckConstraint(
            "source_kind IN ('native', 'legacy_import')",
            name="ck_factory_revisions_source_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    parent_revision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64))
    revision_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FactoryTakeIndexRecord(CreatedUpdatedAt, HubBase):
    __tablename__ = "factory_take_index"
    __table_args__ = (
        CheckConstraint(
            "take_kind IN ('visual', 'delivery')",
            name="ck_factory_take_index_kind",
        ),
        Index(
            "ix_factory_take_project_kind_created",
            "project_id",
            "take_kind",
            "take_created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    visual_take_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    take_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    eligibility: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    take_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class VisualCanonMirrorRecord(CreatedAt, HubBase):
    __tablename__ = "visual_canon_revisions"
    __table_args__ = (
        UniqueConstraint(
            "scene_id",
            "canon_version",
            name="uq_visual_canon_scene_version",
        ),
        Index(
            "ix_visual_canon_project_scene_version",
            "project_id",
            "scene_id",
            "canon_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scene_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    canon_version: Mapped[int] = mapped_column(Integer, nullable=False)
    visual_take_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    continuity_anchor_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DeliveryRevisionMirrorRecord(CreatedAt, HubBase):
    __tablename__ = "delivery_revisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "delivery_version",
            name="uq_delivery_revision_project_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    delivery_version: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_take_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    delivery_acceptance_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ModelCredentialRecord(CreatedUpdatedAt, HubBase):
    __tablename__ = "model_credentials"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "model_name",
            name="uq_model_credentials_provider_model",
        ),
        CheckConstraint(
            "length(provider) BETWEEN 1 AND 64",
            name="ck_model_credentials_provider_length",
        ),
        CheckConstraint(
            "length(model_name) BETWEEN 1 AND 200",
            name="ck_model_credentials_model_length",
        ),
        CheckConstraint(
            "length(ciphertext) BETWEEN 16 AND 8192",
            name="ck_model_credentials_ciphertext_length",
        ),
        CheckConstraint(
            "length(nonce) BETWEEN 16 AND 32",
            name="ck_model_credentials_nonce_length",
        ),
        CheckConstraint(
            "length(fingerprint) = 64",
            name="ck_model_credentials_fingerprint_length",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_model_credentials_revision_positive",
        ),
        CheckConstraint(
            "verification_status IN "
            "('unchecked', 'available', 'invalid')",
            name="ck_model_credentials_verification_status",
        ),
        Index(
            "ix_model_credentials_provider_model",
            "provider",
            "model_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    key_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    verification_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unchecked",
        server_default="unchecked",
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    verification_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    updated_by: Mapped[str] = mapped_column(String(100), nullable=False)


class HubJobRecord(CreatedUpdatedAt, OrchestrationBase):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_hub_jobs_idempotency_key"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', "
            "'cancelled', 'needs_human')",
            name="ck_hub_jobs_status",
        ),
    CheckConstraint(
            "lease_generation >= 0",
            name="ck_hub_jobs_lease_generation_nonnegative",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_hub_jobs_attempts",
        ),
        Index("ix_hub_jobs_status_created", "status", "created_at"),
        Index("ix_hub_jobs_expired_lease", "status", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    error: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    lock_owner: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default="3",
    )
    lease_generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class JobEventRecord(CreatedAt, OrchestrationBase):
    __tablename__ = "job_events"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "sequence",
            name="uq_hub_job_events_job_sequence",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_hub_job_events_sequence_positive",
        ),
        CheckConstraint(
            "contract_major = 1",
            name="ck_hub_job_events_contract_major_supported",
        ),
        CheckConstraint(
            "contract_minor >= 0",
            name="ck_hub_job_events_contract_minor_nonnegative",
        ),
        Index("ix_hub_job_events_job_sequence", "job_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{ORCHESTRATION_SCHEMA}.jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    contract_major: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    contract_minor: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class GenerationRunMirrorRecord(CreatedUpdatedAt, OrchestrationBase):
    __tablename__ = "generation_runs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_generation_runs_idempotency",
        ),
        Index(
            "ix_generation_runs_project_status",
            "project_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scene_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    clip_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FactoryOutboxConsumptionRecord(CreatedAt, OrchestrationBase):
    __tablename__ = "factory_outbox_consumption"
    __table_args__ = (
        UniqueConstraint(
            "source_revision_id",
            "source_sequence",
            name="uq_factory_outbox_source_sequence",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
    )
    source_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    source_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    source_state_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ModelRegistryRecord(CreatedUpdatedAt, OrchestrationBase):
    __tablename__ = "model_registry"

    model_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    registry_entry_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        unique=True,
        nullable=False,
    )
    install_status: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ModelCapabilityRecord(CreatedAt, OrchestrationBase):
    __tablename__ = "model_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "operation",
            "workflow_id",
            name="uq_model_capability_operation_workflow",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(200), nullable=False)
    estimated_vram_mib: Mapped[int] = mapped_column(Integer, nullable=False)
    verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class GpuLeaseMirrorRecord(CreatedUpdatedAt, OrchestrationBase):
    __tablename__ = "gpu_leases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'active', 'released', 'expired', 'cancelled')",
            name="ck_gpu_leases_status",
        ),
        Index(
            "ix_gpu_leases_status_priority",
            "status",
            "effective_priority",
            "requested_at",
        ),
        Index(
            "uq_gpu_leases_one_active_per_gpu",
            "gpu_index",
            unique=True,
            postgresql_where=text(
                "status = 'active' AND gpu_index IS NOT NULL"
            ),
            sqlite_where=text(
                "status = 'active' AND gpu_index IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        unique=True,
        nullable=False,
    )
    resource_class: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    estimated_vram_mib: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_priority: Mapped[int] = mapped_column(Integer, nullable=False)
    gpu_index: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class GpuObservationRecord(CreatedAt, OrchestrationBase):
    __tablename__ = "gpu_observations"
    __table_args__ = (
        Index(
            "ix_gpu_observations_gpu_observed",
            "gpu_index",
            "observed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    gpu_index: Mapped[int] = mapped_column(Integer, nullable=False)
    total_vram_mib: Mapped[int] = mapped_column(Integer, nullable=False)
    free_vram_mib: Mapped[int] = mapped_column(Integer, nullable=False)
    warm_model_id: Mapped[str | None] = mapped_column(String(200))
    active_lease_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ProjectCloudPolicyRecord(CreatedAt, OrchestrationBase):
    __tablename__ = "project_cloud_policies"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "policy_version",
            name="uq_project_cloud_policy_version",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_project_cloud_policy_idempotency",
        ),
        CheckConstraint(
            "policy_version > 0",
            name="ck_project_cloud_policy_version_positive",
        ),
        Index(
            "ix_project_cloud_policy_latest",
            "project_id",
            "policy_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    provider_allowlist: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )
    allowed_data_types: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )
    provider_retention_notice: Mapped[str | None] = mapped_column(Text)
    consented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_by_actor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    snapshot_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


_ATOMIC_MODEL_EXPORTS = {
    "BudgetAccountRecord",
    "BudgetLedgerEntryRecord",
    "BudgetReservationRecord",
    "OperationAttemptEventRecord",
    "OperationAttemptRecord",
    "OperationAttemptStateRecord",
    "OperationRunRecord",
    "ProjectRecord",
    "SelectionHeadRecord",
    "SelectionRevisionRecord",
    "WorkflowDefinitionRecord",
    "WorkflowDefinitionRevisionRecord",
    "WorkflowRunRecord",
}


def __getattr__(name: str) -> Any:
    """Lazily preserve the historical ``creative_hub.models`` import seam."""

    if name not in _ATOMIC_MODEL_EXPORTS:
        raise AttributeError(name)
    from creative_hub.db import models as atomic_models

    return getattr(atomic_models, name)
