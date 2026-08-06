from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
AGENT_CONTRACT_VERSION = "colorgraph.creative-agent-contracts/v1"

NonEmptyString = Annotated[str, Field(min_length=1, max_length=4_096)]
Identifier = Annotated[
    str,
    Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_./:-]+$"),
]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
NormalizedScore = Annotated[float, Field(ge=0, le=1)]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class AgentState(StrEnum):
    EVIDENCE_READY = "evidence_ready"
    INTERPRETED = "interpreted"
    RETRIEVED = "retrieved"
    STRATEGIZED = "strategized"
    COMPILED = "compiled"
    RENDERED = "rendered"
    CRITICIZED = "criticized"
    SELECTED = "selected"
    REFINED = "refined"
    READY = "ready"


class CreativeDirection(StrEnum):
    FAITHFUL = "faithful"
    AMPLIFIED = "amplified"
    COUNTERPOINT = "counterpoint"


class EvidenceKind(StrEnum):
    FRAME = "frame"
    CONTACT_SHEET = "contact_sheet"
    TIME_RANGE = "time_range"
    MEASUREMENT = "measurement"
    MASK = "mask"
    DEPTH = "depth"
    AUDIO = "audio"
    USER_INTENT = "user_intent"


class TechnicalMetric(StrEnum):
    EXPOSURE_EV = "exposure_ev"
    WHITE_BALANCE_TEMPERATURE = "white_balance_temperature"
    WHITE_BALANCE_TINT = "white_balance_tint"
    HIGHLIGHT_CLIPPING_RATIO = "highlight_clipping_ratio"
    SHADOW_CLIPPING_RATIO = "shadow_clipping_ratio"
    GAMUT_OUTSIDE_RATIO = "gamut_outside_ratio"
    STRUCTURE_LOSS = "structure_loss"
    MASK_COMPLETENESS = "mask_completeness"
    FRAME_RATE = "frame_rate"
    FRAME_COUNT = "frame_count"
    AUDIO_LOUDNESS_LUFS = "audio_loudness_lufs"
    AUDIO_DYNAMIC_RANGE = "audio_dynamic_range"
    MOTION_MAGNITUDE = "motion_magnitude"


class MetricUnit(StrEnum):
    EV = "ev"
    NORMALIZED = "normalized"
    RATIO = "ratio"
    FPS = "fps"
    FRAMES = "frames"
    LUFS = "lufs"
    SECONDS = "seconds"
    PIXELS_PER_FRAME = "pixels_per_frame"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    FAILURE = "failure"


class PaletteCharacter(StrEnum):
    SOURCE_FAITHFUL = "source_faithful"
    NEUTRAL = "neutral"
    COOL = "cool"
    WARM = "warm"
    MIXED_TEMPERATURE = "mixed_temperature"
    RESTRAINED = "restrained"
    SATURATED = "saturated"


class ContrastCharacter(StrEnum):
    SOFT = "soft"
    NATURAL = "natural"
    SCULPTED = "sculpted"
    DRAMATIC = "dramatic"


class ColorProperty(StrEnum):
    EXPOSURE = "exposure"
    CONTRAST = "contrast"
    SATURATION = "saturation"
    TEMPERATURE = "temperature"
    TINT = "tint"
    HIGHLIGHT_ROLLOFF = "highlight_rolloff"
    SHADOW_DENSITY = "shadow_density"
    COLOR_SEPARATION = "color_separation"


class AdjustmentDirection(StrEnum):
    DECREASE = "decrease"
    PRESERVE = "preserve"
    INCREASE = "increase"
    WARMER = "warmer"
    COOLER = "cooler"
    CONTEXT_DEPENDENT = "context_dependent"


class ProtectedAttribute(StrEnum):
    COLOR_PIPELINE = "color_pipeline"
    FINITE_VALUES = "finite_values"
    FRAME_PTS = "frame_pts"
    ASSET_INTEGRITY = "asset_integrity"
    HIGHLIGHT_DETAIL = "highlight_detail"
    SHADOW_DETAIL = "shadow_detail"
    SKIN_NEUTRALITY = "skin_neutrality"
    SNOW_NEUTRALITY = "snow_neutrality"
    STRUCTURE = "structure"
    NATURAL_SATURATION = "natural_saturation"
    PROJECT_CONTINUITY = "project_continuity"


class StrategyOperation(StrEnum):
    BALANCE = "balance"
    TONE = "tone"
    LOOK = "look"
    MASKED_GRADE = "masked_grade"
    KEYFRAME = "keyframe"
    COMPOSITE_MASK = "composite_mask"


class BaselineRelationship(StrEnum):
    PRESERVE = "preserve"
    MINOR_ADJUSTMENT = "minor_adjustment"
    INTENTIONAL_EXCEPTION = "intentional_exception"


