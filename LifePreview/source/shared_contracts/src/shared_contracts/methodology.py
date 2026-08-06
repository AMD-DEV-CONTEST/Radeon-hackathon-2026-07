from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)


RuleIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=160, pattern=r"^[a-z][a-z0-9_.-]*$"),
]
ScopeIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_.:-]*$"),
]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
PromptText = Annotated[str, Field(min_length=1, max_length=40_000)]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class MethodologyContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityTier(StrEnum):
    SAFETY_RIGHTS = "safety_rights"
    TARGET_CAPABILITY = "target_capability"
    USER_REQUIREMENT = "user_requirement"
    REFERENCE_AUTHORITY = "reference_authority"
    CONTINUITY = "continuity"
    CAUSALITY_LEGIBILITY = "causality_legibility"
    CAMERA_EDITORIAL = "camera_editorial"
    STYLE = "style"
    DEFAULT = "default"


AUTHORITY_TIER_ORDER: tuple[AuthorityTier, ...] = (
    AuthorityTier.SAFETY_RIGHTS,
    AuthorityTier.TARGET_CAPABILITY,
    AuthorityTier.USER_REQUIREMENT,
    AuthorityTier.REFERENCE_AUTHORITY,
    AuthorityTier.CONTINUITY,
    AuthorityTier.CAUSALITY_LEGIBILITY,
    AuthorityTier.CAMERA_EDITORIAL,
    AuthorityTier.STYLE,
    AuthorityTier.DEFAULT,
)


class MethodologyStage(StrEnum):
    TEXT_ANALYSIS = "text_analysis"
    SHOT_PLANNING = "shot_planning"
    IMAGE_PROMPT = "image_prompt"
    VIDEO_PROMPT = "video_prompt"
    REPAIR = "repair"


class PromptModality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"


class RuleCardApplicabilityV1(MethodologyContract):
    project_types: tuple[ScopeIdentifier, ...] = ()
    stages: tuple[MethodologyStage, ...]
    operations: tuple[ScopeIdentifier, ...] = ()
    target_model_families: tuple[ScopeIdentifier, ...] = ()
    modes: tuple[ScopeIdentifier, ...] = ()

    @field_validator(
        "project_types",
        "stages",
        "operations",
        "target_model_families",
        "modes",
    )
    @classmethod
    def values_must_be_unique(cls, value: tuple[object, ...]) -> tuple[object, ...]:
        if len(value) != len(set(value)):
            raise ValueError("applicability values must be unique")
        return value


class RuleClauseV1(MethodologyContract):
    rule_id: RuleIdentifier
    authority_tier: AuthorityTier
    when: tuple[ShortText, ...] = ()
    directive: ShortText
    required_outputs: tuple[ScopeIdentifier, ...] = ()
    forbidden: tuple[ShortText, ...] = ()
    compression_priority: Annotated[int, Field(ge=0, le=100)] = 50

    @field_validator("when", "required_outputs", "forbidden")
    @classmethod
    def clause_values_must_be_unique(
        cls, value: tuple[object, ...]
    ) -> tuple[object, ...]:
        if len(value) != len(set(value)):
            raise ValueError("clause list values must be unique")
        return value


class RuleCardV1(MethodologyContract):
    schema_version: Literal["rule-card.v1"] = "rule-card.v1"
    title: ShortText
    summary: ShortText
    applicability: RuleCardApplicabilityV1
    clauses: tuple[RuleClauseV1, ...]
    examples: tuple[ShortText, ...] = ()
    counter_examples: tuple[ShortText, ...] = ()
    risks: tuple[ShortText, ...] = ()
    source: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def executable_card_has_unique_rules(self) -> "RuleCardV1":
        if not self.clauses:
            raise ValueError("an executable rule card requires at least one clause")
        rule_ids = [clause.rule_id for clause in self.clauses]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule_id must be unique inside one rule card")
        return self


