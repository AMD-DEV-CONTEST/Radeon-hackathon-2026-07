"""Question ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from models.enums import DifficultyLevel, QuestionStatus

if TYPE_CHECKING:
    from models.interview import Interview
    from models.transcript import Transcript


class Question(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "questions"

    interview_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[DifficultyLevel | None] = mapped_column(String(20), nullable=True)
    priority: Mapped[DifficultyLevel | None] = mapped_column(String(20), nullable=True)
    status: Mapped[QuestionStatus] = mapped_column(
        String(50),
        default=QuestionStatus.PENDING,
        server_default=QuestionStatus.PENDING.value,
        nullable=False,
    )

    interview: Mapped[Interview] = relationship("Interview", back_populates="questions")
    transcripts: Mapped[list[Transcript]] = relationship(
        "Transcript",
        back_populates="question",
    )

    def __repr__(self) -> str:
        return f"<Question id={self.id} number={self.number}>"
