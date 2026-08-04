"""
LaunchKart AI 2.0 — Product ORM Model
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProductModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Products table — items uploaded by sellers for AI analysis."""

    __tablename__ = "products"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    vision_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", index=True
    )

    # Relationships
    user = relationship("UserModel", back_populates="products")
    launches = relationship("LaunchModel", back_populates="product", lazy="selectin")
    marketplace_listings = relationship(
        "MarketplaceListingModel", back_populates="product", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name={self.name}, status={self.status})>"
