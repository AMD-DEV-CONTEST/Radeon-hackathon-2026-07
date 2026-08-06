"""Deterministic E6/M5 route, privacy, and approval policy.

The local model may propose privacy findings, but every accepted reference,
action, route state, and approval is derived here. This module is deliberately
free of persistence, HTTP, and LangGraph wiring so it can run against the
PR #28 contract-equivalent E5 handoff mock.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import NoReturn
from uuid import NAMESPACE_URL, UUID, uuid5

from app.experience_asset.application.m5.contracts import (
    M5_ROUTE_POLICY_IDENTITY,
    ApprovalRequestV1,
    ApprovalValidityV1,
    M5ContextProjectionV1,
    PrivacyActionV1,
    PrivacyCategoryV1,
    PrivacyFindingProposalV1,
    PrivacyProposalSourceV1,
    PrivacyResolutionResultV1,
    PrivacyReviewStatusV1,
    PrivacyReviewV1,
    RouteReadinessMatrixV1,
    StoredDraftBindingV1,
)
from app.experience_asset.domain.enums import (
    ApprovalScope,
    ConfirmationState,
    EvidenceStrength,
    FindingSeverity,
    PrivacyResolution,
    RouteEligibility,
    RouteType,
    StatementStatus,
)
from app.experience_asset.domain.models import ApprovalRecord, PrivacyFinding, RouteDecision
from app.experience_asset.policy.privacy_text_detector import (
    PRIVACY_TEXT_DETECTOR_VERSION,
    detect_text_privacy_proposals,
)

ROUTE_POLICY_VERSION = M5_ROUTE_POLICY_IDENTITY
PRIVACY_POLICY_VERSION = "m5-privacy-policy-v1"
APPROVAL_POLICY_VERSION = "m5-approval-policy-v1"


class M5PolicyError(ValueError):
    """Fail-closed policy denial with one stable public reason code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _deny(code: str, message: str) -> NoReturn:
    raise M5PolicyError(code, message)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique(values: Iterable[UUID]) -> list[UUID]:
    return sorted(set(values), key=str)


def _blocked_decision(
    context: M5ContextProjectionV1,
    route: RouteType,
    *,
    reason_codes: list[str],
    explanation: str,
    supporting: Iterable[UUID] = (),
    missing: Iterable[UUID] = (),
) -> RouteDecision:
    return RouteDecision(
        route=route,
        eligibility=RouteEligibility.BLOCKED,
        reason_codes=reason_codes,
        explanation=explanation,
        supporting_statement_ids=_unique(supporting),
        missing_statement_ids=_unique(missing),
        canonical_version_id=context.version_id,
        policy_version=ROUTE_POLICY_VERSION,
        model_run_id=context.model_run_id,
    )


def _ready_decision(
    context: M5ContextProjectionV1,
    route: RouteType,
    *,
    supporting: Iterable[UUID],
    privacy_review: PrivacyReviewV1 | None,
) -> RouteDecision:
    external = route is not RouteType.PRIVATE_SELF
    eligibility = RouteEligibility.ELIGIBLE
    reasons = ["READY"]
    explanation = "The current evidence satisfies this route contract."
    if external and privacy_review is not None:
        if privacy_review.status is PrivacyReviewStatusV1.FAILED:
            return _blocked_decision(
                context,
                route,
                reason_codes=["PRIVACY_REVIEW_FAILED"],
                explanation="Privacy review failed and external approval remains blocked.",
                supporting=supporting,
            )
        if any(
            finding.resolution is PrivacyResolution.OPEN
            for finding in privacy_review.findings
        ):
            eligibility = RouteEligibility.ELIGIBLE_AFTER_PRIVACY_APPROVAL
            reasons = ["OPEN_PRIVACY_FINDINGS"]
            explanation = (
                "Content support is sufficient, but external sharing requires "
                "the open privacy findings to be resolved."
            )
    return RouteDecision(
        route=route,
        eligibility=eligibility,
        reason_codes=reasons,
        explanation=explanation,
        supporting_statement_ids=_unique(supporting),
        missing_statement_ids=[],
        canonical_version_id=context.version_id,
        policy_version=ROUTE_POLICY_VERSION,
        model_run_id=context.model_run_id,
    )


def _external_claim_guard(
    context: M5ContextProjectionV1,
    route: RouteType,
    *,
    supporting: Iterable[UUID],
) -> RouteDecision | None:
    evidence = context.evidence
    if route is RouteType.PRIVATE_SELF:
        return None
    if evidence.unsupported_professional_claim:
        return _blocked_decision(
            context,
            route,
            reason_codes=["UNSUPPORTED_PROFESSIONAL_CLAIM"],
            explanation="Unsupported professional authority or advice cannot enter this route.",
            supporting=supporting,
            missing=evidence.unsupported_professional_claim,
        )
    if evidence.unsupported_universal_claim:
        return _blocked_decision(
            context,
            route,
            reason_codes=["UNSUPPORTED_UNIVERSAL_CLAIM"],
            explanation="One personal experience cannot be presented as a universal conclusion.",
            supporting=supporting,
            missing=evidence.unsupported_universal_claim,
        )
    return None


