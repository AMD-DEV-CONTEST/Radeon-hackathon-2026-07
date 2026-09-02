"""Resume ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from models.enums import ResumeStatus

if TYPE_CHECKING:
    from models.candidate import Candidate
    from models.interview import Interview


class Resume(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resumes"

    candidate_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ResumeStatus] = mapped_column(
        String(50),
        default=ResumeStatus.UPLOADED,
        server_default=ResumeStatus.UPLOADED.value,
        nullable=False,
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    candidate: Mapped[Candidate] = relationship("Candidate", back_populates="resumes")
    interviews: Mapped[list[Interview]] = relationship(
        "Interview",
        back_populates="resume",
    )

    def __repr__(self) -> str:
        return f"<Resume id={self.id} file_name={self.file_name!r}>"
