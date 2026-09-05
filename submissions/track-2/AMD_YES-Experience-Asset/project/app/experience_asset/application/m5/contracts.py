"""Read-only E5 handoff and isolated E6/M5 application contracts.

These types are views and commands, not new durable domain authorities. They
reuse the canonical E1 domain symbols and keep relation state outside immutable
``ExperienceAssetV1`` snapshots.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.experience_asset.domain.enums import (
    ConfirmationState,
    FindingSeverity,
    PrivacyResolution,
    ReadinessLifecycle,
    RouteType,
    StatementStatus,
)
from app.experience_asset.domain.models import (
    ApprovalRecord,
    ContractModel,
    NonEmptyText,
    PrivacyFinding,
    RouteDecision,
    RouteDraft,
    Sha256,
    SourceReference,
    Statement,
)
from app.experience_asset.domain.relation import KnowledgeCardReadinessRecordV1

M5_SCHEMA_IDENTITY = "experience-asset/1.0.0"
M5_WORKFLOW_IDENTITY = "experience-asset/e6-m5-isolated/v1"
M5_ROUTE_POLICY_IDENTITY = "m5-route-policy-v1"


class RelationOutcomeV1(StrEnum):
    NO_MATCH = "NO_MATCH"
    DECLINED = "DECLINED"
    CONFIRMED_RELATION = "CONFIRMED_RELATION"
    STALE = "STALE"


class PrivacyCategoryV1(StrEnum):
    IDENTITY = "IDENTITY"
    HEALTH_BODY = "HEALTH_BODY"
    LOCATION = "LOCATION"
    PURCHASE_PAYMENT = "PURCHASE_PAYMENT"
    THIRD_PARTY = "THIRD_PARTY"
    SCREENSHOT_METADATA = "SCREENSHOT_METADATA"
    COPYRIGHT = "COPYRIGHT"
    UNVERIFIED_BRAND_CLAIM = "UNVERIFIED_BRAND_CLAIM"
    PROFESSIONAL_ADVICE = "PROFESSIONAL_ADVICE"


class PrivacyActionV1(StrEnum):
    KEEP = "KEEP"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    GENERALIZE = "GENERALIZE"
    REMOVE = "REMOVE"


class PrivacyReviewStatusV1(StrEnum):
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class PrivacyProposalSourceV1(StrEnum):
    """Producers a review is allowed to count as a trustworthy risk proposer.

    Recorded on the review and bound into its hash. Without this, a review built
    when every producer was unavailable is byte-identical to one built over
    genuinely clean content, and "we found nothing" becomes indistinguishable
    from "nothing looked".
    """

    CANONICAL_SENSITIVITY_TAGS = "CANONICAL_SENSITIVITY_TAGS"
    DETERMINISTIC_TEXT_DETECTOR = "DETERMINISTIC_TEXT_DETECTOR"
    USER_PROVIDED = "USER_PROVIDED"


class M5RelationProjectionV1(ContractModel):
    """Contract-equivalent read-only view of E5's sidecar relation ledger."""

    bound_asset_id: UUID
    bound_version_id: UUID
    bound_content_hash: Sha256
    outcome: RelationOutcomeV1
    projection_hash: Sha256
    is_current: bool = True
    confirmed_relation_id: UUID | None = None
    confirmed_related_asset_id: UUID | None = None
    confirmed_related_version_id: UUID | None = None
    confirmed_related_content_hash: Sha256 | None = None
    authorized_historical_statement_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def detail_requires_a_confirmed_relation(self) -> M5RelationProjectionV1:
        has_confirmation = (
            self.confirmed_relation_id is not None
            and self.confirmed_related_asset_id is not None
            and self.confirmed_related_version_id is not None
            and self.confirmed_related_content_hash is not None
        )
        if self.outcome is RelationOutcomeV1.CONFIRMED_RELATION:
            if not has_confirmation:
                raise ValueError("CONFIRMED_RELATION requires exact relation identities")
        elif has_confirmation or self.authorized_historical_statement_ids:
            raise ValueError("only CONFIRMED_RELATION may expose relation detail")
        elif any(
            value is not None
            for value in (
                self.confirmed_relation_id,
                self.confirmed_related_asset_id,
                self.confirmed_related_version_id,
                self.confirmed_related_content_hash,
            )
        ):
            raise ValueError("unconfirmed outcomes cannot carry partial relation identities")
        if self.outcome is RelationOutcomeV1.STALE and self.is_current:
            raise ValueError("STALE relation outcome must not be marked current")
        if len(self.authorized_historical_statement_ids) != len(
            set(self.authorized_historical_statement_ids)
        ):
            raise ValueError("authorized historical statement IDs must be unique")
        return self