def _usable_role_evidence_ids(
    context: M5ContextProjectionV1,
    statement_ids: Iterable[UUID],
    *,
    require_verifiable_result: bool = False,
) -> list[UUID]:
    """Keep only evidence strong enough for peer/result route claims.

    Confirmed historical IDs have already crossed E5's explicit relation gate.
    Current source facts need non-NONE evidence. Peer evidence may also use an
    explicitly confirmed judgment or inference. A verifiable result is stricter:
    it accepts a directly/indirectly grounded source fact or confirmed inference,
    but never a self-reported judgment by itself.
    """

    current_by_id = {
        statement.statement_id: statement for statement in context.statements
    }
    authorized_history = set(context.relation.authorized_historical_statement_ids)
    usable: list[UUID] = []
    for statement_id in statement_ids:
        if statement_id in authorized_history:
            usable.append(statement_id)
            continue
        statement = current_by_id.get(statement_id)
        if statement is None or statement.evidence_strength is EvidenceStrength.NONE:
            continue
        if require_verifiable_result:
            verifiable_strength = statement.evidence_strength in {
                EvidenceStrength.DIRECT,
                EvidenceStrength.INDIRECT,
            }
            qualifies = verifiable_strength and (
                statement.status is StatementStatus.SOURCE_FACT
                or (
                    statement.status is StatementStatus.AGENT_INFERENCE
                    and statement.confirmation is ConfirmationState.CONFIRMED
                    and bool(statement.derived_from)
                )
            )
        else:
            qualifies = statement.status is StatementStatus.SOURCE_FACT or (
                statement.status
                in {StatementStatus.USER_JUDGMENT, StatementStatus.AGENT_INFERENCE}
                and statement.confirmation is ConfirmationState.CONFIRMED
            )
        if qualifies:
            usable.append(statement_id)
    return usable


def _evaluate_one_route(
    context: M5ContextProjectionV1,
    route: RouteType,
    privacy_review: PrivacyReviewV1 | None,
) -> RouteDecision:
    evidence = context.evidence
    unresolved = evidence.unresolved_statement_ids
    missing_statement_ids = list(unresolved)

    if route is RouteType.PRIVATE_SELF:
        support = evidence.decision_context + evidence.personal_lesson
        missing_codes: list[str] = []
        if not evidence.decision_context or not evidence.personal_lesson:
            missing_codes.append("MISSING_DECISION_OR_LESSON")
        if missing_codes:
            return _blocked_decision(
                context,
                route,
                reason_codes=missing_codes,
                explanation="Private review still needs a decision context and a personal lesson.",
                supporting=support,
                missing=unresolved,
            )
        return _ready_decision(
            context,
            route,
            supporting=support,
            privacy_review=privacy_review,
        )

    if route is RouteType.BEGINNER:
        support = (
            evidence.beginner_prerequisite
            + evidence.beginner_guidance_basis
            + evidence.common_mistake_or_risk
            + evidence.applicability_boundary
        )
        missing_codes = []
        if not evidence.beginner_prerequisite:
            missing_codes.append("MISSING_BEGINNER_PREREQUISITE")
        if not evidence.beginner_guidance_basis or not evidence.common_mistake_or_risk:
            missing_codes.append("MISSING_BEGINNER_GUIDANCE_BASIS")
        if not evidence.applicability_boundary:
            missing_codes.append("MISSING_APPLICABILITY_BOUNDARY")
    elif route is RouteType.PEER:
        usable_peer_evidence = _usable_role_evidence_ids(
            context,
            evidence.peer_evidence,
        )
        support = (
            evidence.peer_comparison
            + usable_peer_evidence
            + evidence.tradeoff_or_constraint
            + evidence.applicability_boundary
        )
        missing_codes = []
        if not evidence.peer_comparison or not evidence.tradeoff_or_constraint:
            missing_codes.append("MISSING_PEER_COMPARISON")
        if not usable_peer_evidence:
            missing_codes.append("MISSING_PEER_EVIDENCE")
            missing_statement_ids.extend(evidence.peer_evidence)
        if not evidence.applicability_boundary:
            missing_codes.append("MISSING_APPLICABILITY_BOUNDARY")
    elif route is RouteType.CUSTOMER_EVALUATOR:
        usable_verifiable_results = _usable_role_evidence_ids(
            context,
            evidence.verifiable_result,
            require_verifiable_result=True,
        )
        support = (
            evidence.qualifying_context
            + usable_verifiable_results
            + evidence.decision_context
            + evidence.applicability_boundary
        )
        if not evidence.qualifying_context:
            return RouteDecision(
                route=route,
                eligibility=RouteEligibility.INELIGIBLE,
                reason_codes=["MISSING_QUALIFYING_CONTEXT"],
                explanation=(
                    "No qualifying professional, project, client, or evaluator context exists."
                ),
                supporting_statement_ids=_unique(support),
                missing_statement_ids=_unique(unresolved),
                canonical_version_id=context.version_id,
                policy_version=ROUTE_POLICY_VERSION,
                model_run_id=context.model_run_id,
            )
        missing_codes = []
        if not usable_verifiable_results:
            missing_codes.append("MISSING_VERIFIABLE_RESULT")
            missing_statement_ids.extend(evidence.verifiable_result)
        if not evidence.applicability_boundary:
            missing_codes.append("MISSING_APPLICABILITY_BOUNDARY")
    else:
        support = (
            evidence.event_arc
            + evidence.transferable_lesson
            + evidence.applicability_boundary
            + evidence.disclosure_basis
        )
        missing_codes = []
        if not evidence.event_arc or not evidence.transferable_lesson:
            missing_codes.append("MISSING_DECISION_OR_LESSON")
        if not evidence.applicability_boundary:
            missing_codes.append("MISSING_APPLICABILITY_BOUNDARY")
        if not evidence.disclosure_basis:
            missing_codes.append("MISSING_DISCLOSURE_BASIS")

    claim_block = _external_claim_guard(context, route, supporting=support)
    if claim_block is not None:
        return claim_block
    if missing_codes:
        return _blocked_decision(
            context,
            route,
            reason_codes=missing_codes,
            explanation="The current evidence does not yet satisfy this route contract.",
            supporting=support,
            missing=missing_statement_ids,
        )
    return _ready_decision(
        context,
        route,
        supporting=support,
        privacy_review=privacy_review,
    )


