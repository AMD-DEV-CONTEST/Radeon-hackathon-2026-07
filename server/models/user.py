"""User ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from models.enums import UserRole

if TYPE_CHECKING:
    from models.candidate import Candidate
    from models.interview import Interview
    from models.refresh_token import RefreshToken


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(50),
        default=UserRole.RECRUITER,
        server_default=UserRole.RECRUITER.value,
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    candidates: Mapped[list[Candidate]] = relationship(
        "Candidate",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    interviews: Mapped[list[Interview]] = relationship(
        "Interview",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
