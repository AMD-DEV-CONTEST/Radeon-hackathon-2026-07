"""Monthly usage counters for subscription quotas."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, String, TIMESTAMP, UniqueConstraint

from app.models.database import Base, UUIDType


class UsageCounter(Base):
    __tablename__ = "usage_counters"
    __table_args__ = (
        UniqueConstraint("user_id", "metric", "period", name="uq_usage_user_metric_period"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUIDType, nullable=False, index=True)
    metric = Column(String(64), nullable=False)
    period = Column(String(7), nullable=False)  # YYYY-MM
    value = Column(Integer, default=0, nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