def route_matrix_hash(matrix: RouteReadinessMatrixV1) -> str:
    """Identify one matrix by its content, using the module's one hash function.

    The matrix contract carries no hash field because the policy layer never
    needed to compare two matrices. Persistence and the approval trail do, and a
    second hash implementation next to the store would drift from this one the
    first time a decision field is added.
    """

    return _canonical_hash(
        {
            "asset_id": str(matrix.asset_id),
            "version_id": str(matrix.version_id),
            "content_hash": matrix.content_hash,
            "relation_projection_hash": matrix.relation_projection_hash,
            "policy_version": matrix.policy_version,
            "decisions": [
                {
                    "route": decision.route.value,
                    "eligibility": decision.eligibility.value,
                    "reason_codes": list(decision.reason_codes),
                    "supporting_statement_ids": sorted(
                        str(value) for value in decision.supporting_statement_ids
                    ),
                    "missing_statement_ids": sorted(
                        str(value) for value in decision.missing_statement_ids
                    ),
                }
                for decision in sorted(
                    matrix.decisions, key=lambda item: item.route.value
                )
            ],
        }
    )


def evaluate_route_matrix(
    context: M5ContextProjectionV1,
    *,
    privacy_review: PrivacyReviewV1 | None = None,
) -> RouteReadinessMatrixV1:
    """Return exactly five deterministic route decisions for one exact input."""

    stale_reason = context.stale_reason()
    if privacy_review is not None and (
        privacy_review.asset_id != context.asset_id
        or privacy_review.version_id != context.version_id
        or privacy_review.content_hash != context.content_hash
    ):
        stale_reason = "M5_INPUT_STALE"

    if stale_reason is not None:
        explanation = (
            "The exact M4 Knowledge Card is not ready."
            if stale_reason == "M5_INPUT_NOT_READY"
            else "The M5 input binding is stale and must be recomposed."
        )
        decisions = [
            _blocked_decision(
                context,
                route,
                reason_codes=[stale_reason],
                explanation=explanation,
            )
            for route in RouteType
        ]
    else:
        decisions = [
            _evaluate_one_route(context, route, privacy_review)
            for route in RouteType
        ]
    return RouteReadinessMatrixV1(
        asset_id=context.asset_id,
        version_id=context.version_id,
        content_hash=context.content_hash,
        relation_projection_hash=context.relation.projection_hash,
        policy_version=ROUTE_POLICY_VERSION,
        decisions=decisions,
    )


_CONTENT_CHANGE_ONLY_CATEGORIES = {
    PrivacyCategoryV1.IDENTITY,
    PrivacyCategoryV1.PURCHASE_PAYMENT,
    PrivacyCategoryV1.SCREENSHOT_METADATA,
    PrivacyCategoryV1.PROFESSIONAL_ADVICE,
}

_TAGGED_CATEGORY_SEVERITY = {
    PrivacyCategoryV1.IDENTITY: FindingSeverity.HIGH,
    PrivacyCategoryV1.HEALTH_BODY: FindingSeverity.MEDIUM,
    PrivacyCategoryV1.LOCATION: FindingSeverity.HIGH,
    PrivacyCategoryV1.PURCHASE_PAYMENT: FindingSeverity.HIGH,
    PrivacyCategoryV1.THIRD_PARTY: FindingSeverity.MEDIUM,
    PrivacyCategoryV1.SCREENSHOT_METADATA: FindingSeverity.HIGH,
    PrivacyCategoryV1.COPYRIGHT: FindingSeverity.MEDIUM,
    PrivacyCategoryV1.UNVERIFIED_BRAND_CLAIM: FindingSeverity.MEDIUM,
    PrivacyCategoryV1.PROFESSIONAL_ADVICE: FindingSeverity.HIGH,
}

