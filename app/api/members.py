"""
Phase H — 成员管理 API

项目成员的添加、更新角色、移除和列表。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.observability.error_codes import get_error
from app.schemas.models import ProjectMemberAdd, ProjectMemberEntry
from app.security.permissions import get_current_user, require_project_role
from app.services.membership import MembershipService

router = APIRouter(prefix="/projects/{project_id}/members", tags=["members"])


def _get_svc(request: Request) -> MembershipService:
    return request.app.state.membership_service


@router.get("", response_model=list[ProjectMemberEntry], dependencies=[Depends(require_project_role("guest"))])
async def list_members(project_id: str, request: Request, _: dict = Depends(get_current_user)):
    """List all members of a project (visible to all members including guests)."""
    svc = _get_svc(request)
    return svc.list_members(project_id)


@router.post("", response_model=ProjectMemberEntry, status_code=201)
async def add_member(
    project_id: str,
    body: ProjectMemberAdd,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Add a member to the project.

    Bootstrapping: if the project has no members yet, the first authenticated user
    to join is automatically made admin.
    Otherwise, requires admin role.
    """
    svc = _get_svc(request)
    db_path = request.app.state.db_path
    from app.security.permissions import get_project_role, has_min_role

    # Check if project is empty (no members) — allow bootstrapping
    members = svc.list_members(project_id)
    if len(members) == 0:
        # First member must be admin
        if body.role.value != "admin":
            raise HTTPException(status_code=400, detail="First member must be admin")
    else:
        # Normal check: require admin role
        role = get_project_role(db_path, project_id, user["user_id"])
        if not has_min_role(role, "admin"):
            raise HTTPException(status_code=403, detail=get_error("ACCESS_DENIED"))

    try:
        return svc.add_member(project_id, body.user_id, body.role.value)
    except ValueError as e:
        if "already exists" in str(e).lower():
            raise HTTPException(status_code=409, detail=get_error("MEMBER_ALREADY_EXISTS"))
        raise HTTPException(status_code=404, detail=get_error("USER_NOT_FOUND"))


@router.put("/{user_id}", response_model=ProjectMemberEntry)
async def update_member_role(
    project_id: str,
    user_id: str,
    body: ProjectMemberAdd,
    request: Request,
    _: None = Depends(require_project_role("admin")),
):
    """Update a member's role (admin only)."""
    svc = _get_svc(request)
    try:
        return svc.update_member_role(project_id, user_id, body.role.value)
    except ValueError:
        raise HTTPException(status_code=404, detail=get_error("USER_NOT_IN_PROJECT"))


@router.delete("/{user_id}", status_code=204)
async def remove_member(
    project_id: str,
    user_id: str,
    request: Request,
    _: None = Depends(require_project_role("admin")),
):
    """Remove a member from the project (admin only)."""
    svc = _get_svc(request)
    if not svc.remove_member(project_id, user_id):
        raise HTTPException(status_code=404, detail=get_error("USER_NOT_IN_PROJECT"))