class M5EvidenceIndexV1(ContractModel):
    """Deterministic route-policy signals composed from current/E5 evidence."""

    decision_context: list[UUID] = Field(default_factory=list)
    personal_lesson: list[UUID] = Field(default_factory=list)
    beginner_prerequisite: list[UUID] = Field(default_factory=list)
    beginner_guidance_basis: list[UUID] = Field(default_factory=list)
    common_mistake_or_risk: list[UUID] = Field(default_factory=list)
    peer_comparison: list[UUID] = Field(default_factory=list)
    peer_evidence: list[UUID] = Field(default_factory=list)
    tradeoff_or_constraint: list[UUID] = Field(default_factory=list)
    qualifying_context: list[UUID] = Field(default_factory=list)
    verifiable_result: list[UUID] = Field(default_factory=list)
    event_arc: list[UUID] = Field(default_factory=list)
    transferable_lesson: list[UUID] = Field(default_factory=list)
    applicability_boundary: list[UUID] = Field(default_factory=list)
    disclosure_basis: list[UUID] = Field(default_factory=list)
    unsupported_universal_claim: list[UUID] = Field(default_factory=list)
    unsupported_professional_claim: list[UUID] = Field(default_factory=list)
    unresolved_statement_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def signal_ids_are_unique(self) -> M5EvidenceIndexV1:
        for field_name in type(self).model_fields:
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} statement IDs must be unique")
        return self

    def referenced_statement_ids(self) -> set[UUID]:
        references: set[UUID] = set()
        for field_name in type(self).model_fields:
            references.update(getattr(self, field_name))
        return references


class M5ContextProjectionV1(ContractModel):
    """Read-only M5 input; it never becomes a second persistence authority."""

    asset_id: UUID
    version_id: UUID
    content_hash: Sha256
    current_version_id: UUID
    readiness: KnowledgeCardReadinessRecordV1 | None = None
    statements: list[Statement] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    evidence: M5EvidenceIndexV1
    relation: M5RelationProjectionV1
    schema_identity: NonEmptyText
    workflow_identity: NonEmptyText
    policy_identity: NonEmptyText
    model_run_id: UUID | None = None

    @model_validator(mode="after")
    def references_are_authorized(self) -> M5ContextProjectionV1:
        current_statement_ids = {statement.statement_id for statement in self.statements}
        if len(current_statement_ids) != len(self.statements):
            raise ValueError("current statement IDs must be unique")
        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("current source IDs must be unique")
        if any(
            not set(statement.source_refs).issubset(source_ids)
            for statement in self.statements
        ):
            raise ValueError("current statement references an unknown source")
        allowed = current_statement_ids | set(
            self.relation.authorized_historical_statement_ids
        )
        unknown = self.evidence.referenced_statement_ids() - allowed
        if unknown:
            raise ValueError("route evidence contains unauthorized statement IDs")
        unusable_current_ids = {
            statement.statement_id
            for statement in self.statements
            if statement.status is StatementStatus.UNRESOLVED
            or statement.confirmation
            in {ConfirmationState.CORRECTED, ConfirmationState.REJECTED}
        }
        support_field_names = (
            "decision_context",
            "personal_lesson",
            "beginner_prerequisite",
            "beginner_guidance_basis",
            "common_mistake_or_risk",
            "peer_comparison",
            "peer_evidence",
            "tradeoff_or_constraint",
            "qualifying_context",
            "verifiable_result",
            "event_arc",
            "transferable_lesson",
            "applicability_boundary",
            "disclosure_basis",
        )
        supporting_ids = {
            statement_id
            for field_name in support_field_names
            for statement_id in getattr(self.evidence, field_name)
        }
        if supporting_ids & unusable_current_ids:
            raise ValueError("route support cannot use unresolved or invalidated statements")
        unresolved_ids = set(self.evidence.unresolved_statement_ids)
        if unresolved_ids & supporting_ids:
            raise ValueError("one statement cannot be both route support and unresolved")
        current_by_id = {
            statement.statement_id: statement for statement in self.statements
        }
        if any(
            statement_id not in current_by_id
            or current_by_id[statement_id].status is not StatementStatus.UNRESOLVED
            for statement_id in unresolved_ids
        ):
            raise ValueError("unresolved route references must be current unresolved statements")
        return self

    def stale_reason(self) -> str | None:
        if self.readiness is None:
            return "M5_INPUT_NOT_READY"
        if (
            self.schema_identity != M5_SCHEMA_IDENTITY
            or self.workflow_identity != M5_WORKFLOW_IDENTITY
            or self.policy_identity != M5_ROUTE_POLICY_IDENTITY
        ):
            return "M5_INPUT_STALE"
        if self.current_version_id != self.version_id:
            return "M5_INPUT_STALE"
        if self.relation.outcome is RelationOutcomeV1.STALE:
            return "M5_INPUT_STALE"
        # E5 mints readiness as an append-only sidecar record rather than
        # deleting it on invalidation, so a record that exists is not a record
        # that still holds. Reading only the hashes would let an INVALIDATED
        # readiness re-authorize M5 against a card the user already withdrew.
        if self.readiness.lifecycle is not ReadinessLifecycle.ACTIVE:
            return "M5_INPUT_STALE"
        if (
            self.readiness.asset_id != self.asset_id
            or self.readiness.version_id != self.version_id
            or self.readiness.knowledge_card_hash != self.content_hash
            or self.relation.bound_asset_id != self.asset_id
            or self.relation.bound_version_id != self.version_id
            or self.relation.bound_content_hash != self.content_hash
            or not self.relation.is_current
        ):
            return "M5_INPUT_STALE"
        return None


