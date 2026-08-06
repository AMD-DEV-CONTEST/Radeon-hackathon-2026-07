from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from pydantic import Field, model_validator

from colorgraph.evaluation.creative_intake import (
    CreativeArtifactReference,
    CreativeProductionEvidenceAudit,
    verify_creative_production_manifest,
)
from colorgraph.evaluation.metrics import fleiss_kappa
from colorgraph.evaluation.models import StrictEvaluationModel
from colorgraph.evaluation.review import ReviewPair

CREATIVE_AGENT_EVALUATION_VERSION = "colorgraph.creative-agent-evaluation/v3"
CREATIVE_AGENT_EVALUATION_INPUT_VERSION = (
    "colorgraph.creative-agent-evaluation-input/v3"
)
CREATIVE_ABLATION_EXECUTION_VERSION = (
    "colorgraph.creative-ablation-execution/v1"
)
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CreativeEvaluationSplit(StrEnum):
    TRAIN = "train"
    CALIBRATION = "calibration"
    TEST = "test"


class CreativeEvidenceClass(StrEnum):
    FIXTURE = "fixture"
    PRODUCTION = "production"


class CreativeMediaOrigin(StrEnum):
    CAMERA_ORIGINAL = "camera_original"
    LICENSED_STOCK = "licensed_stock"
    PUBLISHED_DATASET = "published_dataset"
    SYNTHETIC = "synthetic"


class CreativePipelineVariant(StrEnum):
    RULE_BASELINE = "rule_baseline"
    SINGLE_LLM = "single_llm"
    RAG_FIRST = "rag_first"
    CLOSED_BOOK_NO_RAG = "closed_book_no_rag"
    SINGLE_DIRECTION = "single_direction"
    NO_CRITIC = "no_critic"
    NO_REFLECTION = "no_reflection"
    FULL_PIPELINE = "full_pipeline"


class CreativePipelineStage(StrEnum):
    RULE_PLANNER = "rule_planner"
    SINGLE_LLM = "single_llm"
    DIRECTOR = "director"
    RETRIEVAL = "retrieval"
    STRATEGIST = "strategist"
    COMPILER = "compiler"
    RENDERER = "renderer"
    HARD_QC = "hard_qc"
    CRITIC = "critic"
    REFLECTION = "reflection"


_VARIANT_STAGE_ORDER: dict[
    CreativePipelineVariant,
    tuple[CreativePipelineStage, ...],
] = {
    CreativePipelineVariant.RULE_BASELINE: (
        CreativePipelineStage.RULE_PLANNER,
        CreativePipelineStage.COMPILER,
        CreativePipelineStage.RENDERER,
        CreativePipelineStage.HARD_QC,
    ),
    CreativePipelineVariant.SINGLE_LLM: (
        CreativePipelineStage.SINGLE_LLM,
        CreativePipelineStage.COMPILER,
        CreativePipelineStage.RENDERER,
        CreativePipelineStage.HARD_QC,
        CreativePipelineStage.CRITIC,
        CreativePipelineStage.REFLECTION,
    ),
    CreativePipelineVariant.RAG_FIRST: (
        CreativePipelineStage.RETRIEVAL,
        CreativePipelineStage.DIRECTOR,
        CreativePipelineStage.STRATEGIST,
        CreativePipelineStage.COMPILER,
        CreativePipelineStage.RENDERER,
        CreativePipelineStage.HARD_QC,
        CreativePipelineStage.CRITIC,
        CreativePipelineStage.REFLECTION,
    ),
    CreativePipelineVariant.CLOSED_BOOK_NO_RAG: (
        CreativePipelineStage.DIRECTOR,
        CreativePipelineStage.STRATEGIST,
        CreativePipelineStage.COMPILER,
        CreativePipelineStage.RENDERER,
        CreativePipelineStage.HARD_QC,
        CreativePipelineStage.CRITIC,
        CreativePipelineStage.REFLECTION,
    ),
    CreativePipelineVariant.SINGLE_DIRECTION: (
        CreativePipelineStage.DIRECTOR,
        CreativePipelineStage.RETRIEVAL,
        CreativePipelineStage.STRATEGIST,
        CreativePipelineStage.COMPILER,
        CreativePipelineStage.RENDERER,
        CreativePipelineStage.HARD_QC,
        CreativePipelineStage.CRITIC,
        CreativePipelineStage.REFLECTION,
    ),
    CreativePipelineVariant.NO_CRITIC: (
        CreativePipelineStage.DIRECTOR,
        CreativePipelineStage.RETRIEVAL,
        CreativePipelineStage.STRATEGIST,
        CreativePipelineStage.COMPILER,
        CreativePipelineStage.RENDERER,
        CreativePipelineStage.HARD_QC,
        CreativePipelineStage.REFLECTION,
    ),
    CreativePipelineVariant.NO_REFLECTION: (
        CreativePipelineStage.DIRECTOR,
        CreativePipelineStage.RETRIEVAL,
        CreativePipelineStage.STRATEGIST,
        CreativePipelineStage.COMPILER,
        CreativePipelineStage.RENDERER,
        CreativePipelineStage.HARD_QC,
        CreativePipelineStage.CRITIC,
    ),
    CreativePipelineVariant.FULL_PIPELINE: (
        CreativePipelineStage.DIRECTOR,
        CreativePipelineStage.RETRIEVAL,
        CreativePipelineStage.STRATEGIST,
        CreativePipelineStage.COMPILER,
        CreativePipelineStage.RENDERER,
        CreativePipelineStage.HARD_QC,
        CreativePipelineStage.CRITIC,
        CreativePipelineStage.REFLECTION,
    ),
}


