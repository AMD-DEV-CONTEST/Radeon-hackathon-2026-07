"""Candidate ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from models.enums import Recommendation

if TYPE_CHECKING:
    from models.interview import Interview
    from models.resume import Resume
    from models.user import User


class Candidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "candidates"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    years_of_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skills: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[Recommendation | None] = mapped_column(
        String(50),
        nullable=True,
    )

    user: Mapped[User] = relationship("User", back_populates="candidates")
    resumes: Mapped[list[Resume]] = relationship(
        "Resume",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    interviews: Mapped[list[Interview]] = relationship(
        "Interview",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} email={self.email!r}>"
