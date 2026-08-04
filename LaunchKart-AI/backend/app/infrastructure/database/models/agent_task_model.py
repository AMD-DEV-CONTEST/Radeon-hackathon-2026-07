"""
LaunchKart AI 2.0 — Agent Task ORM Model
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, UUIDPrimaryKeyMixin


class AgentTaskModel(Base, UUIDPrimaryKeyMixin):
    """Agent tasks table — individual agent execution records within a launch."""

    __tablename__ = "agent_tasks"

    launch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("launches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued", index=True
    )
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    reasoning_trace: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    tokens_used: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    launch = relationship("LaunchModel", back_populates="agent_tasks")

    def __repr__(self) -> str:
        return f"<AgentTask(id={self.id}, agent={self.agent_name}, status={self.status})>"