class RetrievalRoute(StrEnum):
    SAME_SCENE_DIFFERENT_EMOTION = "same_scene_different_emotion"
    SAME_EMOTION_DIFFERENT_SCENE = "same_emotion_different_scene"
    COUNTEREXAMPLE_OR_FAILURE = "counterexample_or_failure"


class CritiqueDimension(StrEnum):
    CONCEPT_ALIGNMENT = "concept_alignment"
    SCENE_SUPPORT = "scene_support"
    VISUAL_HIERARCHY = "visual_hierarchy"
    EXPRESSIVE_STRENGTH = "expressive_strength"
    NATURALNESS = "naturalness"
    DISTINCTIVENESS = "distinctiveness"
    OVERGRADING_RISK = "overgrading_risk"
    CONTEXT_CONSISTENCY = "context_consistency"


class IntentionalExceptionKind(StrEnum):
    CONTROLLED_HIGHLIGHT_BLOOM = "controlled_highlight_bloom"
    INTENTIONAL_SHADOW_CRUSH = "intentional_shadow_crush"
    SELECTIVE_SATURATION_PUSH = "selective_saturation_push"
    CONTROLLED_STRUCTURE_SOFTENING = "controlled_structure_softening"


class ExceptionApprovalSource(StrEnum):
    AUTOMATIC = "automatic"
    USER = "user"


class ExceptionMetric(StrEnum):
    HIGHLIGHT_CLIPPING_RATIO = "highlight_clipping_ratio"
    SHADOW_CLIPPING_RATIO = "shadow_clipping_ratio"
    OVERSATURATION_RATIO = "oversaturation_ratio"
    STRUCTURE_LOSS = "structure_loss"


class TimeSpan(StrictFrozenModel):
    start_seconds: Annotated[float, Field(ge=0)]
    end_seconds: Annotated[float, Field(gt=0)]

    @model_validator(mode="after")
    def validate_order(self) -> TimeSpan:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("time span end must be greater than start")
        return self


class NormalizedRegion(StrictFrozenModel):
    x: NormalizedScore
    y: NormalizedScore
    width: Annotated[float, Field(gt=0, le=1)]
    height: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def validate_bounds(self) -> NormalizedRegion:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("normalized region must stay within the image")
        return self


class EvidenceReference(StrictFrozenModel):
    evidence_id: Identifier
    kind: EvidenceKind
    digest: Sha256
    summary: NonEmptyString
    frame_index: Annotated[int, Field(ge=0)] | None = None
    time_range: TimeSpan | None = None
    region: NormalizedRegion | None = None
    scene_id: Identifier | None = None
    shot_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_location(self) -> EvidenceReference:
        if self.kind == EvidenceKind.FRAME and self.frame_index is None:
            raise ValueError("frame evidence requires frame_index")
        if self.kind in {EvidenceKind.TIME_RANGE, EvidenceKind.AUDIO} and self.time_range is None:
            raise ValueError(f"{self.kind.value} evidence requires time_range")
        return self


class MeasurementFact(StrictFrozenModel):
    metric: TechnicalMetric
    value: float
    unit: MetricUnit
    uncertainty: Annotated[float, Field(ge=0)] | None = None
    valid_sample_ratio: NormalizedScore
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]


class TechnicalDiagnostic(StrictFrozenModel):
    diagnostic_id: Identifier
    severity: DiagnosticSeverity
    metric: TechnicalMetric
    observed: float
    threshold: float | None = None
    detail: NonEmptyString
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]


class ColorPipelineFacts(StrictFrozenModel):
    input_color_space: Identifier
    working_color_space: Identifier
    output_color_space: Identifier
    renderer_version: Identifier
    input_transform_digest: Sha256
    output_transform_digest: Sha256
    information_already_clipped: bool


class TechnicalBaseline(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-technical-baseline/v1"] = (
        "colorgraph.agent-technical-baseline/v1"
    )
    graph_digest: Sha256
    color_pipeline: ColorPipelineFacts
    measurements: list[MeasurementFact]
    diagnostics: list[TechnicalDiagnostic]
    immutable_fact_ids: list[Identifier]


class ContextBudget(StrictFrozenModel):
    maximum_images: Annotated[int, Field(gt=0, le=256)]
    maximum_image_edge: Annotated[int, Field(gt=0, le=8_192)]
    maximum_audio_seconds: Annotated[float, Field(ge=0, le=86_400)]
    maximum_tokens: Annotated[int, Field(gt=0)]
    maximum_context_bytes: Annotated[int, Field(gt=0)]


