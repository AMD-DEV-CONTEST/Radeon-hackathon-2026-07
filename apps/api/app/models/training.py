"""TrainingJob + Model 模型 (M3).

两张表, 生命周期:

  POST /trainings  -> TrainingJob(status=queued) -> worker 拉起 subprocess
                       \-> status=running, progress_pct
                       \-> status=succeeded + 写 Model(checkpoint_path, metrics)
                       \                       \-> or status=failed + error_msg
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from app.models.database import Base, UUIDType


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id = Column(UUIDType, primary_key=True, default=_uuid.uuid4)
    dataset_id = Column(String(128), index=True, nullable=False)

    # M6: skill-first — which skill is this training for?
    skill_id = Column(String(128), nullable=True, index=True)
    train_backend = Column(String(16), nullable=False, default="local")

    algo = Column(String(32), nullable=False, default="mlp_baseline")
    hparams_json = Column(JSON, nullable=True)

    status = Column(String(16), nullable=False, default="queued", index=True)
    progress_pct = Column(Float, nullable=False, default=0.0)
    epoch = Column(Integer, nullable=False, default=0)
    total_epochs = Column(Integer, nullable=False, default=0)
    loss = Column(Float, nullable=True)

    pid = Column(Integer, nullable=True)
    log_path = Column(Text, nullable=True)
    error_msg = Column(Text, nullable=True)

    # 产出指针 (完成后写)
    model_id = Column(UUIDType, ForeignKey("models.id"), nullable=True)

    created_by = Column(UUIDType, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TrainingJob {self.id} {self.status} {self.algo}>"


class Model(Base):
    __tablename__ = "models"

    id = Column(UUIDType, primary_key=True, default=_uuid.uuid4)
    # 业务 id (目录名) e.g. model_20260418_xxxxx
    model_key = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)

    algo = Column(String(32), nullable=False)
    dataset_id = Column(String(128), index=True, nullable=True)

    # M6: skill-first — what skill does this model perform?
    skill_id = Column(String(128), nullable=True, index=True)
    robot_type = Column(String(64), nullable=True, default="so101")
    hf_model_id = Column(String(256), nullable=True)

    checkpoint_path = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)

    # 训练指标 {"train_loss": [...], "val_loss": [...], "final_rmse": ..., "epochs": N}
    metrics_json = Column(JSON, nullable=True)
    hparams_json = Column(JSON, nullable=True)

    input_dim = Column(Integer, nullable=True)
    output_dim = Column(Integer, nullable=True)

    status = Column(String(16), nullable=False, default="ok")
    error_msg = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Model {self.model_key} {self.algo}>"