class LegacyProseRuleCardV1(MethodologyContract):
    """Non-executable wrapper for pre-structured Skill fragments."""

    schema_version: Literal["legacy-prose.v1"] = "legacy-prose.v1"
    title: ShortText
    fragment: PromptText
    source: dict[str, JsonValue] = Field(default_factory=dict)


class FrozenRuleCardV1(MethodologyContract):
    skill_revision_id: UUID
    skill_key: RuleIdentifier
    revision: PositiveInt
    priority: NonNegativeInt
    digest: Sha256Digest
    card: RuleCardV1


class MethodologySnapshotV1(MethodologyContract):
    schema_version: Literal["methodology-snapshot.v1"] = (
        "methodology-snapshot.v1"
    )
    project_id: UUID
    work_unit_id: UUID | None = None
    workflow_run_id: UUID | None = None
    profile_revision_id: UUID | None = None
    ordered_cards: tuple[FrozenRuleCardV1, ...] = ()
    digest: Sha256Digest

    @model_validator(mode="after")
    def snapshot_has_unique_revisions(self) -> "MethodologySnapshotV1":
        identities = [item.skill_revision_id for item in self.ordered_cards]
        if len(identities) != len(set(identities)):
            raise ValueError("a snapshot cannot contain a revision twice")
        priorities = [item.priority for item in self.ordered_cards]
        if priorities != sorted(priorities):
            raise ValueError("ordered_cards must be sorted by priority")
        return self


class SelectedRuleV1(MethodologyContract):
    skill_revision_id: UUID
    skill_key: RuleIdentifier
    rule_id: RuleIdentifier
    authority_tier: AuthorityTier
    directive: ShortText
    required_outputs: tuple[ScopeIdentifier, ...] = ()
    forbidden: tuple[ShortText, ...] = ()
    compression_priority: Annotated[int, Field(ge=0, le=100)] = 50


class OmittedRuleV1(MethodologyContract):
    skill_revision_id: UUID
    rule_id: RuleIdentifier
    reason: ShortText


class CapabilityProfileV1(MethodologyContract):
    schema_version: Literal["capability-profile.v1"] = "capability-profile.v1"
    profile_key: ScopeIdentifier
    target_model_family: ScopeIdentifier
    modality: PromptModality
    supported_modes: tuple[ScopeIdentifier, ...] = ()
    supported_features: tuple[ScopeIdentifier, ...] = ()
    forbidden_features: tuple[ScopeIdentifier, ...] = ()
    max_prompt_characters: PositiveInt
    digest: Sha256Digest


