"""Auth API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from api.common.schema import MessageResponse
from api.auth.schema import (
    AuthResponse,
    LogoutRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from api.auth.service import AuthService
from api.auth.deps import CurrentUser, RecruiterUser
from db.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    return AuthService(db)


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: UserRegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    return service.register(payload)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: UserLoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    return service.login(payload)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshTokenRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return service.refresh(payload)


@router.post("/logout", response_model=MessageResponse)
def logout(
    payload: LogoutRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    return service.logout(payload)


@router.get("/me", response_model=UserResponse)
def me(
    current_user: CurrentUser,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Protected route returning the authenticated user."""
    return service.get_me(current_user)


@router.get("/protected", response_model=MessageResponse)
def protected_example(current_user: RecruiterUser) -> MessageResponse:
    """Example role-protected route for recruiters and admins."""
    return MessageResponse(
        message=f"Hello {current_user.full_name}, role={current_user.role}",
    )
