"""
LaunchKart AI 2.0 — GPU Benchmark ORM Model
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, UUIDPrimaryKeyMixin


class GPUBenchmarkModel(Base, UUIDPrimaryKeyMixin):
    """GPU benchmark records — AMD Radeon GPU performance metrics per launch."""

    __tablename__ = "gpu_benchmarks"

    launch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("launches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    gpu_name: Mapped[str] = mapped_column(String(255), nullable=False)
    driver_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rocm_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vram_total_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    vram_used_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpu_utilization_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    inference_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_per_second: Mapped[float | None] = mapped_column(Float, nullable=True)
    parallel_tasks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_benchmarks: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    launch = relationship("LaunchModel", back_populates="gpu_benchmarks")

    def __repr__(self) -> str:
        return f"<GPUBenchmark(id={self.id}, gpu={self.gpu_name}, tps={self.tokens_per_second})>"