_SEVERITY_RANK = {
    FindingSeverity.LOW: 0,
    FindingSeverity.MEDIUM: 1,
    FindingSeverity.HIGH: 2,
    FindingSeverity.CRITICAL: 3,
}


def _effective_severity(
    category: PrivacyCategoryV1,
    proposed: FindingSeverity,
) -> FindingSeverity:
    """Apply the deterministic category floor to an untrusted proposal."""

    floor = _TAGGED_CATEGORY_SEVERITY[category]
    return proposed if _SEVERITY_RANK[proposed] >= _SEVERITY_RANK[floor] else floor


def _privacy_finding_fingerprint(
    context: M5ContextProjectionV1,
    *,
    category: PrivacyCategoryV1,
    affected_statement_ids: Iterable[UUID],
    affected_source_ids: Iterable[UUID],
) -> str:
    return _canonical_hash(
        {
            "asset_id": str(context.asset_id),
            "version_id": str(context.version_id),
            "category": category.value,
            "affected_statement_ids": sorted(
                str(value) for value in affected_statement_ids
            ),
            "affected_source_ids": sorted(str(value) for value in affected_source_ids),
        }
    )


def allowed_privacy_actions(
    category: PrivacyCategoryV1,
    severity: FindingSeverity,
) -> tuple[PrivacyActionV1, ...]:
    """Return conservative user actions; severe risks cannot be acknowledged away."""

    content_change = (PrivacyActionV1.GENERALIZE, PrivacyActionV1.REMOVE)
    if category in _CONTENT_CHANGE_ONLY_CATEGORIES:
        return content_change
    if severity in {FindingSeverity.HIGH, FindingSeverity.CRITICAL}:
        return content_change
    return (
        PrivacyActionV1.KEEP,
        PrivacyActionV1.ACKNOWLEDGE,
        *content_change,
    )


def detect_tagged_privacy_proposals(
    context: M5ContextProjectionV1,
) -> list[PrivacyFindingProposalV1]:
    """Convert canonical sensitivity tags into bounded deterministic proposals."""

    proposals: list[PrivacyFindingProposalV1] = []
    for statement in context.statements:
        if statement.status is StatementStatus.UNRESOLVED or statement.confirmation in {
            ConfirmationState.CORRECTED,
            ConfirmationState.REJECTED,
        }:
            continue
        for raw_tag in sorted(set(statement.sensitivity_tags)):
            try:
                category = PrivacyCategoryV1(raw_tag.upper())
            except ValueError:
                _deny(
                    "UNKNOWN_SENSITIVITY_TAG",
                    f"unknown canonical sensitivity tag: {raw_tag}",
                )
            proposals.append(
                PrivacyFindingProposalV1(
                    category=category,
                    affected_statement_ids=[statement.statement_id],
                    severity=_TAGGED_CATEGORY_SEVERITY[category],
                    explanation=(
                        f"Canonical sensitivity tag {category.value} requires explicit review."
                    ),
                )
            )
    return proposals


def _privacy_review_payload(
    context: M5ContextProjectionV1,
    *,
    status: PrivacyReviewStatusV1,
    findings: Sequence[PrivacyFinding],
    failure_code: str | None,
    proposal_sources: Sequence[PrivacyProposalSourceV1] = (),
    detector_version: str | None = None,
) -> dict[str, object]:
    return {
        "asset_id": str(context.asset_id),
        "version_id": str(context.version_id),
        "content_hash": context.content_hash,
        "policy_version": PRIVACY_POLICY_VERSION,
        "status": status.value,
        "failure_code": failure_code,
        # Bound into the hash: changing which producers ran, or changing the
        # detector's rule set, must stale any approval built on the old review.
        "proposal_sources": sorted(source.value for source in proposal_sources),
        "detector_version": detector_version,
        "findings": [
            {
                "finding_id": str(finding.finding_id),
                "category": finding.category,
                "severity": finding.severity.value,
                "affected_statement_ids": sorted(
                    str(value) for value in finding.affected_statement_ids
                ),
                "affected_source_ids": sorted(
                    str(value) for value in finding.affected_source_ids
                ),
                "resolution": finding.resolution.value,
                "created_by_run_id": str(finding.created_by_run_id),
                "resolved_by_run_id": (
                    str(finding.resolved_by_run_id)
                    if finding.resolved_by_run_id is not None
                    else None
                ),
            }
            for finding in sorted(findings, key=lambda item: str(item.finding_id))
        ],
    }


def _make_privacy_review(
    context: M5ContextProjectionV1,
    *,
    status: PrivacyReviewStatusV1,
    findings: Sequence[PrivacyFinding],
    failure_code: str | None = None,
    proposal_sources: Sequence[PrivacyProposalSourceV1] = (),
    detector_version: str | None = None,
) -> PrivacyReviewV1:
    payload = _privacy_review_payload(
        context,
        status=status,
        findings=findings,
        failure_code=failure_code,
        proposal_sources=proposal_sources,
        detector_version=detector_version,
    )
    return PrivacyReviewV1(
        asset_id=context.asset_id,
        version_id=context.version_id,
        content_hash=context.content_hash,
        policy_version=PRIVACY_POLICY_VERSION,
        status=status,
        findings=list(findings),
        review_hash=_canonical_hash(payload),
        failure_code=failure_code,
        proposal_sources=sorted(set(proposal_sources), key=lambda item: item.value),
        detector_version=detector_version,
    )


