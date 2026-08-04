"""
LaunchKart AI 2.0 — Auth API Routes

Endpoints for user registration, login, token refresh, and profile retrieval.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field

from app.dependencies import CurrentUserDep, DbSessionDep
from app.middleware.auth import TokenPair

router = APIRouter()


# ---- Request / Response Schemas ----


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    preferences: dict | None = None

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    user: UserResponse
    tokens: TokenPair


# ---- Endpoints ----


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(request: RegisterRequest, db: DbSessionDep) -> AuthResponse:
    """Register a new user account."""
    from app.services.auth_service import AuthService

    service = AuthService(db)
    return await service.register(
        email=request.email,
        password=request.password,
        full_name=request.full_name,
    )


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest, db: DbSessionDep) -> AuthResponse:
    """Authenticate and get JWT tokens."""
    from app.services.auth_service import AuthService

    service = AuthService(db)
    return await service.login(email=request.email, password=request.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(request: RefreshRequest, db: DbSessionDep) -> TokenPair:
    """Refresh an expired access token."""
    from app.services.auth_service import AuthService

    service = AuthService(db)
    return await service.refresh_token(request.refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUserDep, db: DbSessionDep) -> UserResponse:
    """Get the current authenticated user's profile."""
    from app.services.auth_service import AuthService

    service = AuthService(db)
    return await service.get_user_by_id(UUID(current_user.sub))