def creative_variant_stage_order(
    variant: CreativePipelineVariant,
) -> tuple[CreativePipelineStage, ...]:
    return _VARIANT_STAGE_ORDER[variant]


class CreativeVariantExecution(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-ablation-execution/v1"] = (
        CREATIVE_ABLATION_EXECUTION_VERSION
    )
    candidate_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    variant: CreativePipelineVariant
    source_media_sha256: Sha256Digest
    source_graph_sha256: Sha256Digest
    source_graph_artifact_sha256: Sha256Digest
    run_request_sha256: Sha256Digest
    pipeline_result_sha256: Sha256Digest
    output_sha256: Sha256Digest
    executed_stages: list[CreativePipelineStage] = Field(min_length=1)
    disabled_stages: list[CreativePipelineStage]
    stage_evidence_sha256: dict[CreativePipelineStage, Sha256Digest]
    model_identity_sha256: list[Sha256Digest]
    provider_response_ids: list[str]
    direction_count: int = Field(ge=1, le=3)
    direction_signatures: list[str] = Field(min_length=1)
    direction_pairwise_distances: list[float]
    closed_book_director: bool
    retrieval_input_to_director: bool
    current_graph_unchanged: bool
    hard_qc_passed: bool

    @model_validator(mode="after")
    def validate_protocol(self) -> CreativeVariantExecution:
        expected = list(_VARIANT_STAGE_ORDER[self.variant])
        if self.executed_stages != expected:
            raise ValueError(
                f"{self.variant.value} executed stages do not match the frozen "
                "ablation protocol"
            )
        expected_disabled = [
            stage for stage in CreativePipelineStage if stage not in expected
        ]
        if self.disabled_stages != expected_disabled:
            raise ValueError(
                f"{self.variant.value} disabled stages do not match the frozen "
                "ablation protocol"
            )
        if set(self.stage_evidence_sha256) != set(expected):
            raise ValueError(
                "ablation execution evidence must exactly cover executed stages"
            )
        if len(self.stage_evidence_sha256) != len(
            set(self.stage_evidence_sha256.values())
        ):
            raise ValueError(
                "each executed stage requires distinct content-bound evidence"
            )
        expected_direction_count = (
            1
            if self.variant
            in {
                CreativePipelineVariant.RULE_BASELINE,
                CreativePipelineVariant.SINGLE_DIRECTION,
            }
            else 3
        )
        if self.direction_count != expected_direction_count:
            raise ValueError(
                f"{self.variant.value} requires {expected_direction_count} "
                "direction(s)"
            )
        if len(set(self.direction_signatures)) != self.direction_count:
            raise ValueError(
                "ablation direction signatures must be unique and complete"
            )
        expected_distances = (
            self.direction_count * (self.direction_count - 1) // 2
        )
        if len(self.direction_pairwise_distances) != expected_distances or any(
            not math.isfinite(value) or not 0 <= value <= 1
            for value in self.direction_pairwise_distances
        ):
            raise ValueError(
                "ablation direction distances must cover every direction pair"
            )
        closed_book_variants = {
            CreativePipelineVariant.CLOSED_BOOK_NO_RAG,
            CreativePipelineVariant.SINGLE_DIRECTION,
            CreativePipelineVariant.NO_CRITIC,
            CreativePipelineVariant.NO_REFLECTION,
            CreativePipelineVariant.FULL_PIPELINE,
        }
        if self.closed_book_director != (
            self.variant in closed_book_variants
        ):
            raise ValueError(
                "closed-book Director state does not match the ablation variant"
            )
        if self.retrieval_input_to_director != (
            self.variant == CreativePipelineVariant.RAG_FIRST
        ):
            raise ValueError(
                "only the rag_first ablation may expose retrieval to Director"
            )
        if not self.current_graph_unchanged:
            raise ValueError(
                "creative ablation execution must leave the current graph unchanged"
            )
        if self.variant == CreativePipelineVariant.RULE_BASELINE:
            if self.model_identity_sha256 or self.provider_response_ids:
                raise ValueError(
                    "rule baseline cannot claim provider model execution"
                )
        elif not self.model_identity_sha256 or not self.provider_response_ids:
            raise ValueError(
                "model-driven ablations require model identities and provider receipts"
            )
        if len(self.model_identity_sha256) != len(
            set(self.model_identity_sha256)
        ):
            raise ValueError("ablation model identities must be unique")
        if len(self.provider_response_ids) != len(set(self.provider_response_ids)):
            raise ValueError("ablation provider response receipts must be unique")
        return self


class CreativeEvaluationDimension(StrEnum):
    CONCEPT_SUPPORT = "concept_support"
    EXPRESSION_COHERENCE = "expression_coherence"
    VISUAL_HIERARCHY = "visual_hierarchy"
    DISTINCTIVENESS = "distinctiveness"
    NATURALNESS = "naturalness"
    OVERGRADING_RISK = "overgrading_risk"
    CROSS_SCENE_CONTINUITY = "cross_scene_continuity"
    DIRECTION_DIVERSITY = "direction_diversity"


