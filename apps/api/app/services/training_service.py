"""训练任务 service (M3).

- 路径推导: models/ 和 training_logs/ 默认放在 apps/realtime/ 下, 与 datasets/ 并排.
- CRUD + dict 化 + checkpoint 扫描 (M3.4).
- 启动 worker 的逻辑在 M3.2 worker.py 单独实现, 这里只给数据层.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.training import Model, TrainingJob


# -------- 路径推导 --------


def _fallback_root(kind: str) -> Path:
    # apps/api/app/services/training_service.py -> apps/api -> apps -> apps/realtime/<kind>
    here = Path(__file__).resolve()
    return here.parents[3] / "realtime" / kind


def get_models_root() -> Path:
    raw = settings.MODELS_STORAGE_ROOT
    p = Path(raw).expanduser().resolve() if raw else _fallback_root("models")
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_logs_root() -> Path:
    raw = settings.TRAINING_LOGS_ROOT
    p = Path(raw).expanduser().resolve() if raw else _fallback_root("training_logs")
    p.mkdir(parents=True, exist_ok=True)
    return p


# -------- 序列化 --------


def job_to_dict(j: TrainingJob) -> dict[str, Any]:
    return {
        "id": str(j.id),
        "dataset_id": j.dataset_id,
        "algo": j.algo,
        "hparams": j.hparams_json or {},
        "status": j.status,
        "progress_pct": j.progress_pct,
        "epoch": j.epoch,
        "total_epochs": j.total_epochs,
        "loss": j.loss,
        "pid": j.pid,
        "log_path": j.log_path,
        "error_msg": j.error_msg,
        "model_id": str(j.model_id) if j.model_id else None,
        "skill_id": j.skill_id or "so101_generic_teleop",
        "train_backend": j.train_backend or "local",
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }


def model_to_dict(m: Model) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "model_key": m.model_key,
        "name": m.name,
        "algo": m.algo,
        "dataset_id": m.dataset_id,
        "checkpoint_path": m.checkpoint_path,
        "size_bytes": m.size_bytes,
        "metrics": m.metrics_json or {},
        "hparams": m.hparams_json or {},
        "input_dim": m.input_dim,
        "output_dim": m.output_dim,
        "status": m.status,
        "skill_id": m.skill_id or "so101_generic_teleop",
        "robot_type": m.robot_type or "so101",
        "hf_model_id": m.hf_model_id,
        "compatible_skills": [m.skill_id or "so101_generic_teleop"],
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# -------- Model registry 扫描 (M3.4 骨架, 现在先给空实现) --------


def scan_models(db: Session) -> list[Model]:
    """扫 models/ 目录, 把 model.json 对齐到 DB.

    model.json 由 worker 训练完写, 格式:
      {
        "model_key": "model_20260418_xxxxx",
        "algo": "mlp_baseline",
        "dataset_id": "recording_20260418_xxxxx",
        "checkpoint": "checkpoint.pt",
        "metrics": {...},
        "hparams": {...},
        "input_dim": 6, "output_dim": 6
      }
    """
    import json

    root = get_models_root()
    out: list[Model] = []
    for d in sorted(root.iterdir() if root.exists() else [], key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        meta_path = d / "model.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        key = meta.get("model_key") or d.name
        ckpt_rel = meta.get("checkpoint", "checkpoint.pt")
        ckpt_path = d / ckpt_rel
        if not ckpt_path.exists():
            continue

        existing = db.query(Model).filter(Model.model_key == key).first()
        if existing:
            existing.checkpoint_path = str(ckpt_path)
            existing.size_bytes = ckpt_path.stat().st_size
            existing.metrics_json = meta.get("metrics") or {}
            existing.hparams_json = meta.get("hparams") or {}
            existing.algo = meta.get("algo") or existing.algo
            existing.dataset_id = meta.get("dataset_id") or existing.dataset_id
            existing.input_dim = meta.get("input_dim") or existing.input_dim
            existing.output_dim = meta.get("output_dim") or existing.output_dim
            db.commit()
            db.refresh(existing)
            out.append(existing)
        else:
            row = Model(
                model_key=key,
                name=meta.get("name") or key,
                algo=meta.get("algo") or "unknown",
                dataset_id=meta.get("dataset_id"),
                checkpoint_path=str(ckpt_path),
                size_bytes=ckpt_path.stat().st_size,
                metrics_json=meta.get("metrics") or {},
                hparams_json=meta.get("hparams") or {},
                input_dim=meta.get("input_dim"),
                output_dim=meta.get("output_dim"),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            out.append(row)
    return out


# -------- Stale job reconciliation (quota / UX) --------

_TERMINAL_QUALIA = frozenset(
    {"succeeded", "success", "completed", "done", "failed", "cancelled", "error", "canceled"}
)
_QUALIA_SUCCESS = frozenset({"succeeded", "success", "completed", "done"})


def _apply_qualia_upstream(row: TrainingJob, upstream: str, live: dict[str, Any]) -> bool:
    """Sync DB row from Qualia status string. Returns True if row changed."""
    hp = dict(row.hparams_json or {})
    u = (upstream or "").lower()
    if u in _QUALIA_SUCCESS and row.status not in ("succeeded",):
        row.status = "succeeded"
        if live.get("output_model_id"):
            hp["output_model_id"] = live["output_model_id"]
        row.hparams_json = hp
        row.error_msg = None
        return True
    if u in ("failed", "cancelled", "error", "canceled") and row.status not in (
        "failed",
        "cancelled",
    ):
        row.status = "cancelled" if u in ("cancelled", "canceled") else "failed"
        row.error_msg = live.get("error") or f"Qualia job {u}"
        return True
    return False


def reconcile_user_training_jobs(db: Session, user_id) -> dict[str, Any]:
    """Refresh queued/running jobs so concurrent quota reflects reality.

    - Poll Qualia for cloud jobs (completed/failed on Hub but still ``running`` in DB).
    - Close zombie local ``queued``/``running`` rows (worker never started / dead).
    """
    from datetime import datetime, timedelta

    from app.services import qualia_service as qualia_svc

    now = datetime.utcnow()
    rows = (
        db.query(TrainingJob)
        .filter(
            TrainingJob.created_by == user_id,
            TrainingJob.status.in_(("queued", "running")),
        )
        .order_by(TrainingJob.created_at.asc())
        .all()
    )
    updated = 0
    active_after = 0

    for row in rows:
        changed = False
        created = row.created_at.replace(tzinfo=None) if row.created_at else now
        age = now - created

        if row.train_backend == "qualia":
            qid = (row.hparams_json or {}).get("qualia_job_id")
            if not qid:
                if age > timedelta(hours=1):
                    row.status = "failed"
                    row.error_msg = "云端任务未成功创建，已自动关闭。"
                    changed = True
            elif qualia_svc.is_configured():
                live = qualia_svc.get_training_status(str(qid))
                upstream = (live.get("status") or "").lower()
                if upstream in _TERMINAL_QUALIA:
                    changed = _apply_qualia_upstream(row, upstream, live)
                elif upstream in ("unknown", "error") and live.get("error"):
                    if age > timedelta(days=2):
                        row.status = "failed"
                        row.error_msg = "云端状态无法同步，已释放训练名额。"
                        changed = True
            else:
                if age > timedelta(days=7):
                    row.status = "failed"
                    row.error_msg = "任务过久未更新，已自动关闭。"
                    changed = True
        else:
            if row.status == "queued" and age > timedelta(hours=2):
                row.status = "failed"
                row.error_msg = "本地任务超时未启动，已自动关闭。"
                changed = True
            elif row.status == "running" and not row.pid and age > timedelta(hours=6):
                row.status = "failed"
                row.error_msg = "本地训练进程已结束或丢失，已自动关闭。"
                changed = True

        if changed:
            updated += 1

    if updated:
        db.commit()

    active_after = (
        db.query(TrainingJob)
        .filter(
            TrainingJob.created_by == user_id,
            TrainingJob.status.in_(("queued", "running")),
        )
        .count()
    )
    return {"updated": updated, "active": active_after}