class ProjectContextPack(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-project-context/v1"] = (
        "colorgraph.agent-project-context/v1"
    )
    technical_baseline_asset_id: Identifier
    technical_baseline_sha256: Sha256
    graph_digest: Sha256
    evidence_bundle_schema_version: Identifier
    evidence_bundle_digest: Sha256
    allowed_scene_ids: Annotated[list[Identifier], Field(min_length=1)]
    allowed_shot_ids: list[Identifier]
    evidence: Annotated[list[EvidenceReference], Field(min_length=1)]
    budget: ContextBudget
    omitted_evidence_ids: list[Identifier]
    omission_reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> ProjectContextPack:
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("context evidence IDs must be unique")
        if self.omitted_evidence_ids and self.omission_reason is None:
            raise ValueError("omitted evidence requires an omission_reason")
        return self


class VisualHierarchyItem(StrictFrozenModel):
    target: Identifier
    priority: Annotated[int, Field(ge=1, le=5)]
    rationale: NonEmptyString
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]


class ColorLanguageCue(StrictFrozenModel):
    target: Identifier
    property: ColorProperty
    direction: AdjustmentDirection
    minimum_strength: NormalizedScore
    maximum_strength: NormalizedScore
    rationale: NonEmptyString

    @model_validator(mode="after")
    def validate_strength_order(self) -> ColorLanguageCue:
        if self.maximum_strength < self.minimum_strength:
            raise ValueError("maximum strength must be >= minimum strength")
        return self


class CreativeBrief(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-creative-brief/v1"] = (
        "colorgraph.agent-creative-brief/v1"
    )
    brief_id: Identifier
    scene_id: Identifier
    direction: CreativeDirection
    interpretation: NonEmptyString
    evidence_for: Annotated[list[Identifier], Field(min_length=1)]
    evidence_against: Annotated[list[Identifier], Field(min_length=1)]
    emotional_target: NonEmptyString
    visual_hierarchy: Annotated[list[VisualHierarchyItem], Field(min_length=1)]
    possible_color_language: Annotated[list[ColorLanguageCue], Field(min_length=1)]
    cliche_risks: Annotated[list[NonEmptyString], Field(min_length=1)]
    confidence: NormalizedScore
    uncertainties: list[NonEmptyString]
    failure_conditions: Annotated[list[NonEmptyString], Field(min_length=1)]


class SceneNarrativeRole(StrictFrozenModel):
    scene_id: Identifier
    shot_ids: Annotated[list[Identifier], Field(min_length=1)]
    narrative_role: NonEmptyString
    relationship_to_project_thesis: NonEmptyString
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]


class AllowedCreativeDeviation(StrictFrozenModel):
    scene_id: Identifier
    property: ColorProperty
    maximum_normalized_strength: NormalizedScore
    rationale: NonEmptyString
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]