class CreativeChallengeTag(StrEnum):
    SAME_SCENE_DIFFERENT_CONTEXT = "same_scene_different_context"
    SAME_EMOTION_DIFFERENT_SCENE = "same_emotion_different_scene"
    AMBIGUOUS_OR_CULTURAL_LANGUAGE = "ambiguous_or_cultural_language"
    OUT_OF_DISTRIBUTION = "out_of_distribution"
    INCORRECT_AUDIO_HINT = "incorrect_audio_hint"
    LOG_MISINTERPRETATION = "log_misinterpretation"
    PROMPT_INJECTION = "prompt_injection"


class CreativePairChoice(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    TIE = "tie"
    REJECT = "reject"


class CreativeGoldEvidence(StrictEvaluationModel):
    evidence_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    frame_index: int = Field(ge=0)
    region: str = Field(min_length=1)
    observation: str = Field(min_length=1)


class CreativeGoldItem(StrictEvaluationModel):
    item_id: str = Field(min_length=1)
    source_group_id: str = Field(min_length=1)
    split: CreativeEvaluationSplit
    frozen: bool
    duration_seconds: float = Field(gt=0)
    media_origin: CreativeMediaOrigin
    media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_guideline_version: str = Field(min_length=1)
    evidence: list[CreativeGoldEvidence] = Field(min_length=1)
    acceptable_visual_theses: list[str] = Field(min_length=2)
    scene_roles: dict[str, str]
    cliche_or_overgrading_risks: list[str] = Field(min_length=1)
    continuity_criteria: list[str] = Field(min_length=1)
    challenge_tags: list[CreativeChallengeTag] = Field(min_length=1)
    annotator_ids: list[str] = Field(min_length=1)
    reviewer_ids: list[str] = Field(min_length=1)
    accepted: bool

    @model_validator(mode="after")
    def validate_gold_item(self) -> CreativeGoldItem:
        if self.split == CreativeEvaluationSplit.TEST and not self.frozen:
            raise ValueError("creative test items must be frozen")
        if self.split != CreativeEvaluationSplit.TEST and self.frozen:
            raise ValueError("only creative test items may be frozen")
        if self.annotation_guideline_version.strip().lower() == "unversioned":
            raise ValueError("creative annotations require a versioned guideline")
        normalized_theses = {
            thesis.strip().casefold()
            for thesis in self.acceptable_visual_theses
            if thesis.strip()
        }
        if len(normalized_theses) < 2:
            raise ValueError(
                "creative gold must preserve multiple acceptable visual theses"
            )
        if not self.scene_roles or any(
            not key.strip() or not value.strip()
            for key, value in self.scene_roles.items()
        ):
            raise ValueError("creative gold requires non-empty scene narrative roles")
        if set(self.annotator_ids) & set(self.reviewer_ids):
            raise ValueError("creative annotation and review must be independent")
        if len(self.challenge_tags) != len(set(self.challenge_tags)):
            raise ValueError("creative challenge tags must be unique")
        return self


class CreativeReviewer(StrictEvaluationModel):
    reviewer_id: str = Field(min_length=1)
    years_experience: float = Field(ge=1)
    roles: list[str] = Field(min_length=1)
    color_vision_screened: bool
    calibrated_display_confirmed: bool


class CreativeCandidateObservation(StrictEvaluationModel):
    candidate_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    variant: CreativePipelineVariant
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution: CreativeVariantExecution
    hard_failure: bool = False
    non_waivable_failure_ids: list[str] = Field(default_factory=list)
    direction_signatures: list[str] = Field(default_factory=list)
    direction_pairwise_distances: list[float] = Field(default_factory=list)
    model_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    rendered_frames: int = Field(ge=0)
    wall_seconds: float = Field(ge=0)
    retries: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    cache_lookups: int = Field(ge=0)
    peak_vram_mb: float = Field(ge=0)
    human_takeover: bool = False

    @model_validator(mode="after")
    def validate_candidate(self) -> CreativeCandidateObservation:
        if (
            self.execution.candidate_id != self.candidate_id
            or self.execution.item_id != self.item_id
            or self.execution.variant != self.variant
            or self.execution.output_sha256 != self.output_sha256
        ):
            raise ValueError(
                "creative candidate identity/output does not match its "
                "ablation execution"
            )
        if self.hard_failure != bool(self.non_waivable_failure_ids):
            raise ValueError(
                "hard_failure must exactly match non-waivable failure evidence"
            )
        if self.execution.hard_qc_passed == self.hard_failure:
            raise ValueError(
                "ablation hard-QC state must exactly match candidate failure state"
            )
        if self.cache_hits > self.cache_lookups:
            raise ValueError("cache hits cannot exceed cache lookups")
        if self.direction_signatures != self.execution.direction_signatures:
            raise ValueError(
                "candidate direction signatures do not match its execution"
            )
        if (
            self.direction_pairwise_distances
            != self.execution.direction_pairwise_distances
        ):
            raise ValueError(
                "candidate direction distances do not match its execution"
            )
        if self.variant == CreativePipelineVariant.RULE_BASELINE:
            if self.model_calls != 0:
                raise ValueError("rule baseline cannot report model calls")
        elif self.model_calls <= 0:
            raise ValueError("model-driven ablations require provider calls")
        return self


class CreativeDimensionScores(StrictEvaluationModel):
    values: dict[CreativeEvaluationDimension, Annotated[float, Field(ge=0, le=1)]]

    @model_validator(mode="after")
    def validate_dimensions(self) -> CreativeDimensionScores:
        if set(self.values) != set(CreativeEvaluationDimension):
            raise ValueError("creative review must score every frozen dimension")
        return self


class CreativePairReview(StrictEvaluationModel):
    pair_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    displayed_left_candidate_id: str = Field(min_length=1)
    displayed_right_candidate_id: str = Field(min_length=1)
    choice: CreativePairChoice
    left_scores: CreativeDimensionScores | None = None
    right_scores: CreativeDimensionScores | None = None
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def validate_review(self) -> CreativePairReview:
        if self.displayed_left_candidate_id == self.displayed_right_candidate_id:
            raise ValueError("creative review candidates must differ")
        if self.choice == CreativePairChoice.REJECT:
            if not self.rejection_reason:
                raise ValueError("rejected creative reviews require a reason")
            if self.left_scores is not None or self.right_scores is not None:
                raise ValueError("rejected creative reviews cannot contain scores")
        else:
            if self.rejection_reason:
                raise ValueError("only rejected creative reviews may contain a reason")
            if self.left_scores is None or self.right_scores is None:
                raise ValueError("valid creative reviews require both score vectors")
        return self


class CreativeJudgeRecord(StrictEvaluationModel):
    pair_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    judge_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    selected_candidate_id: str | None
    same_model_as_director: bool
    evidence_grounded: bool


class CreativeChallengeResult(StrictEvaluationModel):
    item_id: str = Field(min_length=1)
    tag: CreativeChallengeTag
    passed: bool
    external_text_received_tool_authority: bool = False
    system_constraints_changed: bool = False
    unauthorized_tool_calls: int = Field(default=0, ge=0)
    detail: str = Field(min_length=1)

    @property
    def security_boundary_passed(self) -> bool:
        return (
            not self.external_text_received_tool_authority
            and not self.system_constraints_changed
            and self.unauthorized_tool_calls == 0
        )


class CreativeAgentEvaluationConfig(StrictEvaluationModel):
    minimum_reviewers: int = Field(default=3, ge=3)
    minimum_rule_baseline_pairs: int = Field(default=10, ge=3)
    minimum_preference_ci95_low: float = Field(default=0.5, ge=0, le=1)
    maximum_position_bias: float = Field(default=0.15, ge=0, le=0.5)
    minimum_direction_diversity: float = Field(default=0.15, ge=0, le=1)
    required_variants: list[CreativePipelineVariant] = Field(
        default_factory=lambda: list(CreativePipelineVariant)
    )
    required_challenges: list[CreativeChallengeTag] = Field(
        default_factory=lambda: list(CreativeChallengeTag)
    )

    @model_validator(mode="after")
    def validate_config(self) -> CreativeAgentEvaluationConfig:
        if len(self.required_variants) != len(set(self.required_variants)):
            raise ValueError("required creative variants must be unique")
        if (
            CreativePipelineVariant.RULE_BASELINE not in self.required_variants
            or CreativePipelineVariant.FULL_PIPELINE not in self.required_variants
        ):
            raise ValueError("creative evaluation requires rule and full variants")
        if len(self.required_challenges) != len(set(self.required_challenges)):
            raise ValueError("required creative challenges must be unique")
        return self


class CreativeAgentEvaluationBundle(StrictEvaluationModel):
    schema_version: Literal["colorgraph.creative-agent-evaluation-input/v3"] = (
        CREATIVE_AGENT_EVALUATION_INPUT_VERSION
    )
    evaluation_id: str = Field(min_length=1)
    evidence_class: CreativeEvidenceClass
    dataset_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    items: list[CreativeGoldItem] = Field(min_length=1)
    reviewers: list[CreativeReviewer] = Field(min_length=3)
    candidates: list[CreativeCandidateObservation] = Field(min_length=1)
    reviews: list[CreativePairReview] = Field(min_length=1)
    judge_records: list[CreativeJudgeRecord] = Field(default_factory=list)
    challenges: list[CreativeChallengeResult] = Field(min_length=1)
    production_manifest: CreativeArtifactReference | None = None
    config: CreativeAgentEvaluationConfig = Field(
        default_factory=CreativeAgentEvaluationConfig
    )

    @model_validator(mode="after")
    def validate_bundle(self) -> CreativeAgentEvaluationBundle:
        if (
            self.evidence_class == CreativeEvidenceClass.PRODUCTION
            and self.production_manifest is None
        ):
            raise ValueError(
                "production creative evaluation requires a content-bound manifest"
            )
        if (
            self.evidence_class == CreativeEvidenceClass.FIXTURE
            and self.production_manifest is not None
        ):
            raise ValueError(
                "fixture creative evaluation cannot claim a production manifest"
            )
        item_ids = [item.item_id for item in self.items]
        reviewer_ids = [item.reviewer_id for item in self.reviewers]
        candidate_ids = [item.candidate_id for item in self.candidates]
        for label, values in (
            ("item", item_ids),
            ("reviewer", reviewer_ids),
            ("candidate", candidate_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"creative {label} ids must be unique")
        source_splits: dict[str, CreativeEvaluationSplit] = {}
        for item in self.items:
            previous = source_splits.setdefault(item.source_group_id, item.split)
            if previous != item.split:
                raise ValueError(
                    f"creative source group {item.source_group_id!r} leaks across splits"
                )
        known_items = set(item_ids)
        known_reviewers = set(reviewer_ids)
        candidates = {item.candidate_id: item for item in self.candidates}
        if any(item.item_id not in known_items for item in self.candidates):
            raise ValueError("creative candidate references an unknown gold item")
        item_by_id = {item.item_id: item for item in self.items}
        for candidate in self.candidates:
            if (
                candidate.execution.source_media_sha256
                != item_by_id[candidate.item_id].media_sha256
            ):
                raise ValueError(
                    "creative candidate execution is not bound to its item media"
                )
        execution_inputs: dict[str, tuple[str, str]] = {}
        for candidate in self.candidates:
            binding = (
                candidate.execution.source_graph_sha256,
                candidate.execution.source_graph_artifact_sha256,
            )
            previous = execution_inputs.setdefault(candidate.item_id, binding)
            if previous != binding:
                raise ValueError(
                    "creative variants for one item must share one frozen source graph"
                )
        seen_reviews: set[tuple[str, str]] = set()
        canonical_pairs: dict[str, frozenset[str]] = {}
        for review in self.reviews:
            if review.item_id not in known_items or review.reviewer_id not in known_reviewers:
                raise ValueError("creative review references an unknown item or reviewer")
            pair_candidates = frozenset(
                {
                    review.displayed_left_candidate_id,
                    review.displayed_right_candidate_id,
                }
            )
            if not pair_candidates <= set(candidates):
                raise ValueError("creative review references an unknown candidate")
            if any(candidates[item].item_id != review.item_id for item in pair_candidates):
                raise ValueError("creative pair candidates must belong to the review item")
            if any(candidates[item].hard_failure for item in pair_candidates):
                raise ValueError("hard-failed candidates cannot enter aesthetic review")
            previous_pair = canonical_pairs.setdefault(review.pair_id, pair_candidates)
            if previous_pair != pair_candidates:
                raise ValueError("creative pair candidates changed between reviewers")
            review_key = (review.pair_id, review.reviewer_id)
            if review_key in seen_reviews:
                raise ValueError("duplicate creative pair review")
            seen_reviews.add(review_key)
        for record in self.judge_records:
            if record.item_id not in known_items or record.pair_id not in canonical_pairs:
                raise ValueError("creative judge references an unknown item or pair")
            if (
                record.selected_candidate_id is not None
                and record.selected_candidate_id not in canonical_pairs[record.pair_id]
            ):
                raise ValueError("creative judge selected a candidate outside its pair")
        if any(item.item_id not in known_items for item in self.challenges):
            raise ValueError("creative challenge references an unknown gold item")
        return self


class CreativeMetricEstimate(StrictEvaluationModel):
    value: float
    ci95_low: float
    ci95_high: float
    samples: int = Field(ge=0)


class CreativeVariantMetrics(StrictEvaluationModel):
    variant: CreativePipelineVariant
    candidate_count: int
    hard_failure_rate: float = Field(ge=0, le=1)
    overgrading_rate: float = Field(ge=0, le=1)
    dimensions: dict[CreativeEvaluationDimension, CreativeMetricEstimate]
    direction_diversity: CreativeMetricEstimate


class CreativeOperationalMetrics(StrictEvaluationModel):
    calls_per_minute_video: float = Field(ge=0)
    tokens_per_minute_video: float = Field(ge=0)
    cost_usd_per_minute_video: float = Field(ge=0)
    rendered_frames_per_minute_video: float = Field(ge=0)
    end_to_end_p50_seconds: float = Field(ge=0)
    end_to_end_p95_seconds: float = Field(ge=0)
    failure_rate: float = Field(ge=0, le=1)
    retry_count: int = Field(ge=0)
    cache_hit_rate: float = Field(ge=0, le=1)
    peak_vram_mb: float = Field(ge=0)
    human_takeover_rate: float = Field(ge=0, le=1)


class CreativeJudgeCalibration(StrictEvaluationModel):
    records: int = Field(ge=0)
    agreement_with_experts: float | None = Field(default=None, ge=0, le=1)
    same_model_agreement: float | None = Field(default=None, ge=0, le=1)
    independent_model_agreement: float | None = Field(default=None, ge=0, le=1)
    self_evaluation_gap: float | None = None
    ungrounded_rate: float | None = Field(default=None, ge=0, le=1)
    auxiliary_only: Literal[True] = True


class CreativeAgentEvaluationReport(StrictEvaluationModel):
    schema_version: str = CREATIVE_AGENT_EVALUATION_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluation_id: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_class: CreativeEvidenceClass
    dataset_version: str
    test_items: int
    reviewer_count: int
    full_vs_rule_preference: CreativeMetricEstimate
    reviewer_fleiss_kappa: float
    displayed_left_choice_rate: float = Field(ge=0, le=1)
    position_bias: float = Field(ge=0, le=0.5)
    variant_metrics: list[CreativeVariantMetrics]
    operational_metrics: CreativeOperationalMetrics
    judge_calibration: CreativeJudgeCalibration
    challenge_coverage: dict[CreativeChallengeTag, bool]
    production_evidence_audit: CreativeProductionEvidenceAudit | None
    gates: dict[str, bool]
    release_status: Literal["shadow_only", "eligible_default"]
    notes: list[str]


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z**2 / (4 * total**2)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _mean_ci(values: Sequence[float]) -> CreativeMetricEstimate:
    if not values:
        return CreativeMetricEstimate(value=0, ci95_low=0, ci95_high=1, samples=0)
    array = np.asarray(values, dtype=np.float64)
    mean = float(np.mean(array))
    if len(array) == 1:
        return CreativeMetricEstimate(
            value=mean,
            ci95_low=mean,
            ci95_high=mean,
            samples=1,
        )
    standard_error = float(np.std(array, ddof=1) / math.sqrt(len(array)))
    margin = 1.959963984540054 * standard_error
    return CreativeMetricEstimate(
        value=mean,
        ci95_low=max(0.0, mean - margin),
        ci95_high=min(1.0, mean + margin),
        samples=len(array),
    )


def build_creative_agent_review_pairs(
    candidates: Sequence[CreativeCandidateObservation],
) -> list[ReviewPair]:
    by_item: dict[str, dict[CreativePipelineVariant, CreativeCandidateObservation]] = (
        defaultdict(dict)
    )
    for candidate in candidates:
        if candidate.hard_failure:
            continue
        if candidate.variant in by_item[candidate.item_id]:
            raise ValueError(
                "review pairing requires one surviving output per item and variant"
            )
        by_item[candidate.item_id][candidate.variant] = candidate
    pairs: list[ReviewPair] = []
    for item_id, variants in sorted(by_item.items()):
        full = variants.get(CreativePipelineVariant.FULL_PIPELINE)
        if full is None:
            continue
        for variant, comparison in sorted(
            variants.items(),
            key=lambda item: item[0].value,
        ):
            if variant == CreativePipelineVariant.FULL_PIPELINE:
                continue
            pairs.append(
                ReviewPair(
                    id=f"{item_id}:{CreativePipelineVariant.FULL_PIPELINE.value}:{variant.value}",
                    source_id=item_id,
                    candidate_a_id=full.candidate_id,
                    candidate_b_id=comparison.candidate_id,
                )
            )
    return pairs


def _canonical_choice(
    review: CreativePairReview,
) -> str | None:
    if review.choice == CreativePairChoice.LEFT:
        return review.displayed_left_candidate_id
    if review.choice == CreativePairChoice.RIGHT:
        return review.displayed_right_candidate_id
    return None


def _pair_consensus(
    reviews: Iterable[CreativePairReview],
) -> str | None:
    votes: dict[str, int] = defaultdict(int)
    for review in reviews:
        selected = _canonical_choice(review)
        if selected is not None:
            votes[selected] += 1
    if not votes:
        return None
    ordered = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        return None
    return ordered[0][0]


def _variant_metrics(
    *,
    candidates: Sequence[CreativeCandidateObservation],
    reviews: Sequence[CreativePairReview],
) -> list[CreativeVariantMetrics]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    scores: dict[
        CreativePipelineVariant,
        dict[CreativeEvaluationDimension, list[float]],
    ] = defaultdict(lambda: defaultdict(list))
    for review in reviews:
        if review.choice == CreativePairChoice.REJECT:
            continue
        assert review.left_scores is not None and review.right_scores is not None
        for candidate_id, score_vector in (
            (review.displayed_left_candidate_id, review.left_scores),
            (review.displayed_right_candidate_id, review.right_scores),
        ):
            variant = candidate_by_id[candidate_id].variant
            for dimension, value in score_vector.values.items():
                scores[variant][dimension].append(value)
    output: list[CreativeVariantMetrics] = []
    for variant in CreativePipelineVariant:
        variant_candidates = [
            candidate for candidate in candidates if candidate.variant == variant
        ]
        overgrading = scores[variant][CreativeEvaluationDimension.OVERGRADING_RISK]
        diversity_values = [
            value
            for candidate in variant_candidates
            for value in candidate.direction_pairwise_distances
        ]
        output.append(
            CreativeVariantMetrics(
                variant=variant,
                candidate_count=len(variant_candidates),
                hard_failure_rate=(
                    sum(candidate.hard_failure for candidate in variant_candidates)
                    / len(variant_candidates)
                    if variant_candidates
                    else 1
                ),
                overgrading_rate=(
                    sum(value >= 0.6 for value in overgrading) / len(overgrading)
                    if overgrading
                    else 0
                ),
                dimensions={
                    dimension: _mean_ci(scores[variant][dimension])
                    for dimension in CreativeEvaluationDimension
                },
                direction_diversity=_mean_ci(diversity_values),
            )
        )
    return output


def _operational_metrics(
    candidates: Sequence[CreativeCandidateObservation],
    items: Sequence[CreativeGoldItem],
) -> CreativeOperationalMetrics:
    full = [
        candidate
        for candidate in candidates
        if candidate.variant == CreativePipelineVariant.FULL_PIPELINE
    ]
    item_duration = {item.item_id: item.duration_seconds for item in items}
    minutes = sum(item_duration[item.item_id] for item in full) / 60
    minutes = max(minutes, 1e-12)
    cache_lookups = sum(item.cache_lookups for item in full)
    wall = np.asarray([item.wall_seconds for item in full], dtype=np.float64)
    return CreativeOperationalMetrics(
        calls_per_minute_video=sum(item.model_calls for item in full) / minutes,
        tokens_per_minute_video=sum(
            item.input_tokens + item.output_tokens for item in full
        )
        / minutes,
        cost_usd_per_minute_video=sum(item.cost_usd for item in full) / minutes,
        rendered_frames_per_minute_video=sum(item.rendered_frames for item in full)
        / minutes,
        end_to_end_p50_seconds=(
            float(np.percentile(wall, 50)) if len(wall) else 0
        ),
        end_to_end_p95_seconds=(
            float(np.percentile(wall, 95)) if len(wall) else 0
        ),
        failure_rate=(
            sum(item.hard_failure for item in full) / len(full) if full else 1
        ),
        retry_count=sum(item.retries for item in full),
        cache_hit_rate=(
            sum(item.cache_hits for item in full) / cache_lookups
            if cache_lookups
            else 0
        ),
        peak_vram_mb=max((item.peak_vram_mb for item in full), default=0),
        human_takeover_rate=(
            sum(item.human_takeover for item in full) / len(full) if full else 1
        ),
    )


def _judge_calibration(
    records: Sequence[CreativeJudgeRecord],
    consensus: dict[str, str | None],
) -> CreativeJudgeCalibration:
    resolved = [
        (record, consensus.get(record.pair_id))
        for record in records
        if consensus.get(record.pair_id) is not None
        and record.selected_candidate_id is not None
    ]

    def accuracy(values: Sequence[tuple[CreativeJudgeRecord, str | None]]) -> float | None:
        if not values:
            return None
        return sum(record.selected_candidate_id == winner for record, winner in values) / len(
            values
        )

    same = [item for item in resolved if item[0].same_model_as_director]
    independent = [item for item in resolved if not item[0].same_model_as_director]
    same_accuracy = accuracy(same)
    independent_accuracy = accuracy(independent)
    return CreativeJudgeCalibration(
        records=len(records),
        agreement_with_experts=accuracy(resolved),
        same_model_agreement=same_accuracy,
        independent_model_agreement=independent_accuracy,
        self_evaluation_gap=(
            same_accuracy - independent_accuracy
            if same_accuracy is not None and independent_accuracy is not None
            else None
        ),
        ungrounded_rate=(
            sum(not record.evidence_grounded for record in records) / len(records)
            if records
            else None
        ),
    )


def evaluate_creative_agent(
    bundle: CreativeAgentEvaluationBundle,
    *,
    production_evidence_audit: CreativeProductionEvidenceAudit | None = None,
) -> CreativeAgentEvaluationReport:
    config = bundle.config
    test_items = [
        item for item in bundle.items if item.split == CreativeEvaluationSplit.TEST
    ]
    candidate_by_id = {item.candidate_id: item for item in bundle.candidates}
    reviews_by_pair: dict[str, list[CreativePairReview]] = defaultdict(list)
    for review in bundle.reviews:
        reviews_by_pair[review.pair_id].append(review)
    consensus = {
        pair_id: _pair_consensus(reviews)
        for pair_id, reviews in reviews_by_pair.items()
    }

    rule_pair_wins = 0
    rule_pair_losses = 0
    baseline_pair_count = 0
    for pair_id, reviews in reviews_by_pair.items():
        candidate_ids = {
            reviews[0].displayed_left_candidate_id,
            reviews[0].displayed_right_candidate_id,
        }
        variants = {candidate_by_id[item].variant for item in candidate_ids}
        if variants != {
            CreativePipelineVariant.FULL_PIPELINE,
            CreativePipelineVariant.RULE_BASELINE,
        }:
            continue
        baseline_pair_count += 1
        winner = consensus[pair_id]
        if winner is None:
            continue
        if candidate_by_id[winner].variant == CreativePipelineVariant.FULL_PIPELINE:
            rule_pair_wins += 1
        else:
            rule_pair_losses += 1
    decisive_rule_pairs = rule_pair_wins + rule_pair_losses
    preference = (
        rule_pair_wins / decisive_rule_pairs if decisive_rule_pairs else 0.5
    )
    preference_low, preference_high = _wilson(
        rule_pair_wins,
        decisive_rule_pairs,
    )

    valid_reviews = [
        review
        for review in bundle.reviews
        if review.choice != CreativePairChoice.REJECT
    ]
    left_choices = sum(
        review.choice == CreativePairChoice.LEFT for review in valid_reviews
    )
    right_choices = sum(
        review.choice == CreativePairChoice.RIGHT for review in valid_reviews
    )
    decisive_positions = left_choices + right_choices
    left_rate = left_choices / decisive_positions if decisive_positions else 0.5
    position_bias = abs(left_rate - 0.5)

    category_counts: list[list[int]] = []
    for pair_reviews in reviews_by_pair.values():
        candidates = sorted(
            {
                pair_reviews[0].displayed_left_candidate_id,
                pair_reviews[0].displayed_right_candidate_id,
            }
        )
        counts = [0, 0, 0]
        for review in pair_reviews:
            selected = _canonical_choice(review)
            if selected == candidates[0]:
                counts[0] += 1
            elif selected == candidates[1]:
                counts[1] += 1
            elif review.choice == CreativePairChoice.TIE:
                counts[2] += 1
        category_counts.append(counts)
    reviewer_kappa = (
        fleiss_kappa(np.asarray(category_counts, dtype=np.int64))
        if category_counts
        else 0
    )

    variant_metrics = _variant_metrics(
        candidates=bundle.candidates,
        reviews=bundle.reviews,
    )
    metrics_by_variant = {item.variant: item for item in variant_metrics}
    full_metrics = metrics_by_variant[CreativePipelineVariant.FULL_PIPELINE]
    baseline_metrics = metrics_by_variant[CreativePipelineVariant.RULE_BASELINE]

    variants_by_test_item: dict[str, set[CreativePipelineVariant]] = defaultdict(set)
    for candidate in bundle.candidates:
        if candidate.item_id in {item.item_id for item in test_items}:
            variants_by_test_item[candidate.item_id].add(candidate.variant)
    required_variants = set(config.required_variants)
    variant_coverage = bool(test_items) and all(
        required_variants <= variants_by_test_item[item.item_id]
        for item in test_items
    )
    comparison_coverage: dict[str, set[CreativePipelineVariant]] = defaultdict(set)
    for reviews in reviews_by_pair.values():
        candidate_ids = {
            reviews[0].displayed_left_candidate_id,
            reviews[0].displayed_right_candidate_id,
        }
        variants = {candidate_by_id[item].variant for item in candidate_ids}
        if CreativePipelineVariant.FULL_PIPELINE not in variants:
            continue
        comparison_coverage[reviews[0].item_id].update(
            variants - {CreativePipelineVariant.FULL_PIPELINE}
        )
    ablations_compared = bool(test_items) and all(
        required_variants - {CreativePipelineVariant.FULL_PIPELINE}
        <= comparison_coverage[item.item_id]
        for item in test_items
    )

    challenge_coverage = {
        tag: any(
            result.tag == tag
            and result.passed
            and result.security_boundary_passed
            for result in bundle.challenges
        )
        for tag in config.required_challenges
    }
    reviewers_qualified = (
        len(bundle.reviewers) >= config.minimum_reviewers
        and all(
            reviewer.color_vision_screened
            and reviewer.calibrated_display_confirmed
            for reviewer in bundle.reviewers
        )
        and all(
            len(
                {
                    review.reviewer_id
                    for review in reviews
                    if review.choice != CreativePairChoice.REJECT
                }
            )
            >= config.minimum_reviewers
            for reviews in reviews_by_pair.values()
        )
    )
    gold_qualified = bool(test_items) and all(
        item.frozen
        and item.accepted
        and item.media_origin
        in {
            CreativeMediaOrigin.CAMERA_ORIGINAL,
            CreativeMediaOrigin.LICENSED_STOCK,
            CreativeMediaOrigin.PUBLISHED_DATASET,
        }
        for item in test_items
    )
    production_evidence = (
        bundle.evidence_class == CreativeEvidenceClass.PRODUCTION
        and gold_qualified
        and production_evidence_audit is not None
        and production_evidence_audit.passed
        and production_evidence_audit.evaluation_id == bundle.evaluation_id
        and production_evidence_audit.dataset_version == bundle.dataset_version
    )
    gates = {
        "frozen_qualified_test_gold": gold_qualified,
        "minimum_three_qualified_reviewers": reviewers_qualified,
        "all_required_variants_present": variant_coverage,
        "all_ablation_comparisons_present": ablations_compared,
        "rule_baseline_pair_quota": (
            baseline_pair_count >= config.minimum_rule_baseline_pairs
        ),
        "significant_preference_over_rule_baseline": (
            preference_low > config.minimum_preference_ci95_low
        ),
        "non_waivable_failure_rate_not_increased": (
            full_metrics.hard_failure_rate <= baseline_metrics.hard_failure_rate
        ),
        "direction_diversity": (
            full_metrics.direction_diversity.value
            >= config.minimum_direction_diversity
        ),
        "position_bias_bounded": position_bias <= config.maximum_position_bias,
        "challenge_and_prompt_injection_suite": all(challenge_coverage.values()),
        "production_evidence": production_evidence,
    }
    release_status: Literal["shadow_only", "eligible_default"] = (
        "eligible_default" if all(gates.values()) else "shadow_only"
    )
    notes = [
        "LLM/VLM judge results are calibration diagnostics only and never decide release.",
        (
            "The release gate requires frozen production evidence and at least "
            "three qualified experts."
        ),
    ]
    if bundle.evidence_class == CreativeEvidenceClass.FIXTURE:
        notes.append(
            "Fixture evidence validates the evaluator implementation only; "
            "it cannot unlock default rollout."
        )
    return CreativeAgentEvaluationReport(
        evaluation_id=bundle.evaluation_id,
        input_sha256=_canonical_sha256(bundle.model_dump(mode="json")),
        evidence_class=bundle.evidence_class,
        dataset_version=bundle.dataset_version,
        test_items=len(test_items),
        reviewer_count=len(bundle.reviewers),
        full_vs_rule_preference=CreativeMetricEstimate(
            value=preference,
            ci95_low=preference_low,
            ci95_high=preference_high,
            samples=decisive_rule_pairs,
        ),
        reviewer_fleiss_kappa=reviewer_kappa,
        displayed_left_choice_rate=left_rate,
        position_bias=position_bias,
        variant_metrics=variant_metrics,
        operational_metrics=_operational_metrics(bundle.candidates, bundle.items),
        judge_calibration=_judge_calibration(bundle.judge_records, consensus),
        challenge_coverage=challenge_coverage,
        production_evidence_audit=production_evidence_audit,
        gates=gates,
        release_status=release_status,
        notes=notes,
    )


def evaluate_creative_agent_file(
    input_path: str | Path,
    output_path: str | Path,
) -> CreativeAgentEvaluationReport:
    source = Path(input_path).resolve()
    bundle = CreativeAgentEvaluationBundle.model_validate_json(
        source.read_text(encoding="utf-8")
    )
    production_evidence_audit = None
    if bundle.production_manifest is not None:
        manifest_root = source.parent.resolve()
        manifest_path = (
            manifest_root / bundle.production_manifest.relative_path
        ).resolve()
        if not manifest_path.is_relative_to(manifest_root):
            raise ValueError("production manifest path escapes the evaluation root")
        production_evidence_audit = verify_creative_production_manifest(
            bundle,
            manifest_path,
            expected_manifest_sha256=bundle.production_manifest.sha256,
        )
    report = evaluate_creative_agent(
        bundle,
        production_evidence_audit=production_evidence_audit,
    )
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(destination)
    return report
