"""
LaunchKart AI 2.0 — Memory Entry ORM Model
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, UUIDPrimaryKeyMixin


class MemoryEntryModel(Base, UUIDPrimaryKeyMixin):
    """Memory entries table — persistent agent and user memory backed by ChromaDB vectors."""

    __tablename__ = "memory_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memory_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    namespace: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True, default=None
    )
    embedding_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # Relationships
    user = relationship("UserModel", back_populates="memory_entries")

    def __repr__(self) -> str:
        return f"<MemoryEntry(id={self.id}, type={self.memory_type}, namespace={self.namespace})>"
