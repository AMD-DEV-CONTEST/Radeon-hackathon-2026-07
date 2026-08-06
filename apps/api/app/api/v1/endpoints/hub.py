"""AI Hub REST endpoints (M7.2).

Proxies HuggingFace API through our backend so the frontend doesn't need
CORS workarounds or direct HF SDK access. Also handles dataset publishing.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.dataset import Dataset
from app.models.user import User
from app.services import hf_hub_service as hf_svc
from app.services import dataset_service as ds_svc

logger = logging.getLogger(__name__)
router = APIRouter()

_hf_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hf-hub")
HF_TIMEOUT = 10  # seconds


@router.get("/models")
async def list_hub_models(
    query: str = Query("", description="Search query"),
    tag: str = Query("robotics", description="HF tag filter"),
    sort: str = Query("downloads", description="Sort: downloads | likes | lastModified"),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        models = await asyncio.wait_for(
            loop.run_in_executor(
                _hf_executor,
                lambda: hf_svc.search_models(query=query, tag=tag, sort=sort, limit=limit),
            ),
            timeout=HF_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("HF search_models timed out after %ss, returning fallback", HF_TIMEOUT)
        models = hf_svc.FALLBACK_MODELS[:limit]
    return {"total": len(models), "items": models}


@router.get("/models/{repo_id:path}")
async def get_hub_model(
    repo_id: str,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        info = await asyncio.wait_for(
            loop.run_in_executor(
                _hf_executor,
                lambda: hf_svc.get_model_info(repo_id),
            ),
            timeout=HF_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("HF get_model_info timed out for %s", repo_id)
        raise HTTPException(504, f"HuggingFace API timed out for '{repo_id}'")
    if info is None:
        raise HTTPException(404, f"model '{repo_id}' not found on HuggingFace")
    return info


class PublishDatasetRequest(BaseModel):
    dataset_id: str = Field(min_length=1)
    hf_repo_id: str = Field(min_length=3, description="e.g. 'username/my-dataset'")
    hf_token: str | None = Field(None, description="HF write token (optional if env is set)")


@router.post("/datasets/publish")
async def publish_dataset_to_hf(
    req: PublishDatasetRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ds = db.query(Dataset).filter(Dataset.dataset_id == req.dataset_id).first()
    if not ds:
        raise HTTPException(404, f"dataset '{req.dataset_id}' not found")

    result = hf_svc.upload_dataset(
        local_path=ds.path,
        repo_id=req.hf_repo_id,
        token=req.hf_token,
    )

    if not result.get("success"):
        raise HTTPException(502, result.get("error", "upload failed"))

    return {
        "success": True,
        "url": result["url"],
        "dataset_id": req.dataset_id,
        "hf_repo_id": req.hf_repo_id,
    }
