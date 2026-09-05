"""Facade for the isolated E6/M5 policy slice."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.experience_asset.domain.enums import PrivacyResolution, RouteType
from app.experience_asset.domain.models import ApprovalRecord, RouteDraft
from app.experience_asset.policy.m5 import (
    M5PolicyError,
    approve_shareable_draft,
    build_privacy_review,
    evaluate_approval,
    evaluate_route_matrix,
    failed_privacy_review,
    resolve_privacy_finding,
)

from .contracts import (
    ApprovalRequestV1,
    ApprovalValidityV1,
    M5ContextProjectionV1,
    PrivacyActionV1,
    PrivacyFindingProposalV1,
    PrivacyResolutionResultV1,
    PrivacyReviewV1,
    RouteReadinessMatrixV1,
    StoredDraftBindingV1,
)


class M5IsolatedService:
    """Coordinate E6 pure policy without owning persistence or shared wiring."""

    def evaluate_routes(
        self,
        context: M5ContextProjectionV1,
        *,
        privacy_review: PrivacyReviewV1 | None = None,
    ) -> RouteReadinessMatrixV1:
        return evaluate_route_matrix(context, privacy_review=privacy_review)

    def review_privacy(
        self,
        context: M5ContextProjectionV1,
        *,
        proposals: Sequence[PrivacyFindingProposalV1],
        run_id: UUID,
        run_text_detector: bool = True,
    ) -> PrivacyReviewV1:
        return build_privacy_review(
            context,
            proposals=proposals,
            run_id=run_id,
            run_text_detector=run_text_detector,
        )

    def review_tagged_privacy(
        self,
        context: M5ContextProjectionV1,
        *,
        run_id: UUID,
    ) -> PrivacyReviewV1:
        return build_privacy_review(context, proposals=(), run_id=run_id)

    def fail_privacy_review(
        self,
        context: M5ContextProjectionV1,
        *,
        failure_code: str,
    ) -> PrivacyReviewV1:
        return failed_privacy_review(context, failure_code=failure_code)

    def resolve_finding(
        self,
        context: M5ContextProjectionV1,
        review: PrivacyReviewV1,
        *,
        finding_id: UUID,
        action: PrivacyActionV1,
        run_id: UUID,
    ) -> PrivacyResolutionResultV1:
        return resolve_privacy_finding(
            context,
            review,
            finding_id=finding_id,
            action=action,
            run_id=run_id,
        )

    def approve(
        self,
        context: M5ContextProjectionV1,
        matrix: RouteReadinessMatrixV1,
        review: PrivacyReviewV1,
        *,
        draft: RouteDraft | None,
        renderer_input_hash: str,
        request: ApprovalRequestV1,
        existing: Sequence[ApprovalRecord] = (),
    ) -> ApprovalRecord:
        if draft is None:
            raise M5PolicyError(
                "ROUTE_DRAFT_REQUIRED",
                "external approval requires one stored final RouteDraft",
            )
        binding = StoredDraftBindingV1(
            draft=draft,
            renderer_input_hash=renderer_input_hash,
        )
        return approve_shareable_draft(
            context,
            matrix,
            review,
            draft_binding=binding,
            request=request,
            existing=existing,
        )

    def approval_status(
        self,
        approval: ApprovalRecord,
        context: M5ContextProjectionV1,
        matrix: RouteReadinessMatrixV1,
        review: PrivacyReviewV1,
        *,
        draft: RouteDraft,
        renderer_input_hash: str,
    ) -> ApprovalValidityV1:
        return evaluate_approval(
            approval,
            context,
            matrix,
            review,
            draft_binding=StoredDraftBindingV1(
                draft=draft,
                renderer_input_hash=renderer_input_hash,
            ),
        )

    @staticmethod
    def operation_requires_external_approval(operation: str) -> bool:
        """Only shareable export requires approval; no operation grants it."""

        return operation == "SHAREABLE_EXTERNAL_EXPORT"

    @staticmethod
    def route_requires_external_approval(route: RouteType) -> bool:
        return route is not RouteType.PRIVATE_SELF

    @staticmethod
    def finding_is_resolved(resolution: PrivacyResolution) -> bool:
        return resolution is not PrivacyResolution.OPEN
