"""
Phase H — 基于角色的权限控制

提供 FastAPI 依赖注入（Depends）形式的权限守卫。
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from fastapi import Depends, Header, HTTPException, Request

from app.observability.error_codes import get_error
from app.security.auth import AuthService, verify_token

# Default db path — overridden by main.py
_AUTH_SERVICE: AuthService | None = None


def set_auth_service(svc: AuthService) -> None:
    global _AUTH_SERVICE
    _AUTH_SERVICE = svc


def _get_auth() -> AuthService:
    if _AUTH_SERVICE is None:
        raise RuntimeError("AuthService not initialised")
    return _AUTH_SERVICE


# ---------------------------------------------------------------------------
# FastAPI dependency: extract current user from Bearer token
# ---------------------------------------------------------------------------

async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """Dependency that extracts and validates the current user from the Authorization header."""
    if authorization is None or not authorization.startswith("Bearer "):
        err = get_error("AUTH_TOKEN_MISSING")
        raise HTTPException(status_code=401, detail=err)
    token = authorization[len("Bearer "):]
    payload = verify_token(token)
    if payload is None:
        err = get_error("AUTH_TOKEN_INVALID")
        raise HTTPException(status_code=401, detail=err)
    user_id = payload.get("sub")
    if not user_id:
        err = get_error("AUTH_TOKEN_INVALID")
        raise HTTPException(status_code=401, detail=err)
    user = _get_auth().get_user(user_id)
    if user is None:
        err = get_error("USER_NOT_FOUND")
        raise HTTPException(status_code=401, detail=err)
    if not user["is_active"]:
        err = get_error("AUTH_TOKEN_INVALID")
        raise HTTPException(status_code=401, detail=err)
    return user


async def get_project_api_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict | None:
    """Return a user for protected project APIs, honoring only an explicit test migration flag."""
    if not request.app.state.settings.enforce_project_authorization:
        return None
    return await get_current_user(request, authorization)


# ---------------------------------------------------------------------------
# Role checking
# ---------------------------------------------------------------------------

ROLE_HIERARCHY: dict[str, int] = {
    "admin": 4,
    "pm": 3,
    "member": 2,
    "guest": 1,
}

MINIMAL_ROLES: dict[str, str] = {
    "project_view": "guest",
    "task_view": "guest",
    "task_edit": "member",
    "risk_view": "guest",
    "risk_manage": "pm",
    "member_manage": "admin",
    "report_create": "member",
    "report_approve": "pm",
    "file_upload": "member",
    "file_download": "member",
    "file_delete": "admin",
    "comment_create": "member",
    "comment_resolve": "pm",
}


def get_project_role(db_path: str, project_id: str, user_id: str) -> str | None:
    """Return the user's role in a project, or None if not a member."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT role FROM project_member WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        return row["role"] if row else None
    finally:
        conn.close()


def has_min_role(user_role: str | None, required_role: str) -> bool:
    """Check if user_role meets or exceeds required_role in hierarchy."""
    if user_role is None:
        return False
    return ROLE_HIERARCHY.get(user_role, 0) >= ROLE_HIERARCHY.get(required_role, 0)


def require_project_role(required_role: str) -> Callable:
    """
    FastAPI dependency factory: ensures the current user has at least
    `required_role` in the target project.

    Usage:
        @router.get("/{project_id}/tasks")
        async def list_tasks(
            project_id: str,
            user: dict = Depends(get_current_user),
            _: None = Depends(require_project_role("guest")),
        ):
            ...
    """

    async def _guard(project_id: str, user: dict = Depends(get_current_user), request: Request = None) -> None:
        db_path = request.app.state.db_path if request else None
        if db_path is None:
            raise HTTPException(status_code=500, detail=get_error("INTERNAL_ERROR"))
        role = get_project_role(db_path, project_id, user["user_id"])
        if not has_min_role(role, required_role):
            raise HTTPException(status_code=403, detail=get_error("ACCESS_DENIED"))

    return _guard


def require_any_project_role(*required_roles: str) -> Callable:
    """Dependency factory: check user has at least one of the required roles."""

    async def _guard(project_id: str, user: dict = Depends(get_current_user), request: Request = None) -> None:
        db_path = request.app.state.db_path if request else None
        if db_path is None:
            raise HTTPException(status_code=500, detail=get_error("INTERNAL_ERROR"))
        role = get_project_role(db_path, project_id, user["user_id"])
        for require in required_roles:
            if has_min_role(role, require):
                return
        raise HTTPException(status_code=403, detail=get_error("ACCESS_DENIED"))

    return _guard


def require_project_api_role(required_role: str) -> Callable:
    """Project-role guard for formerly unauthenticated core API routes.

    Production defaults to enforcement. The configuration bypass is deliberately
    explicit and is used only while legacy API tests are migrated.
    """
    async def _guard(
        project_id: str,
        request: Request,
        user: dict | None = Depends(get_project_api_user),
    ) -> None:
        if not request.app.state.settings.enforce_project_authorization:
            return
        assert user is not None
        role = get_project_role(request.app.state.db_path, project_id, user["user_id"])
        if not has_min_role(role, required_role):
            raise HTTPException(status_code=403, detail=get_error("ACCESS_DENIED"))
    return _guard


async def require_project_creation_permission(
    request: Request,
    user: dict | None = Depends(get_project_api_user),
) -> None:
    """Only configured system administrators may create projects in production.

    The explicit authorization bypass remains available for isolated legacy
    tests. Project creation is otherwise a tenant-level write operation, not a
    permission granted by membership in an existing project.
    """
    if not request.app.state.settings.enforce_project_authorization:
        return
    assert user is not None
    allowed = set(request.app.state.settings.system_admin_usernames)
    if user.get("username") not in allowed:
        raise HTTPException(status_code=403, detail=get_error("ACCESS_DENIED"))


async def require_system_admin(
    user: dict = Depends(get_current_user), request: Request = None
) -> None:
    """Allow production-management operations only for configured admins."""
    allowed = set(getattr(request.app.state.settings, "system_admin_usernames", []))
    if user.get("username") not in allowed:
        raise HTTPException(status_code=403, detail=get_error("ACCESS_DENIED"))
