"""AgentLog ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from models.enums import AgentLogStatus

if TYPE_CHECKING:
    from models.interview import Interview


class AgentLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_logs"

    interview_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    agent: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AgentLogStatus] = mapped_column(
        String(50),
        default=AgentLogStatus.PENDING,
        server_default=AgentLogStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    interview: Mapped[Interview | None] = relationship("Interview", back_populates="agent_logs")

    def __repr__(self) -> str:
        return f"<AgentLog id={self.id} agent={self.agent!r} status={self.status}>"
