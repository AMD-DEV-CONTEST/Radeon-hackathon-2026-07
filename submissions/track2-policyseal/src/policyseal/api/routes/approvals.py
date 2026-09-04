from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from policyseal.api.dependencies import AppServices, get_services
from policyseal.api.schemas import (
    ApprovalRequestInput,
    ApprovalResolveInput,
    ApprovalResponse,
)

router = APIRouter(tags=["approvals"])


@router.get("/api/revisions/{revision_id}/approval-request", response_model=ApprovalResponse)
def get_revision_approval(
    revision_id: str,
    services: Annotated[AppServices, Depends(get_services)],
) -> ApprovalResponse:
    return ApprovalResponse.from_domain(services.repository.get_approval_for_revision(revision_id))


@router.post(
    "/api/revisions/{revision_id}/approval-requests",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
def request_approval(
    revision_id: str,
    body: ApprovalRequestInput,
    services: Annotated[AppServices, Depends(get_services)],
) -> ApprovalResponse:
    return ApprovalResponse.from_domain(services.approvals.request(revision_id, actor=body.actor))


@router.post("/api/approval-requests/{approval_id}/approve", response_model=ApprovalResponse)
def approve(
    approval_id: str,
    body: ApprovalResolveInput,
    services: Annotated[AppServices, Depends(get_services)],
) -> ApprovalResponse:
    approval = services.repository.get_approval(approval_id)
    return ApprovalResponse.from_domain(
        services.approvals.approve(
            approval.revision_id,
            actor=body.actor,
            expected_binding_sha256=body.expected_binding_sha256,
        )
    )


@router.post("/api/approval-requests/{approval_id}/reject", response_model=ApprovalResponse)
def reject(
    approval_id: str,
    body: ApprovalResolveInput,
    services: Annotated[AppServices, Depends(get_services)],
) -> ApprovalResponse:
    approval = services.repository.get_approval(approval_id)
    return ApprovalResponse.from_domain(
        services.approvals.reject(
            approval.revision_id,
            actor=body.actor,
            reason_code=body.reason_code or "policy_reviewer_rejected",
        )
    )
