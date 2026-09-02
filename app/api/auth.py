"""
Phase H.1 — 认证 API (Auth)

提供用户登录、获取当前用户信息和用户列表。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.observability.error_codes import get_error
from app.schemas.models import LoginRequest, TokenResponse, UserProfile
from app.schemas.phase_h_sql import seed_phase_h_tables
from app.security.auth import AuthService
from app.security.permissions import get_current_user, set_auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_auth_svc(request: Request) -> AuthService:
    return request.app.state.auth_service


# ---------------------------------------------------------------------------
# Ensure Phase H tables are seeded on startup (called from main.py)
# ---------------------------------------------------------------------------


def setup_auth(db_path: str) -> AuthService:
    """Create tables, seed demo users, and return the AuthService singleton."""
    seed_phase_h_tables(db_path)
    svc = AuthService(db_path)
    set_auth_service(svc)
    return svc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    """Authenticate with username and password.

    Returns a Bearer token valid for 24 hours.
    """
    svc: AuthService = request.app.state.auth_service
    result = svc.authenticate(body.username, body.password)
    if result is None:
        raise HTTPException(status_code=401, detail=get_error("AUTH_INVALID_CREDENTIALS"))
    result["is_system_admin"] = result["username"] in set(
        request.app.state.settings.system_admin_usernames
    )
    return result


@router.get("/me", response_model=UserProfile)
async def me(request: Request, user: dict = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return {
        **user,
        "is_system_admin": user["username"] in set(
            request.app.state.settings.system_admin_usernames
        ),
    }


@router.get("/users", response_model=list[UserProfile])
async def list_users(request: Request, _: dict = Depends(get_current_user)):
    """List all active users in the system."""
    svc: AuthService = request.app.state.auth_service
    return svc.list_users()
