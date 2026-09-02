"""Evaluation ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from models.interview import Interview


class Evaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluations"

    interview_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    competency_scores: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    metrics: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    pulse_data: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)

    interview: Mapped[Interview] = relationship("Interview", back_populates="evaluation")

    def __repr__(self) -> str:
        return f"<Evaluation id={self.id} interview_id={self.interview_id}>"
