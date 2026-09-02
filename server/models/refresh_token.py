"""Refresh token persistence for revocation and rotation."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from models.user import User


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (UniqueConstraint("jti", name="uq_refresh_tokens_jti"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="refresh_tokens")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def __repr__(self) -> str:
        return f"<RefreshToken id={self.id} user_id={self.user_id} revoked={self.is_revoked}>"
