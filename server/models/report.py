"""Report ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from models.enums import Recommendation

if TYPE_CHECKING:
    from models.interview import Interview


class Report(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    interview_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[Recommendation | None] = mapped_column(String(50), nullable=True)
    performance_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    executive_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    competency_matrix: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    pulse_series: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    export_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    interview: Mapped[Interview] = relationship("Interview", back_populates="report")

    def __repr__(self) -> str:
        return f"<Report id={self.id} interview_id={self.interview_id}>"