def _privacy_review_hash_matches(
    context: M5ContextProjectionV1,
    review: PrivacyReviewV1,
) -> bool:
    expected = _canonical_hash(
        _privacy_review_payload(
            context,
            status=review.status,
            findings=review.findings,
            failure_code=review.failure_code,
            proposal_sources=review.proposal_sources,
            detector_version=review.detector_version,
        )
    )
    return review.review_hash == expected


def _privacy_review_policy_matches(
    context: M5ContextProjectionV1,
    review: PrivacyReviewV1,
) -> bool:
    """Revalidate finding completeness and resolutions, not only hash syntax."""

    allowed_statement_ids = {
        statement.statement_id for statement in context.statements
    } | set(context.relation.authorized_historical_statement_ids)
    allowed_source_ids = {source.source_id for source in context.sources}
    findings_by_fingerprint: dict[str, PrivacyFinding] = {}
    for finding in review.findings:
        try:
            category = PrivacyCategoryV1(finding.category)
        except ValueError:
            return False
        if not set(finding.affected_statement_ids).issubset(allowed_statement_ids):
            return False
        if not set(finding.affected_source_ids).issubset(allowed_source_ids):
            return False
        if _SEVERITY_RANK[finding.severity] < _SEVERITY_RANK[
            _TAGGED_CATEGORY_SEVERITY[category]
        ]:
            return False
        fingerprint = _privacy_finding_fingerprint(
            context,
            category=category,
            affected_statement_ids=finding.affected_statement_ids,
            affected_source_ids=finding.affected_source_ids,
        )
        if fingerprint in findings_by_fingerprint or finding.finding_id != uuid5(
            NAMESPACE_URL,
            f"m5-privacy:{fingerprint}",
        ):
            return False
        findings_by_fingerprint[fingerprint] = finding
        allowed_actions = allowed_privacy_actions(category, finding.severity)
        if finding.proposed_actions != [action.value for action in allowed_actions]:
            return False
        allowed_resolutions = {PrivacyResolution.OPEN}
        if PrivacyActionV1.KEEP in allowed_actions:
            allowed_resolutions.add(PrivacyResolution.KEEP)
        if PrivacyActionV1.ACKNOWLEDGE in allowed_actions:
            allowed_resolutions.add(PrivacyResolution.ACKNOWLEDGED)
        if finding.resolution not in allowed_resolutions:
            return False

    for proposal in detect_tagged_privacy_proposals(context):
        fingerprint = _privacy_finding_fingerprint(
            context,
            category=proposal.category,
            affected_statement_ids=proposal.affected_statement_ids,
            affected_source_ids=proposal.affected_source_ids,
        )
        if fingerprint not in findings_by_fingerprint:
            return False
    return True


