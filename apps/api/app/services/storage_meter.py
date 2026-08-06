"""Recompute per-user dataset storage usage (Phase 2)."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset import Dataset
from app.models.user import User
from app.services.entitlement_service import METRIC_STORAGE_BYTES, set_storage_usage


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
    return total


def refresh_user_storage(db: Session, user_id) -> int:
    """Sum on-disk size for datasets owned by user (admin/platform rows skipped)."""
    rows = db.query(Dataset).filter(Dataset.created_by == user_id).all()
    total = 0
    for ds in rows:
        if ds.path:
            total += _dir_size(Path(ds.path))
    set_storage_usage(db, user_id, total)
    return total


def refresh_all_users(db: Session) -> dict[str, int]:
    users = db.query(User).all()
    out: dict[str, int] = {}
    for u in users:
        out[str(u.id)] = refresh_user_storage(db, u.id)
    return out


def default_storage_root() -> Path:
    return Path(getattr(settings, "DATASETS_STORAGE_ROOT", "apps/realtime/datasets"))
