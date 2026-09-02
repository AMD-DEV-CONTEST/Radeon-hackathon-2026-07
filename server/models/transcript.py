"""Transcript ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from models.enums import TranscriptSpeaker

if TYPE_CHECKING:
    from models.interview import Interview
    from models.question import Question


class Transcript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transcripts"

    interview_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    question_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("questions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    speaker: Mapped[TranscriptSpeaker] = mapped_column(String(50), nullable=False)
    speaker_name: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    spoken_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    interview: Mapped[Interview] = relationship("Interview", back_populates="transcripts")
    question: Mapped[Question | None] = relationship("Question", back_populates="transcripts")

    def __repr__(self) -> str:
        return f"<Transcript id={self.id} speaker={self.speaker}>"