def build_privacy_review(
    context: M5ContextProjectionV1,
    *,
    proposals: Sequence[PrivacyFindingProposalV1],
    run_id: UUID,
    run_text_detector: bool = True,
) -> PrivacyReviewV1:
    """Validate untrusted finding proposals and build a bound review.

    Proposals are untrusted whatever produced them: canonical sensitivity tags,
    the deterministic text detector, or the user. Runtime resolves every
    reference and applies the per-category severity floor before any of it
    becomes a finding.
    """

    if context.stale_reason() is not None:
        _deny("M5_INPUT_STALE", "privacy review requires a current ready M5 input")
    tagged_proposals = detect_tagged_privacy_proposals(context)
    text_proposals = (
        detect_text_privacy_proposals(context.statements) if run_text_detector else []
    )
    sources: list[PrivacyProposalSourceV1] = []
    if run_text_detector:
        sources.append(PrivacyProposalSourceV1.DETERMINISTIC_TEXT_DETECTOR)
    if any(statement.sensitivity_tags for statement in context.statements):
        sources.append(PrivacyProposalSourceV1.CANONICAL_SENSITIVITY_TAGS)
    if proposals:
        sources.append(PrivacyProposalSourceV1.USER_PROVIDED)
    # Fail closed rather than return a clean-looking review: with no producer
    # behind it, an empty finding list states "nothing was found" when the
    # truth is "nothing looked". A FAILED review blocks every external route
    # with PRIVACY_REVIEW_FAILED and leaves private/self available.
    if not sources:
        return failed_privacy_review(context, failure_code="NO_PRIVACY_PROPOSAL_SOURCE")
    current_statement_ids = {statement.statement_id for statement in context.statements}
    allowed_statement_ids = current_statement_ids | set(
        context.relation.authorized_historical_statement_ids
    )
    source_ids = {source.source_id for source in context.sources}
    findings: list[PrivacyFinding] = []
    finding_index_by_fingerprint: dict[str, int] = {}
    merged_proposals = [*tagged_proposals, *text_proposals, *proposals]
    for proposal in merged_proposals:
        if not set(proposal.affected_statement_ids).issubset(allowed_statement_ids):
            _deny("UNKNOWN_PRIVACY_REFERENCE", "privacy proposal referenced unknown content")
        if not set(proposal.affected_source_ids).issubset(source_ids):
            _deny("UNKNOWN_PRIVACY_REFERENCE", "privacy proposal referenced unknown source")
        severity = _effective_severity(proposal.category, proposal.severity)
        fingerprint = _privacy_finding_fingerprint(
            context,
            category=proposal.category,
            affected_statement_ids=proposal.affected_statement_ids,
            affected_source_ids=proposal.affected_source_ids,
        )
        if fingerprint in finding_index_by_fingerprint:
            existing_index = finding_index_by_fingerprint[fingerprint]
            existing = findings[existing_index]
            if _SEVERITY_RANK[severity] > _SEVERITY_RANK[existing.severity]:
                findings[existing_index] = existing.model_copy(
                    update={
                        "severity": severity,
                        "proposed_actions": [
                            action.value
                            for action in allowed_privacy_actions(
                                proposal.category,
                                severity,
                            )
                        ],
                    }
                )
            continue
        finding_index_by_fingerprint[fingerprint] = len(findings)
        actions = allowed_privacy_actions(proposal.category, severity)
        findings.append(
            PrivacyFinding(
                finding_id=uuid5(NAMESPACE_URL, f"m5-privacy:{fingerprint}"),
                category=proposal.category.value,
                affected_statement_ids=proposal.affected_statement_ids,
                affected_source_ids=proposal.affected_source_ids,
                severity=severity,
                explanation=proposal.explanation,
                proposed_actions=[action.value for action in actions],
                resolution=PrivacyResolution.OPEN,
                created_by_run_id=run_id,
            )
        )
    return _make_privacy_review(
        context,
        status=PrivacyReviewStatusV1.COMPLETE,
        findings=findings,
        proposal_sources=sources,
        detector_version=(
            PRIVACY_TEXT_DETECTOR_VERSION if run_text_detector else None
        ),
    )


def failed_privacy_review(
    context: M5ContextProjectionV1,
    *,
    failure_code: str,
) -> PrivacyReviewV1:
    return _make_privacy_review(
        context,
        status=PrivacyReviewStatusV1.FAILED,
        findings=[],
        failure_code=failure_code,
    )


_ACTION_TO_RESOLUTION = {
    PrivacyActionV1.KEEP: PrivacyResolution.KEEP,
    PrivacyActionV1.ACKNOWLEDGE: PrivacyResolution.ACKNOWLEDGED,
}


def resolve_privacy_finding(
    context: M5ContextProjectionV1,
    review: PrivacyReviewV1,
    *,
    finding_id: UUID,
    action: PrivacyActionV1,
    run_id: UUID,
) -> PrivacyResolutionResultV1:
    """Apply non-content resolution or request a canonical correction."""

    if context.stale_reason() is not None or (
        review.asset_id != context.asset_id
        or review.version_id != context.version_id
        or review.content_hash != context.content_hash
        or review.status is not PrivacyReviewStatusV1.COMPLETE
    ):
        _deny("PRIVACY_REVIEW_STALE", "privacy review no longer matches current content")
    if not _privacy_review_hash_matches(context, review):
        _deny("PRIVACY_REVIEW_HASH_MISMATCH", "privacy review hash is not canonical")
    if not _privacy_review_policy_matches(context, review):
        _deny("PRIVACY_REVIEW_POLICY_MISMATCH", "privacy review violates policy")
    finding = next((item for item in review.findings if item.finding_id == finding_id), None)
    if finding is None:
        _deny("UNKNOWN_PRIVACY_FINDING", "privacy finding does not exist")
    category = PrivacyCategoryV1(finding.category)
    allowed = allowed_privacy_actions(category, finding.severity)
    if action not in allowed or action.value not in finding.proposed_actions:
        _deny("PRIVACY_ACTION_DENIED", "the selected resolution is not allowed")

    if action in {PrivacyActionV1.GENERALIZE, PrivacyActionV1.REMOVE}:
        return PrivacyResolutionResultV1(
            action=action,
            finding_id=finding_id,
            requires_canonical_change=True,
            review=review,
        )

    updated = finding.model_copy(
        update={
            "resolution": _ACTION_TO_RESOLUTION[action],
            "resolved_by_run_id": run_id,
        }
    )
    findings = [updated if item.finding_id == finding_id else item for item in review.findings]
    next_review = _make_privacy_review(
        context,
        status=PrivacyReviewStatusV1.COMPLETE,
        findings=findings,
        # Resolving a finding changes the resolution, not who proposed it.
        # Dropping the producers here would silently downgrade the successor
        # review's provenance and break its hash lineage.
        proposal_sources=review.proposal_sources,
        detector_version=review.detector_version,
    )
    return PrivacyResolutionResultV1(
        action=action,
        finding_id=finding_id,
        requires_canonical_change=False,
        review=next_review,
    )


