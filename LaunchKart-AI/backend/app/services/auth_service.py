"""
LaunchKart AI 2.0 — Auth Service

Business logic for user registration, authentication, and token management.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import AuthResponse, UserResponse
from app.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.infrastructure.database.models.user_model import UserModel
from app.middleware.auth import (
    TokenPair,
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)


class AuthService:
    """Handles user authentication and token management."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def register(self, email: str, password: str, full_name: str) -> AuthResponse:
        """Register a new user and return tokens."""
        # Check for existing user
        existing = await self._db.execute(
            select(UserModel).where(UserModel.email == email)
        )
        if existing.scalar_one_or_none():
            raise ConflictError(f"User with email '{email}' already exists")

        user = UserModel(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role="seller",
        )
        self._db.add(user)
        await self._db.flush()

        tokens = create_token_pair(user.id, user.email, user.role)

        return AuthResponse(
            user=UserResponse.model_validate(user),
            tokens=tokens,
        )

    async def login(self, email: str, password: str) -> AuthResponse:
        """Authenticate a user and return tokens."""
        result = await self._db.execute(
            select(UserModel).where(UserModel.email == email)
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid email or password")

        tokens = create_token_pair(user.id, user.email, user.role)

        return AuthResponse(
            user=UserResponse.model_validate(user),
            tokens=tokens,
        )

    async def refresh_token(self, refresh_token: str) -> TokenPair:
        """Generate new tokens from a valid refresh token."""
        payload = decode_token(refresh_token, expected_type="refresh")

        result = await self._db.execute(
            select(UserModel).where(UserModel.id == UUID(payload.sub))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError("User")

        return create_token_pair(user.id, user.email, user.role)

    async def get_user_by_id(self, user_id: UUID) -> UserResponse:
        """Get user profile by ID."""
        result = await self._db.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError("User", str(user_id))

        return UserResponse.model_validate(user)
