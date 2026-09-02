"""Auth data access layer."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.enums import UserRole
from models.refresh_token import RefreshToken
from models.user import User


class AuthRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_user_by_id(self, user_id: UUID) -> User | None:
        return self.db.get(User, user_id)

    def get_user_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        return self.db.scalar(statement)

    def create_user(
        self,
        *,
        email: str,
        hashed_password: str,
        full_name: str,
        role: UserRole,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            role=role,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def create_refresh_token(
        self,
        *,
        user_id: UUID,
        jti: str,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        refresh_token = RefreshToken(
            user_id=user_id,
            jti=jti,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(refresh_token)
        self.db.commit()
        self.db.refresh(refresh_token)
        return refresh_token

    def get_refresh_token_by_jti(self, jti: str) -> RefreshToken | None:
        statement = select(RefreshToken).where(RefreshToken.jti == jti)
        return self.db.scalar(statement)

    def revoke_refresh_token(self, refresh_token: RefreshToken) -> RefreshToken:
        if refresh_token.revoked_at is None:
            refresh_token.revoked_at = datetime.now(UTC)
            self.db.add(refresh_token)
            self.db.commit()
            self.db.refresh(refresh_token)
        return refresh_token

    def revoke_all_user_refresh_tokens(self, user_id: UUID) -> int:
        statement = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        tokens = list(self.db.scalars(statement))
        now = datetime.now(UTC)
        for token in tokens:
            token.revoked_at = now
            self.db.add(token)
        self.db.commit()
        return len(tokens)
