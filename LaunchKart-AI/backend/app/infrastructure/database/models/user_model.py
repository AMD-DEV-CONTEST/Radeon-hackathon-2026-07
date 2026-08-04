"""
LaunchKart AI 2.0 — User ORM Model
"""

from __future__ import annotations

from sqlalchemy import String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Users table — sellers and admins."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="seller")
    preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    # Relationships
    products = relationship("ProductModel", back_populates="user", lazy="selectin")
    launches = relationship("LaunchModel", back_populates="user", lazy="selectin")
    memory_entries = relationship("MemoryEntryModel", back_populates="user", lazy="selectin")
    audit_logs = relationship("AuditLogModel", back_populates="user", lazy="selectin")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
