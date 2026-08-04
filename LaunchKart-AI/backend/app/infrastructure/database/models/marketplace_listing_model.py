"""
LaunchKart AI 2.0 — Marketplace Listing ORM Model
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MarketplaceListingModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Marketplace listings table — generated listings for each marketplace."""

    __tablename__ = "marketplace_listings"

    launch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("launches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    marketplace: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bullet_points: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    keywords: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    pricing: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    images: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    compliance_check: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    export_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exported_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", index=True
    )

    # Relationships
    launch = relationship("LaunchModel", back_populates="marketplace_listing_records")
    product = relationship("ProductModel", back_populates="marketplace_listings")

    def __repr__(self) -> str:
        return f"<MarketplaceListing(id={self.id}, marketplace={self.marketplace}, status={self.status})>"
