"""
Phase H — 通知收件箱 API

站内通知列表、标记已读、未读计数。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.observability.error_codes import get_error
from app.schemas.models import NotificationEntry
from app.security.permissions import get_current_user
from app.services.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _ntf_svc(request: Request) -> NotificationService:
    return request.app.state.notification_service


@router.get("", response_model=list[NotificationEntry])
async def list_notifications(
    request: Request,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    """List notifications for the current user."""
    return _ntf_svc(request).list_notifications(
        user["user_id"], unread_only=unread_only, limit=limit, offset=offset
    )


@router.get("/unread-count", response_model=dict)
async def unread_count(request: Request, user: dict = Depends(get_current_user)):
    """Get the count of unread notifications."""
    cnt = _ntf_svc(request).unread_count(user["user_id"])
    return {"unread_count": cnt}


@router.put("/{notification_id}/read", response_model=dict)
async def mark_read(
    notification_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Mark a specific notification as read."""
    result = _ntf_svc(request).mark_read(notification_id, user["user_id"])
    if result is None:
        raise HTTPException(status_code=404, detail=get_error("NOTIFICATION_NOT_FOUND"))
    return result


@router.put("/read-all", response_model=dict)
async def mark_all_read(request: Request, user: dict = Depends(get_current_user)):
    """Mark all notifications as read."""
    count = _ntf_svc(request).mark_all_read(user["user_id"])
    return {"marked_read": count}
