"""Models REST (M3.4 骨架)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.training import Model
from app.models.user import User
from app.services import training_service as svc

router = APIRouter()


@router.get("")
async def list_models(
    rescan: bool = Query(True),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if rescan:
        try:
            svc.scan_models(db)
        except Exception as e:
            return {"total": 0, "items": [], "rescan_error": str(e), "storage_root": str(svc.get_models_root())}
    rows = db.query(Model).order_by(Model.created_at.desc()).limit(200).all()
    return {"total": len(rows), "items": [svc.model_to_dict(r) for r in rows], "storage_root": str(svc.get_models_root())}


@router.get("/{model_id}")
async def get_model(
    model_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.query(Model).filter((Model.id == model_id) | (Model.model_key == model_id)).first()
    if not row:
        raise HTTPException(404, f"model '{model_id}' not found")
    return svc.model_to_dict(row)


@router.post("/scan")
async def scan(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    out = svc.scan_models(db)
    return {"scanned": len(out), "storage_root": str(svc.get_models_root())}
