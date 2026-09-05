"""Public E6/M5 policy tests against contract-equivalent E5 handoffs."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

import app.experience_asset.policy.m5 as m5_policy
from app.experience_asset.application.m5 import (
    ApprovalRequestV1,
    M5ContextProjectionV1,
    M5IsolatedService,
    M5RelationProjectionV1,
    PrivacyActionV1,
    PrivacyFindingProposalV1,
    RelationOutcomeV1,
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
from app.experience_asset.domain.models import RouteDecision, RouteDraft
from app.experience_asset.policy.m5 import M5PolicyError, route_draft_binding_hash
from tests.fixtures.m5 import (
    ASSET_ID,
    CONTENT_HASH,
    RENDERER_INPUT_HASH,
    RUN_ID,
    STATEMENT_IDS,
    VERSION_ID,
    complete_context,
    correction_context,
    privacy_risk_proposals,
)


def _by_route(matrix: object) -> dict[RouteType, object]:
    return {decision.route: decision for decision in matrix.decisions}


def _public_draft(*, statement_ids: list[UUID] | None = None) -> RouteDraft:
    return RouteDraft(
        route_draft_id=UUID(int=500),
        route=RouteType.PUBLIC,
        language="zh-CN",
        canonical_version_id=VERSION_ID,
        statement_ids=statement_ids or [STATEMENT_IDS["event"], STATEMENT_IDS["lesson"]],
        content_hash="6" * 64,
        created_by_run_id=RUN_ID,
    )


def _approval_request(
    draft: RouteDraft,
    review_hash: str,
    route_decision: RouteDecision,
) -> ApprovalRequestV1:
    return ApprovalRequestV1(
        expected_asset_id=ASSET_ID,
        expected_version_id=VERSION_ID,
        expected_content_hash=CONTENT_HASH,
        route=draft.route,
        language=draft.language,
        expected_route_draft_hash=route_draft_binding_hash(
            draft,
            asset_content_hash=CONTENT_HASH,
            relation_projection_hash="2" * 64,
            route_decision=route_decision,
            renderer_input_hash=RENDERER_INPUT_HASH,
        ),
        expected_privacy_review_hash=review_hash,
        user_action="APPROVE_SHAREABLE_EXPORT",
        idempotency_key="public-zh-v1",
    )


@pytest.mark.parametrize(
    "outcome",
    [RelationOutcomeV1.NO_MATCH, RelationOutcomeV1.DECLINED],
)
def test_complete_fixture_evaluates_five_routes_without_history(outcome: RelationOutcomeV1) -> None:
    service = M5IsolatedService()
    matrix = service.evaluate_routes(complete_context(relation_outcome=outcome))
    decisions = _by_route(matrix)

    assert len(decisions) == 5
    assert decisions[RouteType.PRIVATE_SELF].eligibility is RouteEligibility.ELIGIBLE
    assert decisions[RouteType.BEGINNER].eligibility is RouteEligibility.ELIGIBLE
    assert decisions[RouteType.PEER].eligibility is RouteEligibility.ELIGIBLE
    assert decisions[RouteType.PUBLIC].eligibility is RouteEligibility.ELIGIBLE
    assert (
        decisions[RouteType.CUSTOMER_EVALUATOR].eligibility
        is RouteEligibility.INELIGIBLE
    )
    assert decisions[RouteType.CUSTOMER_EVALUATOR].reason_codes == [
        "MISSING_QUALIFYING_CONTEXT"
    ]


def test_confirmed_relation_exposes_only_authorized_history_to_route_support() -> None:
    context = complete_context(
        relation_outcome=RelationOutcomeV1.CONFIRMED_RELATION,
    )
    historical_statement_id = context.relation.authorized_historical_statement_ids[0]
    payload = context.model_dump(mode="python")
    payload["evidence"]["peer_evidence"].append(historical_statement_id)
    context = M5ContextProjectionV1.model_validate(payload)

    peer = _by_route(M5IsolatedService().evaluate_routes(context))[RouteType.PEER]

    assert peer.eligibility is RouteEligibility.ELIGIBLE
    assert historical_statement_id in peer.supporting_statement_ids


def test_missing_readiness_blocks_every_route() -> None:
    matrix = M5IsolatedService().evaluate_routes(complete_context(readiness=False))
    assert all(
        decision.eligibility is RouteEligibility.BLOCKED
        and decision.reason_codes == ["M5_INPUT_NOT_READY"]
        for decision in matrix.decisions
    )


def test_stale_relation_projection_blocks_every_route() -> None:
    matrix = M5IsolatedService().evaluate_routes(
        complete_context(
            relation_outcome=RelationOutcomeV1.CONFIRMED_RELATION,
            relation_current=False,
        )
    )
    assert all(decision.reason_codes == ["M5_INPUT_STALE"] for decision in matrix.decisions)


def test_explicit_stale_relation_outcome_blocks_every_route() -> None:
    matrix = M5IsolatedService().evaluate_routes(
        complete_context(relation_outcome=RelationOutcomeV1.STALE)
    )
    assert all(
        decision.eligibility is RouteEligibility.BLOCKED
        and decision.reason_codes == ["M5_INPUT_STALE"]
        for decision in matrix.decisions
    )


def test_explicit_stale_relation_outcome_cannot_be_marked_current() -> None:
    with pytest.raises(ValidationError, match="STALE relation outcome"):
        complete_context(
            relation_outcome=RelationOutcomeV1.STALE,
            relation_current=True,
        )


def test_relation_projection_must_bind_the_exact_current_asset_version() -> None:
    context = complete_context()
    context = context.model_copy(
        update={
            "relation": context.relation.model_copy(
                update={"bound_version_id": UUID(int=9876)}
            )
        }
    )
    matrix = M5IsolatedService().evaluate_routes(context)
    assert all(decision.reason_codes == ["M5_INPUT_STALE"] for decision in matrix.decisions)


@pytest.mark.parametrize(
    ("field_name", "wrong_value"),
    [
        ("schema_identity", "experience-asset/2.0.0"),
        ("workflow_identity", "experience-asset/e6-m5-isolated/old"),
        ("policy_identity", "m5-route-policy-old"),
    ],
)
def test_contract_identity_drift_blocks_every_route(
    field_name: str,
    wrong_value: str,
) -> None:
    context = complete_context().model_copy(update={field_name: wrong_value})
    matrix = M5IsolatedService().evaluate_routes(context)
    assert all(decision.reason_codes == ["M5_INPUT_STALE"] for decision in matrix.decisions)


def test_only_confirmed_relation_may_expose_historical_detail() -> None:
    with pytest.raises(ValidationError, match="only CONFIRMED_RELATION"):
        M5RelationProjectionV1(
            bound_asset_id=ASSET_ID,
            bound_version_id=VERSION_ID,
            bound_content_hash=CONTENT_HASH,
            outcome=RelationOutcomeV1.NO_MATCH,
            projection_hash="2" * 64,
            authorized_historical_statement_ids=[UUID(int=999)],
        )


def test_missing_route_support_is_blocked_without_invented_ids() -> None:
    context = complete_context()
    context = context.model_copy(
        update={
            "evidence": context.evidence.model_copy(
                update={"beginner_prerequisite": [], "applicability_boundary": []}
            )
        }
    )
    decision = _by_route(M5IsolatedService().evaluate_routes(context))[RouteType.BEGINNER]
    assert decision.eligibility is RouteEligibility.BLOCKED
    assert decision.reason_codes == [
        "MISSING_BEGINNER_PREREQUISITE",
        "MISSING_APPLICABILITY_BOUNDARY",
    ]
    assert decision.missing_statement_ids == [STATEMENT_IDS["unresolved"]]


def test_weak_role_evidence_cannot_unlock_peer_or_customer_routes() -> None:
    payload = complete_context(include_qualifying_context=True).model_dump(mode="python")
    result = next(
        statement
        for statement in payload["statements"]
        if statement["statement_id"] == STATEMENT_IDS["result"]
    )
    result["evidence_strength"] = EvidenceStrength.NONE
    context = M5ContextProjectionV1.model_validate(payload)

    decisions = _by_route(M5IsolatedService().evaluate_routes(context))

    for route, reason in (
        (RouteType.PEER, "MISSING_PEER_EVIDENCE"),
        (RouteType.CUSTOMER_EVALUATOR, "MISSING_VERIFIABLE_RESULT"),
    ):
        assert decisions[route].eligibility is RouteEligibility.BLOCKED
        assert reason in decisions[route].reason_codes
        assert STATEMENT_IDS["result"] in decisions[route].missing_statement_ids
        assert STATEMENT_IDS["result"] not in decisions[route].supporting_statement_ids


def test_confirmed_supported_judgment_serves_peer_but_not_verifiable_result() -> None:
    payload = complete_context(include_qualifying_context=True).model_dump(mode="python")
    result = next(
        statement
        for statement in payload["statements"]
        if statement["statement_id"] == STATEMENT_IDS["result"]
    )
    result.update(
        {
            "status": StatementStatus.USER_JUDGMENT,
            "source_refs": [],
            "confirmation": ConfirmationState.CONFIRMED,
            "evidence_strength": EvidenceStrength.SELF_REPORTED,
        }
    )
    context = M5ContextProjectionV1.model_validate(payload)

    decisions = _by_route(M5IsolatedService().evaluate_routes(context))

    assert decisions[RouteType.PEER].eligibility is RouteEligibility.ELIGIBLE
    assert (
        decisions[RouteType.CUSTOMER_EVALUATOR].eligibility
        is RouteEligibility.BLOCKED
    )
    assert "MISSING_VERIFIABLE_RESULT" in decisions[
        RouteType.CUSTOMER_EVALUATOR
    ].reason_codes


def test_confirmed_grounded_inference_may_serve_as_verifiable_result() -> None:
    payload = complete_context(include_qualifying_context=True).model_dump(mode="python")
    result = next(
        statement
        for statement in payload["statements"]
        if statement["statement_id"] == STATEMENT_IDS["result"]
    )
    result.update(
        {
            "status": StatementStatus.AGENT_INFERENCE,
            "source_refs": [],
            "derived_from": [STATEMENT_IDS["decision"]],
            "confirmation": ConfirmationState.CONFIRMED,
            "evidence_strength": EvidenceStrength.INDIRECT,
        }
    )
    context = M5ContextProjectionV1.model_validate(payload)

    decisions = _by_route(M5IsolatedService().evaluate_routes(context))

    assert (
        decisions[RouteType.CUSTOMER_EVALUATOR].eligibility
        is RouteEligibility.ELIGIBLE
    )


def test_unconfirmed_inference_cannot_serve_as_role_evidence() -> None:
    payload = complete_context(include_qualifying_context=True).model_dump(mode="python")
    result = next(
        statement
        for statement in payload["statements"]
        if statement["statement_id"] == STATEMENT_IDS["result"]
    )
    result.update(
        {
            "status": StatementStatus.AGENT_INFERENCE,
            "source_refs": [],
            "derived_from": [STATEMENT_IDS["decision"]],
            "confirmation": ConfirmationState.UNCONFIRMED,
            "evidence_strength": EvidenceStrength.INDIRECT,
        }
    )
    context = M5ContextProjectionV1.model_validate(payload)

    decisions = _by_route(M5IsolatedService().evaluate_routes(context))

    assert decisions[RouteType.PEER].eligibility is RouteEligibility.BLOCKED
    assert "MISSING_PEER_EVIDENCE" in decisions[RouteType.PEER].reason_codes
    assert (
        decisions[RouteType.CUSTOMER_EVALUATOR].eligibility
        is RouteEligibility.BLOCKED
    )
    assert "MISSING_VERIFIABLE_RESULT" in decisions[
        RouteType.CUSTOMER_EVALUATOR
    ].reason_codes


def test_unresolved_statement_cannot_be_smuggled_in_as_route_support() -> None:
    payload = complete_context().model_dump(mode="python")
    payload["evidence"]["beginner_prerequisite"] = [STATEMENT_IDS["unresolved"]]
    with pytest.raises(ValidationError, match="route support"):
        type(complete_context()).model_validate(payload)


def test_public_route_requires_a_supported_disclosure_basis() -> None:
    context = complete_context()
    context = context.model_copy(
        update={"evidence": context.evidence.model_copy(update={"disclosure_basis": []})}
    )
    decision = _by_route(M5IsolatedService().evaluate_routes(context))[RouteType.PUBLIC]
    assert decision.eligibility is RouteEligibility.BLOCKED
    assert "MISSING_DISCLOSURE_BASIS" in decision.reason_codes


def test_open_privacy_findings_gate_external_routes_not_private_review() -> None:
    service = M5IsolatedService()
    context = complete_context()
    review = service.review_privacy(
        context,
        proposals=privacy_risk_proposals(),
        run_id=RUN_ID,
    )
    decisions = _by_route(service.evaluate_routes(context, privacy_review=review))

    assert decisions[RouteType.PRIVATE_SELF].eligibility is RouteEligibility.ELIGIBLE
    assert (
        decisions[RouteType.PUBLIC].eligibility
        is RouteEligibility.ELIGIBLE_AFTER_PRIVACY_APPROVAL
    )
    assert decisions[RouteType.PUBLIC].reason_codes == ["OPEN_PRIVACY_FINDINGS"]
    assert (
        decisions[RouteType.CUSTOMER_EVALUATOR].eligibility
        is RouteEligibility.INELIGIBLE
    )


def test_unknown_privacy_reference_fails_closed() -> None:
    context = complete_context()
    proposal = PrivacyFindingProposalV1(
        category="LOCATION",
        affected_statement_ids=[UUID(int=9999)],
        severity=FindingSeverity.MEDIUM,
        explanation="Unknown reference.",
    )
    with pytest.raises(M5PolicyError, match="unknown content") as error:
        M5IsolatedService().review_privacy(context, proposals=[proposal], run_id=RUN_ID)
    assert error.value.code == "UNKNOWN_PRIVACY_REFERENCE"


@pytest.mark.parametrize(
    "invalid_update",
    [
        {"category": "BIOMETRIC"},
        {"model_decided_safe": True},
    ],
)
def test_privacy_proposal_rejects_unknown_category_and_extra_authority(
    invalid_update: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "category": "LOCATION",
        "affected_statement_ids": [STATEMENT_IDS["identity"]],
        "severity": "HIGH",
        "explanation": "Location detail requires review.",
    }
    payload.update(invalid_update)

    with pytest.raises(ValidationError):
        PrivacyFindingProposalV1.model_validate(payload)


def test_runtime_denies_an_unknown_privacy_action() -> None:
    service = M5IsolatedService()
    context = complete_context()
    review = service.review_privacy(
        context,
        proposals=privacy_risk_proposals(),
        run_id=RUN_ID,
    )
    identity = next(finding for finding in review.findings if finding.category == "IDENTITY")

    with pytest.raises(M5PolicyError) as denied:
        service.resolve_finding(
            context,
            review,
            finding_id=identity.finding_id,
            action="PUBLISH",  # type: ignore[arg-type]
            run_id=UUID(int=599),
        )

    assert denied.value.code == "PRIVACY_ACTION_DENIED"


def test_untrusted_proposal_cannot_downgrade_the_category_severity_floor() -> None:
    context = complete_context(include_sensitive_tags=False)
    review = M5IsolatedService().review_privacy(
        context,
        proposals=[
            PrivacyFindingProposalV1(
                category="LOCATION",
                affected_statement_ids=[STATEMENT_IDS["identity"]],
                severity=FindingSeverity.LOW,
                explanation="A precise location may expose the person.",
            )
        ],
        run_id=RUN_ID,
    )
    finding = review.findings[0]
    assert finding.severity is FindingSeverity.HIGH
    assert finding.proposed_actions == ["GENERALIZE", "REMOVE"]


def test_all_nine_tagged_privacy_categories_are_detected_deterministically() -> None:
    context = complete_context()
    categories = {
        "IDENTITY",
        "HEALTH_BODY",
        "LOCATION",
        "PURCHASE_PAYMENT",
        "THIRD_PARTY",
        "SCREENSHOT_METADATA",
        "COPYRIGHT",
        "UNVERIFIED_BRAND_CLAIM",
        "PROFESSIONAL_ADVICE",
    }
    first = context.statements[0].model_copy(update={"sensitivity_tags": sorted(categories)})
    others = [
        statement.model_copy(update={"sensitivity_tags": []})
        for statement in context.statements[1:]
    ]
    context = context.model_copy(update={"statements": [first, *others]})

    review = M5IsolatedService().review_tagged_privacy(context, run_id=RUN_ID)
    assert {finding.category for finding in review.findings} == categories
    assert all(
        finding.affected_statement_ids == [first.statement_id]
        for finding in review.findings
    )


def test_empty_additional_proposals_keep_tagged_findings_and_block_approval() -> None:
    service = M5IsolatedService()
    context = complete_context()
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = _public_draft()

    assert {finding.category for finding in review.findings} == {
        "IDENTITY",
        "HEALTH_BODY",
    }
    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            matrix,
            review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=_approval_request(
                draft,
                review.review_hash,
                _by_route(matrix)[RouteType.PUBLIC],
            ),
        )
    assert denied.value.code == "OPEN_PRIVACY_FINDINGS"


def test_unknown_canonical_sensitivity_tag_fails_closed() -> None:
    context = complete_context(include_sensitive_tags=False)
    first = context.statements[0].model_copy(
        update={"sensitivity_tags": ["UNRECOGNIZED_PRIVATE_DATA"]}
    )
    context = context.model_copy(update={"statements": [first, *context.statements[1:]]})

    with pytest.raises(M5PolicyError) as denied:
        M5IsolatedService().review_privacy(context, proposals=[], run_id=RUN_ID)

    assert denied.value.code == "UNKNOWN_SENSITIVITY_TAG"


def test_additional_proposal_cannot_remove_or_duplicate_tagged_finding() -> None:
    context = complete_context()
    review = M5IsolatedService().review_privacy(
        context,
        proposals=[
            PrivacyFindingProposalV1(
                category="IDENTITY",
                affected_statement_ids=[STATEMENT_IDS["identity"]],
                severity=FindingSeverity.CRITICAL,
                explanation="Model also detected the tagged identity detail.",
            )
        ],
        run_id=RUN_ID,
    )

    identity_findings = [
        finding for finding in review.findings if finding.category == "IDENTITY"
    ]
    assert len(identity_findings) == 1
    assert identity_findings[0].severity is FindingSeverity.CRITICAL
    assert identity_findings[0].proposed_actions == ["GENERALIZE", "REMOVE"]


def test_failed_privacy_review_never_means_zero_risk() -> None:
    service = M5IsolatedService()
    context = complete_context()
    failed = service.fail_privacy_review(context, failure_code="MODEL_UNAVAILABLE")
    decisions = _by_route(service.evaluate_routes(context, privacy_review=failed))

    assert decisions[RouteType.PRIVATE_SELF].eligibility is RouteEligibility.ELIGIBLE
    assert decisions[RouteType.PUBLIC].eligibility is RouteEligibility.BLOCKED
    assert decisions[RouteType.PUBLIC].reason_codes == ["PRIVACY_REVIEW_FAILED"]


def test_resolution_policy_denies_acknowledging_identity_and_keeps_low_copyright() -> None:
    service = M5IsolatedService()
    context = complete_context()
    review = service.review_privacy(
        context,
        proposals=privacy_risk_proposals(),
        run_id=RUN_ID,
    )
    identity = next(finding for finding in review.findings if finding.category == "IDENTITY")
    with pytest.raises(M5PolicyError) as denied:
        service.resolve_finding(
            context,
            review,
            finding_id=identity.finding_id,
            action=PrivacyActionV1.ACKNOWLEDGE,
            run_id=UUID(int=600),
        )
    assert denied.value.code == "PRIVACY_ACTION_DENIED"

    copyright_finding = next(
        finding for finding in review.findings if finding.category == "COPYRIGHT"
    )
    result = service.resolve_finding(
        context,
        review,
        finding_id=copyright_finding.finding_id,
        action=PrivacyActionV1.KEEP,
        run_id=UUID(int=601),
    )
    updated = next(
        finding
        for finding in result.review.findings
        if finding.finding_id == copyright_finding.finding_id
    )
    assert not result.requires_canonical_change
    assert updated.resolution is PrivacyResolution.KEEP
    assert result.review.review_hash != review.review_hash


def test_generalize_requests_new_canonical_version_without_in_place_resolution() -> None:
    service = M5IsolatedService()
    context = complete_context()
    review = service.review_privacy(
        context,
        proposals=privacy_risk_proposals(),
        run_id=RUN_ID,
    )
    identity = next(finding for finding in review.findings if finding.category == "IDENTITY")
    result = service.resolve_finding(
        context,
        review,
        finding_id=identity.finding_id,
        action=PrivacyActionV1.GENERALIZE,
        run_id=UUID(int=602),
    )
    assert result.requires_canonical_change
    assert result.review == review
    assert identity.resolution is PrivacyResolution.OPEN


def test_approval_is_exact_bound_idempotent_and_stale_after_correction() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = _public_draft()
    request = _approval_request(
        draft,
        review.review_hash,
        _by_route(matrix)[RouteType.PUBLIC],
    )

    approval = service.approve(
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
        request=request,
    )
    repeated = service.approve(
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
        request=request,
        existing=[approval],
    )
    assert repeated == approval
    assert service.approval_status(
        approval,
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
    ).valid

    stale = service.approval_status(
        approval,
        correction_context(context),
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
    )
    assert not stale.valid
    assert "M5_INPUT_STALE" in stale.reason_codes

    changed_relation = context.model_copy(
        update={
            "relation": context.relation.model_copy(
                update={"projection_hash": "8" * 64}
            )
        }
    )
    relation_stale = service.approval_status(
        approval,
        changed_relation,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
    )
    assert not relation_stale.valid
    assert "ROUTE_MATRIX_STALE" in relation_stale.reason_codes


def test_approval_recomputes_privacy_review_hash_instead_of_trusting_caller() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    forged_review = review.model_copy(update={"review_hash": "a" * 64})
    matrix = service.evaluate_routes(context, privacy_review=forged_review)
    draft = _public_draft()

    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            matrix,
            forged_review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=_approval_request(
                draft,
                forged_review.review_hash,
                _by_route(matrix)[RouteType.PUBLIC],
            ),
        )

    assert denied.value.code == "PRIVACY_REVIEW_HASH_MISMATCH"


def test_approval_rejects_correctly_hashed_review_that_omits_tagged_findings() -> None:
    service = M5IsolatedService()
    context = complete_context()
    legitimate = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    forged_review = m5_policy._make_privacy_review(
        context,
        status=legitimate.status,
        findings=[],
        proposal_sources=legitimate.proposal_sources,
        detector_version=legitimate.detector_version,
    )
    matrix = service.evaluate_routes(context, privacy_review=forged_review)
    draft = _public_draft()

    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            matrix,
            forged_review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=_approval_request(
                draft,
                forged_review.review_hash,
                _by_route(matrix)[RouteType.PUBLIC],
            ),
        )

    assert denied.value.code == "PRIVACY_REVIEW_POLICY_MISMATCH"


def test_approval_rejects_correctly_hashed_forbidden_privacy_resolution() -> None:
    service = M5IsolatedService()
    context = complete_context()
    legitimate = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    forged_findings = [
        finding.model_copy(update={"resolution": PrivacyResolution.KEEP})
        if finding.category == "IDENTITY"
        else finding
        for finding in legitimate.findings
    ]
    forged_review = m5_policy._make_privacy_review(
        context,
        status=legitimate.status,
        findings=forged_findings,
        proposal_sources=legitimate.proposal_sources,
        detector_version=legitimate.detector_version,
    )
    matrix = service.evaluate_routes(context, privacy_review=forged_review)
    draft = _public_draft()

    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            matrix,
            forged_review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=_approval_request(
                draft,
                forged_review.review_hash,
                _by_route(matrix)[RouteType.PUBLIC],
            ),
        )

    assert denied.value.code == "PRIVACY_REVIEW_POLICY_MISMATCH"


def test_approval_recomputes_route_matrix_instead_of_trusting_eligible_claim() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    context = context.model_copy(
        update={
            "evidence": context.evidence.model_copy(update={"disclosure_basis": []})
        }
    )
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    real_public = _by_route(matrix)[RouteType.PUBLIC]
    assert real_public.eligibility is RouteEligibility.BLOCKED
    forged_public = real_public.model_copy(
        update={
            "eligibility": RouteEligibility.ELIGIBLE,
            "reason_codes": ["READY"],
            "explanation": "Caller-forged eligibility.",
            "missing_statement_ids": [],
        }
    )
    forged_matrix = matrix.model_copy(
        update={
            "decisions": [
                forged_public if decision.route is RouteType.PUBLIC else decision
                for decision in matrix.decisions
            ]
        }
    )
    draft = _public_draft()

    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            forged_matrix,
            review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=_approval_request(draft, review.review_hash, forged_public),
        )

    assert denied.value.code == "ROUTE_MATRIX_POLICY_MISMATCH"


def test_old_route_inputs_cannot_approve_after_relation_projection_changes() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    changed_context = context.model_copy(
        update={
            "relation": context.relation.model_copy(
                update={"projection_hash": "8" * 64}
            )
        }
    )
    draft = _public_draft()

    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            changed_context,
            matrix,
            review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=_approval_request(
                draft,
                review.review_hash,
                _by_route(matrix)[RouteType.PUBLIC],
            ),
        )

    assert denied.value.code == "ROUTE_MATRIX_STALE"


def test_approval_validity_rejects_forged_scope_and_user_action() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = _public_draft()
    approval = service.approve(
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
        request=_approval_request(
            draft,
            review.review_hash,
            _by_route(matrix)[RouteType.PUBLIC],
        ),
    )
    assert approval.scope is ApprovalScope.SHAREABLE_EXPORT

    forged_action = approval.model_copy(update={"user_action": "IN_APP_PREVIEW"})
    action_status = service.approval_status(
        forged_action,
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
    )
    assert not action_status.valid
    assert "APPROVAL_ACTION_INVALID" in action_status.reason_codes

    forged_scope = approval.model_copy(update={"scope": "PRIVATE_PREVIEW"})
    scope_status = service.approval_status(
        forged_scope,
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
    )
    assert not scope_status.valid
    assert "APPROVAL_SCOPE_INVALID" in scope_status.reason_codes


def test_approval_becomes_stale_when_approval_policy_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = _public_draft()
    approval = service.approve(
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
        request=_approval_request(
            draft,
            review.review_hash,
            _by_route(matrix)[RouteType.PUBLIC],
        ),
    )

    monkeypatch.setattr(m5_policy, "APPROVAL_POLICY_VERSION", "m5-approval-policy-v2")
    status = service.approval_status(
        approval,
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
    )
    assert not status.valid
    assert "ROUTE_DRAFT_STALE" in status.reason_codes


def test_approval_without_a_stored_final_draft_is_denied() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = _public_draft()
    request = _approval_request(
        draft,
        review.review_hash,
        _by_route(matrix)[RouteType.PUBLIC],
    )
    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            matrix,
            review,
            draft=None,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=request,
        )
    assert denied.value.code == "ROUTE_DRAFT_REQUIRED"


def test_approval_rejects_a_draft_with_an_unauthorized_statement_reference() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = _public_draft(statement_ids=[UUID(int=9999)])
    request = _approval_request(
        draft,
        review.review_hash,
        _by_route(matrix)[RouteType.PUBLIC],
    )
    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            matrix,
            review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=request,
        )
    assert denied.value.code == "UNAUTHORIZED_DRAFT_REFERENCE"


def test_approval_is_denied_while_privacy_findings_are_open() -> None:
    service = M5IsolatedService()
    context = complete_context()
    review = service.review_privacy(
        context,
        proposals=privacy_risk_proposals(),
        run_id=RUN_ID,
    )
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = _public_draft()
    request = _approval_request(
        draft,
        review.review_hash,
        _by_route(matrix)[RouteType.PUBLIC],
    )

    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            matrix,
            review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=request,
        )
    assert denied.value.code == "OPEN_PRIVACY_FINDINGS"


def test_resolving_findings_requires_a_fresh_route_matrix_before_approval() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    copyright_only = [
        proposal
        for proposal in privacy_risk_proposals()
        if proposal.category.value == "COPYRIGHT"
    ]
    open_review = service.review_privacy(
        context,
        proposals=copyright_only,
        run_id=RUN_ID,
    )
    old_matrix = service.evaluate_routes(context, privacy_review=open_review)
    resolved = service.resolve_finding(
        context,
        open_review,
        finding_id=open_review.findings[0].finding_id,
        action=PrivacyActionV1.KEEP,
        run_id=UUID(int=700),
    ).review
    draft = _public_draft()
    request = _approval_request(
        draft,
        resolved.review_hash,
        _by_route(old_matrix)[RouteType.PUBLIC],
    )

    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            old_matrix,
            resolved,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=request,
        )
    assert denied.value.code == "ROUTE_REEVALUATION_REQUIRED"


def test_private_route_cannot_receive_an_external_share_approval() -> None:
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = _public_draft().model_copy(update={"route": RouteType.PRIVATE_SELF})
    request = _approval_request(
        draft,
        review.review_hash,
        _by_route(matrix)[RouteType.PRIVATE_SELF],
    )

    with pytest.raises(M5PolicyError) as denied:
        service.approve(
            context,
            matrix,
            review,
            draft=draft,
            renderer_input_hash=RENDERER_INPUT_HASH,
            request=request,
        )
    assert denied.value.code == "PRIVATE_ROUTE_NOT_SHAREABLE"


def test_preview_and_private_download_do_not_grant_approval() -> None:
    service = M5IsolatedService()
    assert not service.operation_requires_external_approval("IN_APP_PREVIEW")
    assert not service.operation_requires_external_approval("PRIVATE_DOWNLOAD")
    assert service.operation_requires_external_approval("SHAREABLE_EXTERNAL_EXPORT")


def test_client_approved_boolean_is_rejected_as_an_extra_field() -> None:
    draft = _public_draft()
    with pytest.raises(ValidationError, match="approved"):
        ApprovalRequestV1.model_validate(
            {
                **_approval_request(
                    draft,
                    "7" * 64,
                    _by_route(M5IsolatedService().evaluate_routes(complete_context()))[
                        RouteType.PUBLIC
                    ],
                ).model_dump(mode="json"),
                "approved": True,
            }
        )
