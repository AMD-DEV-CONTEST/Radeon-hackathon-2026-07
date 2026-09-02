"""
Phase H — 报告中心 API

报告草稿的创建、编辑、审批、版控与导出 (PDF/DOCX)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.observability.error_codes import get_error
from app.schemas.models import (
    ReportApprovalRequest,
    ReportDraftCreate,
    ReportDraftEntry,
    ReportDraftUpdate,
)
from app.security.permissions import get_current_user, require_project_role
from app.services.report_center import ReportCenterService

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["reports"])


def _svc(request: Request) -> ReportCenterService:
    return request.app.state.report_center_service


@router.get("", response_model=list[ReportDraftEntry])
async def list_report_drafts(
    project_id: str,
    request: Request,
    status: str | None = Query(default=None),
    _: None = Depends(require_project_role("guest")),
):
    """List report drafts for a project."""
    return _svc(request).list_drafts(project_id, status)


@router.post("", response_model=ReportDraftEntry, status_code=201)
async def create_report_draft(
    project_id: str,
    body: ReportDraftCreate,
    request: Request,
    _: None = Depends(require_project_role("member")),
    user: dict = Depends(get_current_user),
):
    """Create a new report draft."""
    return _svc(request).create_draft(project_id, body.title, user["user_id"], body.content_md)


@router.get("/{draft_id}", response_model=ReportDraftEntry)
async def get_report_draft(
    project_id: str,
    draft_id: str,
    request: Request,
    _: None = Depends(require_project_role("guest")),
):
    """Get a report draft by ID."""
    draft = _svc(request).get_draft(draft_id)
    if draft is None or draft.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=get_error("REPORT_DRAFT_NOT_FOUND"))
    return draft


@router.put("/{draft_id}", response_model=ReportDraftEntry)
async def update_report_draft(
    project_id: str,
    draft_id: str,
    body: ReportDraftUpdate,
    request: Request,
    _: None = Depends(require_project_role("member")),
    user: dict = Depends(get_current_user),
):
    """Update a report draft's title and/or content."""
    svc = _svc(request)
    draft = svc.get_draft(draft_id)
    if draft is None or draft.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=get_error("REPORT_DRAFT_NOT_FOUND"))
    updated = svc.update_draft(draft_id, title=body.title, content_md=body.content_md)
    return updated


@router.post("/{draft_id}/submit", response_model=ReportDraftEntry)
async def submit_for_approval(
    project_id: str,
    draft_id: str,
    request: Request,
    _: None = Depends(require_project_role("member")),
    user: dict = Depends(get_current_user),
):
    """Submit a report draft for approval."""
    svc = _svc(request)
    draft = svc.get_draft(draft_id)
    if draft is None or draft.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=get_error("REPORT_DRAFT_NOT_FOUND"))
    if draft.get("status") != "draft":
        raise HTTPException(status_code=400, detail=get_error("REPORT_ALREADY_SUBMITTED"))
    result = svc.submit_for_approval(draft_id)

    # Notify PM/admins
    from app.services.notifications import NotificationService
    from app.services.membership import MembershipService
    ntf = NotificationService(request.app.state.db_path)
    msvc = MembershipService(request.app.state.db_path)
    members = msvc.list_members(project_id)
    for m in members:
        if m["role"] in ("admin", "pm"):
            ntf.create_notification(
                recipient_id=m["user_id"],
                kind="report_approved",
                title=f"Report '{draft['title']}' submitted for approval",
                body=f"Submitted by {user.get('username', 'Unknown')}",
                link=f"/projects/{project_id}/reports/{draft_id}",
            )

    return result


@router.post("/{draft_id}/approve", response_model=ReportDraftEntry)
async def approve_report(
    project_id: str,
    draft_id: str,
    body: ReportApprovalRequest,
    request: Request,
    _: None = Depends(require_project_role("pm")),
    user: dict = Depends(get_current_user),
):
    """Approve, reject, or request changes on a report draft."""
    svc = _svc(request)
    draft = svc.get_draft(draft_id)
    if draft is None or draft.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=get_error("REPORT_DRAFT_NOT_FOUND"))

    result = svc.approve_report(draft_id, user["user_id"], body.decision, body.comment)

    # Notify author
    from app.services.notifications import NotificationService
    ntf = NotificationService(request.app.state.db_path)
    decision_label = {"approved": "approved", "rejected": "rejected", "request_changes": "requested changes on"}
    ntf.create_notification(
        recipient_id=draft["author_id"],
        kind="report_approved",
        title=f"Your report '{draft['title']}' was {decision_label.get(body.decision, body.decision)}",
        body=body.comment,
        link=f"/projects/{project_id}/reports/{draft_id}",
    )

    return result


@router.get("/{draft_id}/approvals", response_model=list[dict])
async def get_approval_history(
    project_id: str,
    draft_id: str,
    request: Request,
    _: None = Depends(require_project_role("guest")),
):
    """Get the approval history for a report draft."""
    svc = _svc(request)
    draft = svc.get_draft(draft_id)
    if draft is None or draft.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=get_error("REPORT_DRAFT_NOT_FOUND"))
    return svc.get_approvals(draft_id)


@router.get("/{draft_id}/export/pdf")
async def export_pdf(
    project_id: str,
    draft_id: str,
    request: Request,
    _: None = Depends(require_project_role("member")),
):
    """Export a report draft as PDF."""
    svc = _svc(request)
    try:
        pdf_bytes = svc.export_pdf_bytes(draft_id)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=report-{draft_id}.pdf"},
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=get_error("REPORT_DRAFT_NOT_FOUND"))
    except Exception:
        raise HTTPException(status_code=500, detail=get_error("REPORT_EXPORT_FAILED"))


@router.get("/{draft_id}/export/docx")
async def export_docx(
    project_id: str,
    draft_id: str,
    request: Request,
    _: None = Depends(require_project_role("member")),
):
    """Export a report draft as DOCX."""
    svc = _svc(request)
    try:
        docx_bytes = svc.export_docx_bytes(draft_id)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename=report-{draft_id}.docx"},
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=get_error("REPORT_DRAFT_NOT_FOUND"))
    except Exception:
        raise HTTPException(status_code=500, detail=get_error("REPORT_EXPORT_FAILED"))
