"""External billing subscription records (Phase 3)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, String, TIMESTAMP

from app.models.database import Base, UUIDType


class SubscriptionRecord(Base):
    __tablename__ = "subscription_records"

    id = Column(UUIDType, primary_key=True)
    user_id = Column(UUIDType, nullable=False, index=True)
    provider = Column(String(32), nullable=False)  # stripe | alipay | manual
    external_id = Column(String(128), nullable=True, index=True)
    tier = Column(String(32), nullable=False)
    status = Column(String(32), default="active", nullable=False)
    current_period_start = Column(TIMESTAMP(timezone=True), nullable=True)
    current_period_end = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
