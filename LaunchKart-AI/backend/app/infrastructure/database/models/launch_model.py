"""
LaunchKart AI 2.0 — Launch ORM Model
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LaunchModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Launches table — tracks the end-to-end product launch process."""

    __tablename__ = "launches"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", index=True
    )
    execution_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    agent_results: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    seo_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    pricing_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    marketing_content: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    marketplace_listings: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # Relationships
    product = relationship("ProductModel", back_populates="launches")
    user = relationship("UserModel", back_populates="launches")
    agent_tasks = relationship(
        "AgentTaskModel", back_populates="launch", lazy="selectin", order_by="AgentTaskModel.created_at"
    )
    marketplace_listing_records = relationship(
        "MarketplaceListingModel", back_populates="launch", lazy="selectin"
    )
    gpu_benchmarks = relationship(
        "GPUBenchmarkModel", back_populates="launch", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Launch(id={self.id}, status={self.status}, progress={self.progress_percent}%)>"