def _draft_binding_hash(
    binding: StoredDraftBindingV1,
    *,
    asset_content_hash: str,
    relation_projection_hash: str,
    route_decision: RouteDecision,
) -> str:
    return _canonical_hash(
        {
            "approval_policy_version": APPROVAL_POLICY_VERSION,
            "route_draft_id": str(binding.draft.route_draft_id),
            "asset_version_id": str(binding.draft.canonical_version_id),
            "asset_content_hash": asset_content_hash,
            "relation_projection_hash": relation_projection_hash,
            "route": binding.draft.route.value,
            "language": binding.draft.language,
            "draft_content_hash": binding.draft.content_hash,
            "renderer_input_hash": binding.renderer_input_hash,
            "statement_ids": sorted(str(value) for value in binding.draft.statement_ids),
            "route_decision": route_decision.model_dump(mode="json"),
        }
    )


def route_draft_binding_hash(
    draft: object,
    *,
    asset_content_hash: str,
    relation_projection_hash: str,
    route_decision: RouteDecision,
    renderer_input_hash: str,
) -> str:
    """Return the exact approval hash for an E7-owned verified RouteDraft."""

    from app.experience_asset.domain.models import RouteDraft

    validated_draft = RouteDraft.model_validate(draft)
    return _draft_binding_hash(
        StoredDraftBindingV1(
            draft=validated_draft,
            renderer_input_hash=renderer_input_hash,
        ),
        asset_content_hash=asset_content_hash,
        relation_projection_hash=relation_projection_hash,
        route_decision=route_decision,
    )


def _find_route(
    matrix: RouteReadinessMatrixV1,
    route: RouteType,
) -> RouteDecision:
    return next(decision for decision in matrix.decisions if decision.route is route)


def _approval_precondition_reasons(
    context: M5ContextProjectionV1,
    matrix: RouteReadinessMatrixV1,
    review: PrivacyReviewV1,
    binding: StoredDraftBindingV1,
) -> list[str]:
    reasons: list[str] = []
    if context.stale_reason() is not None:
        reasons.append("M5_INPUT_STALE")
    if (
        matrix.asset_id != context.asset_id
        or matrix.version_id != context.version_id
        or matrix.content_hash != context.content_hash
        or matrix.relation_projection_hash != context.relation.projection_hash
    ):
        reasons.append("ROUTE_MATRIX_STALE")
    if matrix.policy_version != ROUTE_POLICY_VERSION or any(
        decision.policy_version != ROUTE_POLICY_VERSION for decision in matrix.decisions
    ):
        reasons.append("ROUTE_POLICY_STALE")
    if (
        review.asset_id != context.asset_id
        or review.version_id != context.version_id
        or review.content_hash != context.content_hash
        or review.status is not PrivacyReviewStatusV1.COMPLETE
    ):
        reasons.append("PRIVACY_REVIEW_FAILED")
    if review.policy_version != PRIVACY_POLICY_VERSION:
        reasons.append("PRIVACY_POLICY_STALE")
    if not _privacy_review_hash_matches(context, review):
        reasons.append("PRIVACY_REVIEW_HASH_MISMATCH")
    if not _privacy_review_policy_matches(context, review):
        reasons.append("PRIVACY_REVIEW_POLICY_MISMATCH")
    expected_matrix = evaluate_route_matrix(context, privacy_review=review)
    if binding.draft.canonical_version_id != context.version_id:
        reasons.append("ROUTE_DRAFT_STALE")
    allowed_statement_ids = {
        statement.statement_id for statement in context.statements
    } | set(context.relation.authorized_historical_statement_ids)
    if not set(binding.draft.statement_ids).issubset(allowed_statement_ids):
        reasons.append("UNAUTHORIZED_DRAFT_REFERENCE")
    decision = _find_route(matrix, binding.draft.route)
    if binding.draft.route is RouteType.PRIVATE_SELF:
        reasons.append("PRIVATE_ROUTE_NOT_SHAREABLE")
    has_open_findings = any(
        finding.resolution is PrivacyResolution.OPEN for finding in review.findings
    )
    if has_open_findings:
        reasons.append("OPEN_PRIVACY_FINDINGS")
    if decision.eligibility is RouteEligibility.ELIGIBLE_AFTER_PRIVACY_APPROVAL:
        if not has_open_findings:
            reasons.append("ROUTE_REEVALUATION_REQUIRED")
    elif decision.eligibility is not RouteEligibility.ELIGIBLE:
        reasons.append("ROUTE_NOT_ELIGIBLE")
    if matrix.model_dump(mode="json") != expected_matrix.model_dump(mode="json"):
        reasons.append("ROUTE_MATRIX_POLICY_MISMATCH")
    return list(dict.fromkeys(reasons))