class PrivacyFindingProposalV1(ContractModel):
    """Untrusted local-model/detector proposal before Runtime validation."""

    category: PrivacyCategoryV1
    affected_statement_ids: list[UUID] = Field(default_factory=list)
    affected_source_ids: list[UUID] = Field(default_factory=list)
    severity: FindingSeverity
    explanation: NonEmptyText

    @model_validator(mode="after")
    def finding_has_an_exact_reference(self) -> PrivacyFindingProposalV1:
        if not self.affected_statement_ids and not self.affected_source_ids:
            raise ValueError("privacy proposal requires an affected statement or source")
        if len(self.affected_statement_ids) != len(set(self.affected_statement_ids)):
            raise ValueError("privacy proposal statement IDs must be unique")
        if len(self.affected_source_ids) != len(set(self.affected_source_ids)):
            raise ValueError("privacy proposal source IDs must be unique")
        return self


class PrivacyReviewV1(ContractModel):
    asset_id: UUID
    version_id: UUID
    content_hash: Sha256
    policy_version: NonEmptyText
    status: PrivacyReviewStatusV1
    findings: list[PrivacyFinding] = Field(default_factory=list)
    review_hash: Sha256
    failure_code: NonEmptyText | None = None
    proposal_sources: list[PrivacyProposalSourceV1] = Field(default_factory=list)
    detector_version: NonEmptyText | None = None

    @model_validator(mode="after")
    def status_matches_failure(self) -> PrivacyReviewV1:
        if self.status is PrivacyReviewStatusV1.FAILED:
            if self.failure_code is None:
                raise ValueError("failed privacy review requires a safe failure code")
            if self.findings:
                raise ValueError("failed privacy review cannot claim validated findings")
        else:
            if self.failure_code is not None:
                raise ValueError("complete privacy review cannot carry a failure code")
            # A complete review with no producer behind it would assert
            # "reviewed and clean" on content nothing actually read.
            if not self.proposal_sources:
                raise ValueError("complete privacy review requires at least one proposal source")
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("privacy finding IDs must be unique")
        return self


class RouteReadinessMatrixV1(ContractModel):
    asset_id: UUID
    version_id: UUID
    content_hash: Sha256
    relation_projection_hash: Sha256
    policy_version: NonEmptyText
    decisions: list[RouteDecision]

    @model_validator(mode="after")
    def contains_each_route_once(self) -> RouteReadinessMatrixV1:
        routes = [decision.route for decision in self.decisions]
        if len(routes) != len(set(routes)) or set(routes) != set(RouteType):
            raise ValueError("M5 matrix must contain each route exactly once")
        if any(decision.canonical_version_id != self.version_id for decision in self.decisions):
            raise ValueError("M5 route decisions must bind the matrix version")
        return self


class PrivacyResolutionResultV1(ContractModel):
    action: PrivacyActionV1
    finding_id: UUID
    requires_canonical_change: bool
    review: PrivacyReviewV1

    @model_validator(mode="after")
    def action_matches_effect(self) -> PrivacyResolutionResultV1:
        content_change = self.action in {
            PrivacyActionV1.GENERALIZE,
            PrivacyActionV1.REMOVE,
        }
        if content_change != self.requires_canonical_change:
            raise ValueError("privacy action and canonical-change requirement disagree")
        return self


class ApprovalRequestV1(ContractModel):
    expected_asset_id: UUID
    expected_version_id: UUID
    expected_content_hash: Sha256
    route: RouteType
    language: Literal["zh-CN", "en"]
    expected_route_draft_hash: Sha256
    expected_privacy_review_hash: Sha256
    user_action: Literal["APPROVE_SHAREABLE_EXPORT"]
    idempotency_key: NonEmptyText


class ApprovalValidityV1(ContractModel):
    valid: bool
    reason_codes: list[str] = Field(default_factory=list)
    approval: ApprovalRecord | None = None

    @model_validator(mode="after")
    def invalid_result_has_reason(self) -> ApprovalValidityV1:
        if self.valid and self.reason_codes:
            raise ValueError("valid approval cannot carry stale reasons")
        if not self.valid and not self.reason_codes:
            raise ValueError("invalid approval requires a reason")
        return self


class StoredDraftBindingV1(ContractModel):
    """E7-owned draft identity consumed by the isolated E6 approval policy."""

    draft: RouteDraft
    renderer_input_hash: Sha256
    verified: Literal[True] = True


class FindingPolicyV1(ContractModel):
    category: PrivacyCategoryV1
    severity: FindingSeverity
    allowed_actions: list[PrivacyActionV1]
    resolution: PrivacyResolution = PrivacyResolution.OPEN
