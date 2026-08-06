"""Platform statistics endpoint (M7.1).

Aggregates real counts from the database so the Dashboard can show live numbers
instead of hardcoded mock values.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.dataset import Dataset
from app.models.training import Model, TrainingJob
from app.models.user import User

router = APIRouter()


@router.get("")
async def get_stats(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    dataset_count = db.query(func.count(Dataset.id)).scalar() or 0
    total_frames = db.query(func.coalesce(func.sum(Dataset.frame_count), 0)).scalar() or 0

    model_count = db.query(func.count(Model.id)).scalar() or 0

    training_total = db.query(func.count(TrainingJob.id)).scalar() or 0
    training_running = (
        db.query(func.count(TrainingJob.id))
        .filter(TrainingJob.status.in_(["queued", "running"]))
        .scalar()
        or 0
    )
    training_succeeded = (
        db.query(func.count(TrainingJob.id))
        .filter(TrainingJob.status == "succeeded")
        .scalar()
        or 0
    )

    skill_ids = (
        db.query(Dataset.skill_id)
        .filter(Dataset.skill_id.isnot(None))
        .distinct()
        .all()
    )
    unique_skills = len(skill_ids)

    return {
        "datasets": {
            "total": dataset_count,
            "total_frames": int(total_frames),
        },
        "models": {
            "total": model_count,
        },
        "training_jobs": {
            "total": training_total,
            "running": training_running,
            "succeeded": training_succeeded,
        },
        "skills": {
            "unique": unique_skills,
        },
    }
