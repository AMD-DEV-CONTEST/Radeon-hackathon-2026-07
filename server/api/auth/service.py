"""Auth business service layer."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from api.auth.repository import AuthRepository
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
from core.config import settings
from core.constants import TOKEN_TYPE_BEARER
from core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from models.enums import UserRole
from models.user import User
from core.exceptions import (
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)


class AuthService:
    def __init__(self, db: Session) -> None:
        self.repository = AuthRepository(db)

    def register(self, payload: UserRegisterRequest) -> AuthResponse:
        existing = self.repository.get_user_by_email(payload.email)
        if existing is not None:
            raise ConflictError("Email already registered")

        user = self.repository.create_user(
            email=payload.email,
            hashed_password=get_password_hash(payload.password),
            full_name=payload.full_name,
            role=UserRole.RECRUITER,
        )
        tokens = self._issue_token_pair(user)
        return AuthResponse(user=UserResponse.model_validate(user), tokens=tokens)

    def login(self, payload: UserLoginRequest) -> AuthResponse:
        user = self.repository.get_user_by_email(payload.email)
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedError(
                "Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise ForbiddenError("Inactive user")

        tokens = self._issue_token_pair(user)
        return AuthResponse(user=UserResponse.model_validate(user), tokens=tokens)

    def refresh(self, payload: RefreshTokenRequest) -> TokenResponse:
        token_payload = decode_refresh_token(payload.refresh_token)
        if token_payload is None:
            raise UnauthorizedError("Invalid refresh token")

        jti = token_payload.get("jti")
        subject = token_payload.get("sub")
        if not jti or not subject:
            raise UnauthorizedError("Invalid refresh token")

        stored = self.repository.get_refresh_token_by_jti(str(jti))
        if stored is None or stored.is_revoked:
            raise UnauthorizedError("Refresh token revoked or unknown")

        expires_at = stored.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            self.repository.revoke_refresh_token(stored)
            raise UnauthorizedError("Refresh token expired")

        if stored.token_hash != hash_token(payload.refresh_token):
            self.repository.revoke_refresh_token(stored)
            raise UnauthorizedError("Invalid refresh token")

        user = self.repository.get_user_by_id(stored.user_id)
        if user is None or not user.is_active or str(user.id) != str(subject):
            raise UnauthorizedError("Invalid refresh token")

        # Rotate refresh token
        self.repository.revoke_refresh_token(stored)
        return self._issue_token_pair(user)

    def logout(self, payload: LogoutRequest) -> MessageResponse:
        token_payload = decode_refresh_token(payload.refresh_token)
        if token_payload is None:
            # Idempotent logout
            return MessageResponse(message="Logged out")

        jti = token_payload.get("jti")
        if not jti:
            return MessageResponse(message="Logged out")

        stored = self.repository.get_refresh_token_by_jti(str(jti))
        if stored is not None and not stored.is_revoked:
            if stored.token_hash == hash_token(payload.refresh_token):
                self.repository.revoke_refresh_token(stored)

        return MessageResponse(message="Logged out")

    def get_me(self, user: User) -> UserResponse:
        return UserResponse.model_validate(user)

    def _issue_token_pair(self, user: User) -> TokenResponse:
        role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
        access_token = create_access_token(str(user.id), role=role)
        refresh_token, jti, expires_at = create_refresh_token(str(user.id), role=role)

        self.repository.create_refresh_token(
            user_id=user.id,
            jti=jti,
            token_hash=hash_token(refresh_token),
            expires_at=expires_at,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=TOKEN_TYPE_BEARER,
            expires_in=settings.access_token_expire_minutes * 60,
        )
