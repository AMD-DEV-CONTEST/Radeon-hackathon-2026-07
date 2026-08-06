"""Datasets REST (M2).

磁盘为真, DB 为索引. 所有 GET 请求在进入前先做一次懒扫描, 不会漏掉 realtime
新落地的 episode. DELETE 只删 DB 记录 (不动磁盘), 手工清理 parquet 请用
`?purge=true` 附加参数.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.dataset import Dataset
from app.models.user import User
from app.services import dataset_service as svc
from app.services import hf_hub_service as hf_svc

router = APIRouter()


def _get_or_404(db: Session, dataset_id: str) -> Dataset:
    row = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if row is None:
        # 可能是刚录完但还没扫, 做一次定向 upsert. ``resolve_dataset_dir`` 兼顾
        # legacy ``recording_*`` 和 Step4 写在 HF cache 的 ``owner/name``。
        p = svc.resolve_dataset_dir(dataset_id)
        if p is not None:
            row = svc.upsert_from_dir(db, p)
    if row is None:
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    return row


@router.get("")
async def list_datasets(
    rescan: bool = Query(True, description="进入前做一次磁盘扫描"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if rescan:
        try:
            svc.scan_storage_root(db)
        except Exception as e:
            # 扫描失败不能让列表挂掉, 仅在 meta 里报出来
            return {
                "total": 0,
                "items": [],
                "rescan_error": str(e),
                "storage_root": str(svc.get_storage_root()),
            }

    q = db.query(Dataset)
    if user.role != "admin":
        q = q.filter(or_(Dataset.created_by.is_(None), Dataset.created_by == user.id))
    q = q.order_by(Dataset.created_at.desc())
    total = q.count()
    items = [svc.dataset_to_dict(r) for r in q.offset(offset).limit(limit).all()]
    return {
        "total": total,
        "items": items,
        "storage_root": str(svc.get_storage_root()),
    }


# NOTE: fixed paths (``/scan`` and ``/hf/status``) MUST be declared BEFORE
# any ``/{dataset_id:path}`` catch-all, otherwise FastAPI resolves them as
# ``dataset_id="scan"`` / ``"hf/status"`` and you get 404s.
@router.post("/scan")
async def scan_datasets(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    out = svc.scan_storage_root(db)
    return {"scanned": len(out), "storage_root": str(svc.get_storage_root())}


@router.get("/hf/status")
async def hf_hub_status(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Does the API have a working HF write token? UI uses this to show
    the push button as disabled when no token is configured."""
    return hf_svc.validate_token()


@router.get("/{dataset_id:path}/stats")
async def get_dataset_stats(
    dataset_id: str,
    recompute: bool = Query(False, description="忽略缓存, 重新读 parquet 算"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ds = _get_or_404(db, dataset_id)
    if recompute:
        refreshed = svc.upsert_from_dir(db, Path(ds.path))
        if refreshed:
            ds = refreshed
    return {
        "dataset_id": ds.dataset_id,
        "frame_count": ds.frame_count,
        "duration_s": ds.duration_s,
        "fps_nominal": ds.fps_nominal,
        "quality_score": ds.quality_score,
        "flags": ds.flags_json or [],
        "stats": ds.stats_json or {},
    }


@router.get("/{dataset_id:path}")
async def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ds = _get_or_404(db, dataset_id)
    return svc.dataset_to_dict(ds)


@router.delete("/{dataset_id:path}")
async def delete_dataset(
    dataset_id: str,
    purge: bool = Query(False, description="同时删除磁盘 parquet"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ds = _get_or_404(db, dataset_id)
    path = Path(ds.path) if ds.path else None
    db.delete(ds)
    db.commit()
    purged = False
    if purge and path and path.exists():
        try:
            shutil.rmtree(path)
            purged = True
        except Exception as e:
            return {"deleted": True, "purged": False, "error": str(e)}
    return {"deleted": True, "purged": purged}


class PushToHubRequest(BaseModel):
    repo_name: str | None = None
    owner: str | None = None
    private: bool = True


@router.post("/{dataset_id:path}/push_to_hub")
async def push_dataset_to_hub(
    dataset_id: str,
    body: PushToHubRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Push the local dataset dir up to HF Hub as a dataset repo.

    Synchronous in M9.5 — we block until the upload finishes. For any
    recording over ~2 GB this will time out the HTTP request; the service
    layer rejects those up front with a clear error. Async push lands in
    M9.6.

    On success we persist the resolved ``hf_repo_id`` into ``meta_json``
    so the Training page can auto-suggest it later.
    """
    ds = _get_or_404(db, dataset_id)
    local_path = ds.path
    if not local_path or not Path(local_path).is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"dataset path missing on disk: {local_path}",
        )

    result = hf_svc.push_local_dataset(
        local_path=local_path,
        dataset_id=ds.dataset_id,
        repo_name=body.repo_name,
        owner=body.owner,
        private=body.private,
    )

    if result.get("ok"):
        # Persist hf_repo_id into meta_json so the training page can pick it
        # up as a dropdown suggestion and the wizard Step 5 can pre-fill it.
        meta = dict(ds.meta_json or {})
        meta["hf_repo_id"] = result["repo_id"]
        meta["hf_url"] = result["url"]
        meta["hf_private"] = result.get("private", True)
        ds.meta_json = meta
        db.add(ds)
        db.commit()

    return result


@router.post("/{dataset_id:path}/convert")
async def convert_dataset(
    dataset_id: str,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """`json -> lerobot` 转换 (M2 预留, 目前 realtime 停止录制时已自动做过).

    返回 parquet 路径. 未来用于重新切分 / 重算 fps 等场景.
    """
    raise HTTPException(
        status_code=501,
        detail="convert 暂未实现 (realtime 停止录制时已自动产出 parquet). 占位端点.",
    )
