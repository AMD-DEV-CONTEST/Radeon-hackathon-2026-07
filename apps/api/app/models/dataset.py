"""Dataset 元数据表 (M2).

存储所有已登记的数据集. parquet 本身住在文件系统 (apps/realtime/datasets/ 或
外部 upload 目录), 这里只保存元信息 + 计算出来的统计/评分.

- source: "realtime_record" | "upload" | "import"
- status: "ok" | "error" | "pending"
- quality_score: 0-100 (综合评分, M2.3)
- stats_json: 所有统计量 (关节范围、时长、fps 稳定性等)
- flags_json: 质量告警 ["fps_unstable", "low_frame_count", "jitter"] 等
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, JSON

from app.models.database import Base, UUIDType


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(UUIDType, primary_key=True, default=_uuid.uuid4)

    # 业务 id — 目录名, 对齐 apps/realtime 输出 (e.g. "recording_20260418_080554")
    dataset_id = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)

    # 物理位置 (绝对路径或相对 storage_root)
    path = Column(Text, nullable=False)

    source = Column(String(32), nullable=False, default="realtime_record")
    robot_id = Column(String(64), nullable=True)

    # M6: skill-first architecture — what behavior was this dataset teaching?
    skill_id = Column(String(128), nullable=True, index=True)
    robot_type = Column(String(64), nullable=True, default="so101")

    frame_count = Column(Integer, nullable=False, default=0)
    duration_s = Column(Float, nullable=False, default=0.0)
    fps_nominal = Column(Float, nullable=True)

    # 核心 stats — 关节范围、fps 稳定性、jitter 等
    stats_json = Column(JSON, nullable=True)
    flags_json = Column(JSON, nullable=True)

    quality_score = Column(Integer, nullable=True)

    status = Column(String(16), nullable=False, default="ok")

    # 自由 meta (原始 botclaw.json 内容等)
    meta_json = Column(JSON, nullable=True)

    # 关联用户 (可选)
    created_by = Column(UUIDType, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Dataset {self.dataset_id} frames={self.frame_count} q={self.quality_score}>"