def approve_shareable_draft(
    context: M5ContextProjectionV1,
    matrix: RouteReadinessMatrixV1,
    review: PrivacyReviewV1,
    *,
    draft_binding: StoredDraftBindingV1,
    request: ApprovalRequestV1,
    existing: Sequence[ApprovalRecord] = (),
) -> ApprovalRecord:
    """Create or reuse one exact-bound external-share approval."""

    reasons = _approval_precondition_reasons(context, matrix, review, draft_binding)
    trusted_matrix = evaluate_route_matrix(context, privacy_review=review)
    route_decision = _find_route(trusted_matrix, draft_binding.draft.route)
    binding_hash = _draft_binding_hash(
        draft_binding,
        asset_content_hash=context.content_hash,
        relation_projection_hash=context.relation.projection_hash,
        route_decision=route_decision,
    )
    if request.expected_asset_id != context.asset_id:
        reasons.append("ASSET_BINDING_MISMATCH")
    if (
        request.expected_version_id != context.version_id
        or request.expected_content_hash != context.content_hash
    ):
        reasons.append("VERSION_BINDING_MISMATCH")
    if request.route is not draft_binding.draft.route:
        reasons.append("ROUTE_BINDING_MISMATCH")
    if request.language != draft_binding.draft.language:
        reasons.append("LANGUAGE_BINDING_MISMATCH")
    if request.expected_route_draft_hash != binding_hash:
        reasons.append("ROUTE_DRAFT_HASH_MISMATCH")
    if request.expected_privacy_review_hash != review.review_hash:
        reasons.append("PRIVACY_REVIEW_HASH_MISMATCH")
    if reasons:
        _deny(reasons[0], "; ".join(dict.fromkeys(reasons)))

    approval_id = uuid5(
        NAMESPACE_URL,
        f"m5-approval:{context.asset_id}:{request.idempotency_key}",
    )
    candidate = ApprovalRecord(
        approval_id=approval_id,
        user_action=request.user_action,
        approved_at=datetime.now(UTC),
        asset_id=context.asset_id,
        version_id=context.version_id,
        route=request.route,
        language=request.language,
        route_draft_hash=binding_hash,
        privacy_review_hash=review.review_hash,
        finding_resolutions={
            str(finding.finding_id): finding.resolution for finding in review.findings
        },
    )
    prior = next((approval for approval in existing if approval.approval_id == approval_id), None)
    if prior is None:
        return candidate
    comparable = {
        "scope",
        "user_action",
        "asset_id",
        "version_id",
        "route",
        "language",
        "route_draft_hash",
        "privacy_review_hash",
        "finding_resolutions",
    }
    if any(getattr(prior, field) != getattr(candidate, field) for field in comparable):
        _deny("IDEMPOTENCY_CONFLICT", "idempotency key is bound to another approval")
    return prior


def evaluate_approval(
    approval: ApprovalRecord,
    context: M5ContextProjectionV1,
    matrix: RouteReadinessMatrixV1,
    review: PrivacyReviewV1,
    *,
    draft_binding: StoredDraftBindingV1,
) -> ApprovalValidityV1:
    reasons = _approval_precondition_reasons(context, matrix, review, draft_binding)
    trusted_matrix = evaluate_route_matrix(context, privacy_review=review)
    expected_finding_resolutions = {
        str(finding.finding_id): finding.resolution for finding in review.findings
    }
    comparisons = (
        (
            approval.scope is ApprovalScope.SHAREABLE_EXPORT,
            "APPROVAL_SCOPE_INVALID",
        ),
        (
            approval.user_action == "APPROVE_SHAREABLE_EXPORT",
            "APPROVAL_ACTION_INVALID",
        ),
        (approval.asset_id == context.asset_id, "ASSET_BINDING_MISMATCH"),
        (approval.version_id == context.version_id, "VERSION_BINDING_MISMATCH"),
        (approval.route is draft_binding.draft.route, "ROUTE_BINDING_MISMATCH"),
        (approval.language == draft_binding.draft.language, "LANGUAGE_BINDING_MISMATCH"),
        (
            approval.route_draft_hash
            == _draft_binding_hash(
                draft_binding,
                asset_content_hash=context.content_hash,
                relation_projection_hash=context.relation.projection_hash,
                route_decision=_find_route(trusted_matrix, draft_binding.draft.route),
            ),
            "ROUTE_DRAFT_STALE",
        ),
        (approval.privacy_review_hash == review.review_hash, "PRIVACY_REVIEW_STALE"),
        (
            approval.finding_resolutions == expected_finding_resolutions,
            "FINDING_RESOLUTION_STALE",
        ),
    )
    reasons.extend(reason for matches, reason in comparisons if not matches)
    reasons = list(dict.fromkeys(reasons))
    return ApprovalValidityV1(
        valid=not reasons,
        reason_codes=reasons,
        approval=approval,
    )


__all__ = [
    "APPROVAL_POLICY_VERSION",
    "PRIVACY_POLICY_VERSION",
    "ROUTE_POLICY_VERSION",
    "M5PolicyError",
    "allowed_privacy_actions",
    "approve_shareable_draft",
    "build_privacy_review",
    "detect_tagged_privacy_proposals",
    "evaluate_approval",
    "evaluate_route_matrix",
    "failed_privacy_review",
    "resolve_privacy_finding",
    "route_draft_binding_hash",
]
