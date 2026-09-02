"""Interview ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from models.enums import InterviewStatus

if TYPE_CHECKING:
    from models.agent_log import AgentLog
    from models.candidate import Candidate
    from models.evaluation import Evaluation
    from models.question import Question
    from models.report import Report
    from models.resume import Resume
    from models.transcript import Transcript
    from models.user import User


class Interview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "interviews"

    candidate_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    resume_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("resumes.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[InterviewStatus] = mapped_column(
        String(50),
        default=InterviewStatus.SCHEDULED,
        server_default=InterviewStatus.SCHEDULED.value,
        nullable=False,
        index=True,
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    complexity: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidate: Mapped[Candidate] = relationship("Candidate", back_populates="interviews")
    user: Mapped[User] = relationship("User", back_populates="interviews")
    resume: Mapped[Resume | None] = relationship("Resume", back_populates="interviews")
    questions: Mapped[list[Question]] = relationship(
        "Question",
        back_populates="interview",
        cascade="all, delete-orphan",
        order_by="Question.number",
    )
    transcripts: Mapped[list[Transcript]] = relationship(
        "Transcript",
        back_populates="interview",
        cascade="all, delete-orphan",
        order_by="Transcript.sequence",
    )
    evaluation: Mapped[Evaluation | None] = relationship(
        "Evaluation",
        back_populates="interview",
        cascade="all, delete-orphan",
        uselist=False,
    )
    report: Mapped[Report | None] = relationship(
        "Report",
        back_populates="interview",
        cascade="all, delete-orphan",
        uselist=False,
    )
    agent_logs: Mapped[list[AgentLog]] = relationship(
        "AgentLog",
        back_populates="interview",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Interview id={self.id} role={self.role!r} status={self.status}>"
