"""
Phase H — 评论 API

支持对任务、风险、报告段落实体的评论创建、列表、更新和回复。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.observability.error_codes import get_error
from app.schemas.models import CommentCreate, CommentEntry, CommentUpdate
from app.security.permissions import get_current_user, require_project_role
from app.services.comments import CommentService
from app.services.notifications import NotificationService

router = APIRouter(prefix="/projects/{project_id}", tags=["comments"])


def _cmt_svc(request: Request) -> CommentService:
    return request.app.state.comment_service


def _ntf_svc(request: Request) -> NotificationService:
    return request.app.state.notification_service


@router.post("/comments", response_model=dict, status_code=201)
async def create_comment(
    project_id: str,
    body: CommentCreate,
    request: Request,
    _: None = Depends(require_project_role("member")),
    user: dict = Depends(get_current_user),
):
    """Post a comment on a task, risk, or report section.

    Supports @mentions and threaded replies via parent_id.
    """
    cmt = _cmt_svc(request)
    ntf = _ntf_svc(request)

    # Extract @mentions from body
    mentioned = cmt.extract_mentions(body.body)

    comment = cmt.create_comment(
        project_id=project_id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        author_id=user["user_id"],
        body=body.body,
        parent_id=body.parent_id,
        mentions=mentioned,
    )

    # Notify mentioned users
    if mentioned:
        for uname in mentioned:
            from app.security.auth import AuthService
            auth: AuthService = request.app.state.auth_service
            all_users = auth.list_users()
            for u in all_users:
                if u["username"] == uname and u["user_id"] != user["user_id"]:
                    ntf.create_notification(
                        recipient_id=u["user_id"],
                        kind="mention",
                        title=f"@{user.get('username', 'Someone')} mentioned you in a comment",
                        body=body.body[:200],
                        link=f"/projects/{project_id}/comments/{comment['id']}",
                    )

    # Notify parent comment author if reply
    if body.parent_id:
        parent = cmt.get_comment(body.parent_id)
        if parent and parent["author_id"] != user["user_id"]:
            ntf.create_notification(
                recipient_id=parent["author_id"],
                kind="comment_reply",
                title=f"{user.get('username', 'Someone')} replied to your comment",
                body=body.body[:200],
                link=f"/projects/{project_id}/comments/{comment['id']}",
            )

    return comment


@router.get("/comments", response_model=list[CommentEntry])
async def list_comments(
    project_id: str,
    entity_type: str,
    entity_id: str,
    request: Request,
    _: None = Depends(require_project_role("guest")),
):
    """List all comments for a given entity, threaded."""
    return _cmt_svc(request).list_comments(project_id, entity_type, entity_id)


@router.put("/comments/{comment_id}", response_model=dict)
async def update_comment(
    project_id: str,
    comment_id: str,
    body: CommentUpdate,
    request: Request,
    _: None = Depends(require_project_role("member")),
    user: dict = Depends(get_current_user),
):
    """Edit a comment body."""
    cmt = _cmt_svc(request)
    existing = cmt.get_comment(comment_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=get_error("COMMENT_NOT_FOUND"))
    if existing["author_id"] != user["user_id"]:
        raise HTTPException(status_code=403, detail=get_error("ACCESS_DENIED"))
    updated = cmt.update_comment(comment_id, body.body)
    return updated


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    project_id: str,
    comment_id: str,
    request: Request,
    _: None = Depends(require_project_role("pm")),
    user: dict = Depends(get_current_user),
):
    """Delete a comment (PM+ or author)."""
    cmt = _cmt_svc(request)
    existing = cmt.get_comment(comment_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=get_error("COMMENT_NOT_FOUND"))
    # Author can delete own comments; PM/admin can delete any
    from app.security.permissions import get_project_role, has_min_role
    role = get_project_role(request.app.state.db_path, project_id, user["user_id"])
    if existing["author_id"] != user["user_id"] and not has_min_role(role, "pm"):
        raise HTTPException(status_code=403, detail=get_error("ACCESS_DENIED"))
    cmt.delete_comment(comment_id)


@router.post("/comments/{comment_id}/resolve", response_model=dict)
async def resolve_comment(
    project_id: str,
    comment_id: str,
    request: Request,
    _: None = Depends(require_project_role("pm")),
):
    """Mark a comment as resolved (PM+)."""
    cmt = _cmt_svc(request)
    result = cmt.resolve_comment(comment_id, True)
    if result is None:
        raise HTTPException(status_code=404, detail=get_error("COMMENT_NOT_FOUND"))
    return result
