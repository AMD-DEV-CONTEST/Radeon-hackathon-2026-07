"""Skill marketplace listings (Phase 3)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, Integer, String, TIMESTAMP, Text

from app.models.database import Base, UUIDType


class SkillListing(Base):
    __tablename__ = "skill_listings"

    id = Column(UUIDType, primary_key=True)
    skill_id = Column(String(128), nullable=False, index=True)
    seller_id = Column(UUIDType, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    price_cents = Column(Integer, default=0, nullable=False)
    currency = Column(String(8), default="CNY", nullable=False)
    license_type = Column(String(32), default="personal", nullable=False)  # personal | commercial
    revenue_share_bps = Column(Integer, default=3000, nullable=False)  # 30% platform
    status = Column(String(32), default="pending", nullable=False)  # pending | approved | rejected
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