class ProjectVisualThesis(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-project-visual-thesis/v1"] = (
        "colorgraph.agent-project-visual-thesis/v1"
    )
    thesis_id: Identifier
    project_interpretation: NonEmptyString
    palette_character: PaletteCharacter
    contrast_character: ContrastCharacter
    shared_protections: Annotated[list[ProtectedAttribute], Field(min_length=1)]
    evidence_for: Annotated[list[Identifier], Field(min_length=1)]
    evidence_against: Annotated[list[Identifier], Field(min_length=1)]
    confidence: NormalizedScore
    uncertainties: list[NonEmptyString]
    briefs: Annotated[list[CreativeBrief], Field(min_length=3)]
    scene_roles: list[SceneNarrativeRole] = Field(default_factory=list)
    allowed_deviations: list[AllowedCreativeDeviation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_three_directions_per_scene(self) -> ProjectVisualThesis:
        by_scene: dict[str, list[CreativeDirection]] = {}
        brief_ids: set[str] = set()
        for brief in self.briefs:
            if brief.brief_id in brief_ids:
                raise ValueError("creative brief IDs must be unique")
            brief_ids.add(brief.brief_id)
            by_scene.setdefault(brief.scene_id, []).append(brief.direction)
        expected = set(CreativeDirection)
        for scene_id, directions in by_scene.items():
            if len(directions) != 3 or set(directions) != expected:
                raise ValueError(
                    f"scene {scene_id!r} must contain exactly faithful, "
                    "amplified, and counterpoint briefs"
                )
        return self


class CardProvenance(StrictFrozenModel):
    source_id: Identifier
    source_uri: NonEmptyString
    source_version: Identifier
    rights: NonEmptyString
    permitted_uses: Annotated[list[Identifier], Field(min_length=1)]
    redistributable: bool


class CreativePossibilityCard(StrictFrozenModel):
    schema_version: Literal["colorgraph.creative-possibility-card/v1"] = (
        "colorgraph.creative-possibility-card/v1"
    )
    card_id: Identifier
    card_version: Identifier
    provenance: CardProvenance
    concept: NonEmptyString
    possible_visual_cues: Annotated[list[NonEmptyString], Field(min_length=1)]
    possible_grade_strategies: Annotated[list[NonEmptyString], Field(min_length=1)]
    alternatives: Annotated[list[NonEmptyString], Field(min_length=1)]
    cliche_risks: Annotated[list[NonEmptyString], Field(min_length=1)]
    counterexamples: Annotated[list[NonEmptyString], Field(min_length=1)]
    scene_terms: Annotated[list[NonEmptyString], Field(min_length=1)]
    emotion_terms: Annotated[list[NonEmptyString], Field(min_length=1)]
    route_support: Annotated[list[RetrievalRoute], Field(min_length=1)]
    media_types: Annotated[list[Identifier], Field(min_length=1)]
    color_domains: Annotated[list[Identifier], Field(min_length=1)]
    scopes: Annotated[list[Identifier], Field(min_length=1)]
    required_capabilities: list[Identifier]
    compatible_protections: Annotated[list[ProtectedAttribute], Field(min_length=1)]
    template_family: Identifier
    reference_asset_uris: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_publishable_assets(self) -> CreativePossibilityCard:
        if self.reference_asset_uris and not self.provenance.redistributable:
            raise ValueError(
                "possibility cards with reference assets must be redistributable"
            )
        if "creative_retrieval" not in self.provenance.permitted_uses:
            raise ValueError(
                "possibility card provenance must permit creative_retrieval"
            )
        return self


class OperationParameterSpec(StrictFrozenModel):
    name: Identifier
    unit: Identifier
    minimum: float
    maximum: float
    semantic: NonEmptyString

    @model_validator(mode="after")
    def validate_bounds(self) -> OperationParameterSpec:
        if self.maximum < self.minimum:
            raise ValueError("operation parameter maximum must be >= minimum")
        return self


class OperationCard(StrictFrozenModel):
    schema_version: Literal["colorgraph.operation-card/v1"] = (
        "colorgraph.operation-card/v1"
    )
    card_id: Identifier
    card_version: Identifier
    provenance: CardProvenance
    operation: StrategyOperation
    parameters: Annotated[list[OperationParameterSpec], Field(min_length=1)]
    supported_color_spaces: Annotated[list[Identifier], Field(min_length=1)]
    scopes: Annotated[list[Identifier], Field(min_length=1)]
    reversibility: bool
    information_loss: bool
    requires_linear_light: bool
    must_precede: list[StrategyOperation]
    must_follow: list[StrategyOperation]
    conflicts_with: list[StrategyOperation]
    may_cause: list[NonEmptyString]
    validation_checks: Annotated[list[Identifier], Field(min_length=1)]
    repair_guidance: Annotated[list[NonEmptyString], Field(min_length=1)]
    invalidation_scope: NonEmptyString
    renderer_node_type: Identifier | None = None
    parameter_mapping: dict[Identifier, Identifier] = Field(default_factory=dict)
    order_hint: Annotated[int, Field(ge=1, le=199)] | None = None
    requires_mask: bool = False
    allowed_mask_targets: list[Identifier] = Field(default_factory=list)
    composite_expression: NonEmptyString | None = None
    conflicts_with_protections: list[ProtectedAttribute] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_renderer_mapping(self) -> OperationCard:
        parameter_names = {item.name for item in self.parameters}
        if self.parameter_mapping and set(self.parameter_mapping) != parameter_names:
            raise ValueError(
                "operation card parameter mapping must cover every parameter exactly"
            )
        if self.requires_mask and not self.allowed_mask_targets:
            raise ValueError("masked operation card requires allowed mask targets")
        if not self.requires_mask and self.allowed_mask_targets:
            raise ValueError("unmasked operation card cannot advertise mask targets")
        if self.operation == StrategyOperation.COMPOSITE_MASK:
            if self.composite_expression is None:
                raise ValueError("composite-mask card requires an expression")
        elif self.composite_expression is not None:
            raise ValueError("only composite-mask cards may declare an expression")
        return self


class FailureCard(StrictFrozenModel):
    schema_version: Literal["colorgraph.failure-card/v1"] = (
        "colorgraph.failure-card/v1"
    )
    card_id: Identifier
    card_version: Identifier
    provenance: CardProvenance
    failure_class: Identifier
    applicable_operations: Annotated[list[StrategyOperation], Field(min_length=1)]
    failure_evidence: Annotated[list[NonEmptyString], Field(min_length=1)]
    detection_checks: Annotated[list[Identifier], Field(min_length=1)]
    repair_steps: Annotated[list[NonEmptyString], Field(min_length=1)]


class RetrievedPossibility(StrictFrozenModel):
    card_id: Identifier
    card_version: Identifier
    route: RetrievalRoute
    score: NormalizedScore
    source_uri: NonEmptyString
    rights: NonEmptyString
    selected_reason: NonEmptyString | None = None
    excluded_reason: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> RetrievedPossibility:
        if (self.selected_reason is None) == (self.excluded_reason is None):
            raise ValueError("retrieved possibility requires exactly one selected/excluded reason")
        return self


class BriefRetrieval(StrictFrozenModel):
    brief_id: Identifier
    query: NonEmptyString
    route: RetrievalRoute
    results: list[RetrievedPossibility]
    low_relevance_rejected: bool


class RetrievalExpansion(StrictFrozenModel):
    brief_id: Identifier
    frozen_brief_sha256: Sha256
    selected_card_ids: list[Identifier]
    expanded_possibilities: list[NonEmptyString]
    challenges: list[NonEmptyString]
    convergence_risk: bool


class RetrievalBundle(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-retrieval-bundle/v1"] = (
        "colorgraph.agent-retrieval-bundle/v1"
    )
    thesis_asset_id: Identifier
    thesis_sha256: Sha256
    retrievals: Annotated[list[BriefRetrieval], Field(min_length=3)]
    index_version: Identifier
    empty_bundle_reason: NonEmptyString | None = None
    selected_cards: list[CreativePossibilityCard] = Field(default_factory=list)
    expansions: list[RetrievalExpansion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_routes(self) -> RetrievalBundle:
        routes_by_brief: dict[str, set[RetrievalRoute]] = {}
        for retrieval in self.retrievals:
            routes_by_brief.setdefault(retrieval.brief_id, set()).add(retrieval.route)
        expected = set(RetrievalRoute)
        for brief_id, routes in routes_by_brief.items():
            if routes != expected:
                raise ValueError(f"brief {brief_id!r} must record all three retrieval routes")
        selected_ids = {
            result.card_id
            for retrieval in self.retrievals
            for result in retrieval.results
            if result.selected_reason is not None
        }
        selected_card_ids = {card.card_id for card in self.selected_cards}
        if selected_card_ids != selected_ids:
            raise ValueError(
                "selected card snapshots must exactly match selected retrieval results"
            )
        if not selected_ids and self.empty_bundle_reason is None:
            raise ValueError("an empty retrieval bundle requires a reason")
        if selected_ids and self.empty_bundle_reason is not None:
            raise ValueError("a non-empty retrieval bundle cannot have an empty reason")
        if self.expansions:
            expanded_briefs = [item.brief_id for item in self.expansions]
            if len(expanded_briefs) != len(set(expanded_briefs)):
                raise ValueError("retrieval expansions must be unique per brief")
            if any(
                not set(item.selected_card_ids) <= selected_ids
                for item in self.expansions
            ):
                raise ValueError("retrieval expansion references an unselected card")
        return self


class StrategyScope(StrictFrozenModel):
    project_id: Identifier
    scene_id: Identifier | None = None
    shot_id: Identifier | None = None
    time_range: TimeSpan | None = None
    mask_target: Identifier | None = None


class IntentionalException(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-intentional-exception/v1"] = (
        "colorgraph.agent-intentional-exception/v1"
    )
    exception_id: Identifier
    kind: IntentionalExceptionKind
    reason: NonEmptyString
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    scope: StrategyScope
    metric: ExceptionMetric
    maximum_metric_value: Annotated[float, Field(ge=0, le=1)]
    protected_attributes: Annotated[list[ProtectedAttribute], Field(min_length=1)]
    approval_source: ExceptionApprovalSource
    approval_reference: Identifier | None = None
    source_graph_digest: Sha256
    candidate_digest: Sha256
    declared_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    invalidation_conditions: Annotated[list[NonEmptyString], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_allowlisted_shape(self) -> IntentionalException:
        expected = {
            IntentionalExceptionKind.CONTROLLED_HIGHLIGHT_BLOOM: (
                ExceptionMetric.HIGHLIGHT_CLIPPING_RATIO,
                ProtectedAttribute.HIGHLIGHT_DETAIL,
            ),
            IntentionalExceptionKind.INTENTIONAL_SHADOW_CRUSH: (
                ExceptionMetric.SHADOW_CLIPPING_RATIO,
                ProtectedAttribute.SHADOW_DETAIL,
            ),
            IntentionalExceptionKind.SELECTIVE_SATURATION_PUSH: (
                ExceptionMetric.OVERSATURATION_RATIO,
                ProtectedAttribute.NATURAL_SATURATION,
            ),
            IntentionalExceptionKind.CONTROLLED_STRUCTURE_SOFTENING: (
                ExceptionMetric.STRUCTURE_LOSS,
                ProtectedAttribute.STRUCTURE,
            ),
        }
        expected_metric, expected_attribute = expected[self.kind]
        if self.metric != expected_metric:
            raise ValueError("intentional exception kind does not match its metric")
        if set(self.protected_attributes) != {expected_attribute}:
            raise ValueError(
                "intentional exception may only name its allowlisted protected attribute"
            )
        if (
            self.kind
            in {
                IntentionalExceptionKind.CONTROLLED_HIGHLIGHT_BLOOM,
                IntentionalExceptionKind.SELECTIVE_SATURATION_PUSH,
                IntentionalExceptionKind.CONTROLLED_STRUCTURE_SOFTENING,
            }
            and self.scope.mask_target is None
        ):
            raise ValueError("this intentional exception kind requires a local mask target")
        if (
            self.approval_source == ExceptionApprovalSource.USER
            and self.approval_reference is None
        ):
            raise ValueError("user-approved exceptions require an approval reference")
        if (
            self.approval_source == ExceptionApprovalSource.AUTOMATIC
            and self.approval_reference is not None
        ):
            raise ValueError("automatic exceptions cannot claim a user approval reference")
        if self.expires_at is not None and self.expires_at <= self.declared_at:
            raise ValueError("intentional exception expiry must follow its declaration")
        return self


class StrategyParameter(StrictFrozenModel):
    name: Identifier
    unit: Identifier
    minimum: float
    nominal: float
    maximum: float

    @model_validator(mode="after")
    def validate_range(self) -> StrategyParameter:
        if not self.minimum <= self.nominal <= self.maximum:
            raise ValueError("strategy parameter nominal must be inside its range")
        return self


class StrategyTrackPoint(StrictFrozenModel):
    time_seconds: Annotated[float, Field(ge=0)]
    value: float


class StrategyParameterTrack(StrictFrozenModel):
    parameter: Identifier
    points: Annotated[list[StrategyTrackPoint], Field(min_length=2)]
    interpolation: Identifier = "pchip"

    @model_validator(mode="after")
    def validate_points(self) -> StrategyParameterTrack:
        timestamps = [item.time_seconds for item in self.points]
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise ValueError("strategy track points must have sorted unique times")
        return self


class StrategyAction(StrictFrozenModel):
    action_id: Identifier
    operation: StrategyOperation
    scope: StrategyScope
    parameters: Annotated[list[StrategyParameter], Field(min_length=1)]
    serves_brief_id: Identifier
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    protected_attributes: list[ProtectedAttribute]
    rationale: NonEmptyString
    capability_id: Identifier | None = None
    intended_property: ColorProperty | None = None
    direction: AdjustmentDirection | None = None
    baseline_relationship: BaselineRelationship = BaselineRelationship.PRESERVE
    parameter_tracks: list[StrategyParameterTrack] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tracks(self) -> StrategyAction:
        parameter_names = {item.name for item in self.parameters}
        track_names = [item.parameter for item in self.parameter_tracks]
        if len(track_names) != len(set(track_names)):
            raise ValueError("strategy action parameter tracks must be unique")
        if not set(track_names) <= parameter_names:
            raise ValueError("strategy track references an unknown action parameter")
        return self


class ColorStrategy(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-color-strategy/v1"] = (
        "colorgraph.agent-color-strategy/v1"
    )
    strategy_id: Identifier
    brief_id: Identifier
    technical_baseline_asset_id: Identifier
    technical_baseline_sha256: Sha256
    common_language: NonEmptyString
    actions: Annotated[list[StrategyAction], Field(min_length=1)]
    alternatives_not_selected: Annotated[list[NonEmptyString], Field(min_length=1)]
    continuity_constraints: Annotated[list[ProtectedAttribute], Field(min_length=1)]
    failure_conditions: Annotated[list[NonEmptyString], Field(min_length=1)]
    intentional_exceptions: list[IntentionalException] = Field(default_factory=list)
    project_thesis_sha256: Sha256 | None = None
    retrieval_bundle_sha256: Sha256 | None = None
    selected_possibility_card_ids: list[Identifier] = Field(default_factory=list)
    scene_role: NonEmptyString | None = None
    tonal_structure: list[NonEmptyString] = Field(default_factory=list)
    color_relationships: list[NonEmptyString] = Field(default_factory=list)
    visual_hierarchy: list[NonEmptyString] = Field(default_factory=list)
    local_region_intents: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_ids(self) -> ColorStrategy:
        identifiers = [action.action_id for action in self.actions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("strategy action IDs must be unique")
        return self


class GraphChange(StrictFrozenModel):
    action_id: Identifier
    node_id: Identifier
    operation: Literal["add", "update", "disable"]
    parameter: Identifier | None = None
    before_value: float | int | str | bool | None = None
    after_value: float | int | str | bool | None = None


class CompiledCandidate(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-compiled-candidate/v1"] = (
        "colorgraph.agent-compiled-candidate/v1"
    )
    candidate_id: Identifier
    strategy_id: Identifier
    source_graph_digest: Sha256
    compiled_graph_digest: Sha256
    undo_graph_digest: Sha256
    graph_changes: Annotated[list[GraphChange], Field(min_length=1)]
    operation_card_versions: dict[Identifier, Identifier]
    compiler_version: Identifier
    validation_passed: bool

    @model_validator(mode="after")
    def require_valid_candidate(self) -> CompiledCandidate:
        if not self.validation_passed:
            raise ValueError("a compiled candidate asset must have passed validation")
        if self.source_graph_digest != self.undo_graph_digest:
            raise ValueError("undo graph digest must equal the source graph digest")
        return self


class RenderedFrameEvidence(StrictFrozenModel):
    frame_index: Annotated[int, Field(ge=0)]
    time_seconds: Annotated[float, Field(ge=0)]
    output_digest: Sha256
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    hard_checks_passed: bool
    failed_check_ids: list[Identifier]


class RenderedCandidate(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-rendered-candidate/v1"] = (
        "colorgraph.agent-rendered-candidate/v1"
    )
    candidate_id: Identifier
    compiled_asset_id: Identifier
    compiled_sha256: Sha256
    renderer_version: Identifier
    frames: Annotated[list[RenderedFrameEvidence], Field(min_length=1)]
    render_manifest_digest: Sha256


class CritiqueEvidenceRole(StrEnum):
    SOURCE = "source"
    CURRENT = "current"
    CANDIDATE = "candidate"
    NEIGHBOR = "neighbor"


class CritiqueFrameRegion(StrictFrozenModel):
    evidence_id: Identifier
    role: CritiqueEvidenceRole
    frame_index: Annotated[int, Field(ge=0)]
    time_seconds: Annotated[float, Field(ge=0)]
    region: NormalizedRegion
    observation: NonEmptyString


class CritiqueScore(StrictFrozenModel):
    dimension: CritiqueDimension
    score: NormalizedScore
    confidence: NormalizedScore
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    counterevidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    concise_reason: NonEmptyString
    frame_regions: list[CritiqueFrameRegion] = Field(default_factory=list)
    counter_frame_regions: list[CritiqueFrameRegion] = Field(default_factory=list)


class VisualCritique(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-visual-critique/v1"] = (
        "colorgraph.agent-visual-critique/v1"
    )
    candidate_id: Identifier
    rendered_asset_id: Identifier
    rendered_sha256: Sha256
    blind_order_digest: Sha256
    position_swap_consistent: bool
    technical_integrity_asset_id: Identifier
    technical_integrity_sha256: Sha256
    scores: Annotated[list[CritiqueScore], Field(min_length=8, max_length=8)]

    @model_validator(mode="after")
    def validate_dimensions(self) -> VisualCritique:
        dimensions = [score.dimension for score in self.scores]
        if len(set(dimensions)) != len(CritiqueDimension):
            raise ValueError("visual critique must contain each dimension exactly once")
        return self


class SelectionDecision(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-selection-decision/v1"] = (
        "colorgraph.agent-selection-decision/v1"
    )
    selected_candidate_id: Identifier
    runner_up_candidate_id: Identifier
    pareto_candidate_ids: Annotated[list[Identifier], Field(min_length=2)]
    gate_trace: Annotated[list[Identifier], Field(min_length=1)]
    selection_digest: Sha256

    @model_validator(mode="after")
    def validate_candidates(self) -> SelectionDecision:
        if self.selected_candidate_id == self.runner_up_candidate_id:
            raise ValueError("selected candidate and runner-up must differ")
        if self.selected_candidate_id not in self.pareto_candidate_ids:
            raise ValueError("selected candidate must belong to the Pareto set")
        if self.runner_up_candidate_id not in self.pareto_candidate_ids:
            raise ValueError("runner-up must belong to the Pareto set")
        return self


class PatchChange(StrictFrozenModel):
    node_id: Identifier
    parameter: Identifier
    before_value: float
    after_value: float
    scope: StrategyScope


class ReflectionPatch(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-reflection-patch/v1"] = (
        "colorgraph.agent-reflection-patch/v1"
    )
    patch_id: Identifier
    parent_candidate_id: Identifier
    hypothesis: NonEmptyString
    target_dimensions: Annotated[list[CritiqueDimension], Field(min_length=1)]
    maximum_allowed_regression: NormalizedScore
    changes: Annotated[list[PatchChange], Field(min_length=1)]
    locked_node_ids: list[Identifier]
    expected_improvement: NonEmptyString


class FailureCase(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-failure-case/v1"] = "colorgraph.agent-failure-case/v1"
    failure_id: Identifier
    candidate_id: Identifier | None = None
    patch_id: Identifier | None = None
    context_asset_id: Identifier
    operation_summary: NonEmptyString
    actual_harm: NonEmptyString
    responsible_node_ids: list[Identifier]
    repair_summary: NonEmptyString | None = None
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    reviewed_for_reuse: bool = False
    contains_private_data: bool = True


class ReadyResult(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-ready-result/v1"] = "colorgraph.agent-ready-result/v1"
    selected_candidate_id: Identifier
    selected_graph_digest: Sha256
    runner_up_candidate_id: Identifier
    ready_for_user_review: bool
    current_graph_unchanged: bool


class ManifestAssetEntry(StrictFrozenModel):
    state: AgentState
    asset_id: Identifier
    asset_sha256: Sha256
    payload_schema_version: Identifier
    parent_asset_id: Identifier | None = None


class AgentRunManifest(StrictFrozenModel):
    schema_version: Literal["colorgraph.agent-run-manifest/v1"] = "colorgraph.agent-run-manifest/v1"
    run_id: Identifier
    project_id: Identifier
    graph_digest: Sha256
    current_state: AgentState | None
    assets: list[ManifestAssetEntry]
    completed: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


type AgentPayload = Annotated[
    TechnicalBaseline
    | ProjectContextPack
    | ProjectVisualThesis
    | RetrievalBundle
    | ColorStrategy
    | CompiledCandidate
    | RenderedCandidate
    | VisualCritique
    | SelectionDecision
    | ReflectionPatch
    | FailureCase
    | ReadyResult
    | AgentRunManifest,
    Field(discriminator="schema_version"),
]


class AgentAssetRecord(StrictFrozenModel):
    asset_id: Identifier
    project_id: Identifier
    scene_id: Identifier | None = None
    shot_id: Identifier | None = None
    input_digest: Sha256
    prompt_version: Identifier
    model_id: Identifier
    model_revision: Identifier
    tool_versions: dict[Identifier, Identifier]
    created_at: AwareDatetime
    parent_asset_id: Identifier | None = None
    parent_sha256: Sha256 | None = None
    payload: AgentPayload

    @model_validator(mode="after")
    def validate_parent_pair(self) -> AgentAssetRecord:
        if (self.parent_asset_id is None) != (self.parent_sha256 is None):
            raise ValueError("parent asset ID and SHA-256 must be provided together")
        return self


def canonical_sha256(value: BaseModel | dict[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _asset_identity(record: AgentAssetRecord) -> str:
    payload = record.model_dump(
        mode="json",
        exclude={"asset_id", "created_at"},
    )
    return canonical_sha256(payload)


class SignedAgentAsset(AgentAssetRecord):
    sha256: Sha256

    @model_validator(mode="after")
    def validate_signature_and_identity(self) -> SignedAgentAsset:
        unsigned = AgentAssetRecord.model_validate(
            self.model_dump(mode="python", exclude={"sha256"})
        )
        expected_sha = canonical_sha256(unsigned)
        if self.sha256 != expected_sha:
            raise ValueError("agent asset SHA-256 signature mismatch")
        expected_suffix = _asset_identity(unsigned)[:24]
        if not self.asset_id.endswith(expected_suffix):
            raise ValueError("agent asset ID does not match its immutable content")
        return self


def sign_agent_asset(
    *,
    project_id: str,
    input_digest: str,
    payload: AgentPayload,
    prompt_version: str,
    model_id: str,
    model_revision: str,
    tool_versions: dict[str, str],
    scene_id: str | None = None,
    shot_id: str | None = None,
    parent: SignedAgentAsset | None = None,
    created_at: datetime | None = None,
) -> SignedAgentAsset:
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("agent asset created_at must be timezone-aware")
    schema_label = payload.schema_version.split("/")[-1].replace("-", "_")
    provisional = AgentAssetRecord(
        asset_id=f"{schema_label}_{'0' * 24}",
        project_id=project_id,
        scene_id=scene_id,
        shot_id=shot_id,
        input_digest=input_digest,
        prompt_version=prompt_version,
        model_id=model_id,
        model_revision=model_revision,
        tool_versions=tool_versions,
        created_at=timestamp,
        parent_asset_id=parent.asset_id if parent else None,
        parent_sha256=parent.sha256 if parent else None,
        payload=payload,
    )
    identity = _asset_identity(provisional)
    record = provisional.model_copy(update={"asset_id": f"{schema_label}_{identity[:24]}"})
    return SignedAgentAsset(
        **record.model_dump(mode="python"),
        sha256=canonical_sha256(record),
    )