class MethodologyBriefV1(MethodologyContract):
    schema_version: Literal["methodology-brief.v1"] = "methodology-brief.v1"
    snapshot_id: UUID
    snapshot_digest: Sha256Digest
    project_type: ScopeIdentifier
    stage: MethodologyStage
    operation: ScopeIdentifier
    target_model_family: ScopeIdentifier
    mode: ScopeIdentifier | None = None
    selected_rules: tuple[SelectedRuleV1, ...] = ()
    omitted_rules: tuple[OmittedRuleV1, ...] = ()
    capability_profile: CapabilityProfileV1
    max_methodology_characters: PositiveInt = 12_000

    @model_validator(mode="after")
    def selected_rules_are_unique(self) -> "MethodologyBriefV1":
        keys = [
            (item.skill_revision_id, item.rule_id)
            for item in self.selected_rules
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("selected methodology rules must be unique")
        return self


class ActionChainV1(MethodologyContract):
    initial_state: ShortText
    trigger: ShortText
    decisive_change: ShortText
    response: ShortText
    follow_through: ShortText
    local_endpoint: ShortText
    camera_coverage: tuple[ShortText, ...]


class ReferenceDutyV1(MethodologyContract):
    asset_ref: ShortText
    owns_dimensions: tuple[ScopeIdentifier, ...]
    must_preserve: tuple[ShortText, ...] = ()
    must_not_transfer: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def reference_owns_at_least_one_dimension(self) -> "ReferenceDutyV1":
        if not self.owns_dimensions:
            raise ValueError("a reference duty must own at least one dimension")
        if len(self.owns_dimensions) != len(set(self.owns_dimensions)):
            raise ValueError("reference dimensions must be unique")
        return self


class DirectionContractV1(MethodologyContract):
    schema_version: Literal["direction-contract.v1"] = "direction-contract.v1"
    contract_key: ScopeIdentifier
    source_mapping: dict[str, JsonValue] = Field(default_factory=dict)
    scene_function: ShortText
    dramatic_turn: ShortText
    point_of_view: ShortText
    composition: tuple[ShortText, ...]
    subtext: ShortText
    narrative_job: ShortText
    felt_intent: ShortText
    primary_spend: Literal[
        "identity",
        "action",
        "camera",
        "performance",
        "environment",
        "continuity",
    ]
    action_chain: ActionChainV1
    camera: tuple[ShortText, ...]
    performance: tuple[ShortText, ...]
    lighting: tuple[ShortText, ...]
    sound: tuple[ShortText, ...]
    continuity_locks: tuple[ShortText, ...] = ()
    completed_beats: tuple[ShortText, ...] = ()
    reserved_beats: tuple[ShortText, ...] = ()
    reference_duties: tuple[ReferenceDutyV1, ...] = ()
    safety_warnings: tuple[ShortText, ...] = ()
    capability_warnings: tuple[ShortText, ...] = ()
    applied_rule_ids: tuple[RuleIdentifier, ...]

    @model_validator(mode="after")
    def contract_has_coherent_directing_fields(self) -> "DirectionContractV1":
        if (
            not self.composition
            or not self.camera
            or not self.performance
            or not self.lighting
        ):
            raise ValueError(
                "composition, camera, performance, and lighting must each "
                "contain a direction"
            )
        if len(self.applied_rule_ids) != len(set(self.applied_rule_ids)):
            raise ValueError("applied_rule_ids must be unique")
        if not self.applied_rule_ids:
            raise ValueError("a direction contract must cite an applied rule")
        completed = set(self.completed_beats)
        reserved = set(self.reserved_beats)
        if completed & reserved:
            raise ValueError("completed and reserved beats cannot overlap")
        owners: dict[str, str] = {}
        for duty in self.reference_duties:
            for dimension in duty.owns_dimensions:
                if dimension in owners:
                    raise ValueError(
                        f"reference dimension {dimension!r} has multiple owners"
                    )
                owners[dimension] = duty.asset_ref
        return self


class CompiledPromptV1(MethodologyContract):
    role: ScopeIdentifier
    text: PromptText
    negative_text: PromptText | None = None


class CompiledPromptBundleV1(MethodologyContract):
    schema_version: Literal["compiled-prompt-bundle.v1"] = (
        "compiled-prompt-bundle.v1"
    )
    compilation_id: UUID
    methodology_snapshot_id: UUID
    methodology_snapshot_digest: Sha256Digest
    direction_contract_digest: Sha256Digest
    adapter_key: ScopeIdentifier
    adapter_version: ScopeIdentifier
    target_model_family: ScopeIdentifier
    modality: PromptModality
    prompts: tuple[CompiledPromptV1, ...]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    applied_rule_ids: tuple[RuleIdentifier, ...]
    omitted_rules: tuple[OmittedRuleV1, ...] = ()
    bundle_digest: Sha256Digest

    @model_validator(mode="after")
    def bundle_has_unique_prompt_roles(self) -> "CompiledPromptBundleV1":
        roles = [prompt.role for prompt in self.prompts]
        if not roles:
            raise ValueError("a compiled prompt bundle requires a prompt")
        if len(roles) != len(set(roles)):
            raise ValueError("compiled prompt roles must be unique")
        if len(self.applied_rule_ids) != len(set(self.applied_rule_ids)):
            raise ValueError("applied_rule_ids must be unique")
        return self
