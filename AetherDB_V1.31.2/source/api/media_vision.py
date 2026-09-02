"""Authenticated local image embedding and retrieval API."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.dependencies.auth import get_current_user_role, require_admin
from services.audit_log import log_event
from services.db import get_db
from services.media_vision import (
    MediaVisionError,
    default_media_vision_index,
)


router = APIRouter(prefix="/api/media-vision", tags=["media-vision"])
ID_PATTERN = r"^[A-Za-z0-9:._-]{1,160}$"
Backend = Literal["auto", "rocm_pytorch", "cuda", "cpu"]
Lifecycle = Literal["temporary", "pending_review", "approved", "archived"]


class MediaVisionIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_backend: Backend = "auto"
    include_caption: bool = True


class MediaVisionBatchRequest(MediaVisionIndexRequest):
    asset_ids: list[
        Annotated[str, Field(min_length=1, max_length=160, pattern=ID_PATTERN)]
    ] = Field(min_length=1, max_length=100)
    continue_on_error: bool = True


class MediaVisionTextSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str = Field(min_length=1, max_length=100, pattern=ID_PATTERN)
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=20, ge=1, le=100)
    lifecycle_statuses: tuple[Lifecycle, ...] = ("approved", "archived")
    target_type: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=160)
    requested_backend: Backend = "auto"

    @model_validator(mode="after")
    def validate_target_filter(self):
        if bool(self.target_type) != bool(self.target_id):
            raise ValueError("target_type and target_id must be provided together")
        return self


class MediaVisionImageSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str = Field(min_length=1, max_length=100, pattern=ID_PATTERN)
    query_asset_id: str = Field(min_length=1, max_length=160, pattern=ID_PATTERN)
    top_k: int = Field(default=20, ge=1, le=100)
    lifecycle_statuses: tuple[Lifecycle, ...] = ("approved", "archived")
    target_type: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_target_filter(self):
        if bool(self.target_type) != bool(self.target_id):
            raise ValueError("target_type and target_id must be provided together")
        return self


class VisualSpaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=ID_PATTERN)
    requested_backend: Backend = "auto"


class VisualSpaceActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(min_length=1, max_length=100, pattern=ID_PATTERN)


class VisualSpaceGarbageCollectRequest(VisualSpaceActionRequest):
    confirm_space_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=ID_PATTERN,
    )


def _raise(error: MediaVisionError):
    from fastapi import HTTPException

    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.safe_message},
    )


def _audit(
    database_id: str,
    book_id: str,
    action: str,
    target: str,
    details: dict,
) -> None:
    conn = get_db(database_id)
    try:
        log_event(
            conn,
            action,
            f"Local media vision operation completed for {target}",
            details=json.dumps(details, ensure_ascii=True, sort_keys=True),
            target=target,
            database_id=database_id,
            book_id=book_id,
            success=True,
        )
    finally:
        conn.close()


@router.get("/status")
def media_vision_status(
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    book_id: str | None = Query(default=None, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        return default_media_vision_index(database_id).status(book_id=book_id)
    except MediaVisionError as error:
        _raise(error)


@router.get("/spaces")
def media_visual_spaces(
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        return default_media_vision_index(database_id).list_visual_spaces()
    except MediaVisionError as error:
        _raise(error)


@router.post("/spaces", status_code=202)
def create_media_visual_space(
    payload: VisualSpaceCreateRequest,
    _: None = Depends(require_admin),
):
    index = default_media_vision_index(payload.database_id)
    space = None
    try:
        space = index.create_visual_space()
        task = index.create_migration_task(
            space["space_id"],
            requested_backend=payload.requested_backend,
        )
        return {"space": space, "task": task}
    except MediaVisionError as error:
        if space is not None:
            index.mark_visual_space_failed(
                space["space_id"],
                "MIGRATION_TASK_CREATE_FAILED",
            )
        _raise(error)


@router.post("/spaces/rollback")
def rollback_media_visual_space(
    payload: VisualSpaceActionRequest,
    _: None = Depends(require_admin),
):
    try:
        return default_media_vision_index(
            payload.database_id
        ).rollback_visual_space()
    except MediaVisionError as error:
        _raise(error)


@router.post("/spaces/{space_id}/validate")
def validate_media_visual_space(
    space_id: str,
    payload: VisualSpaceActionRequest,
    _: None = Depends(require_admin),
):
    try:
        return default_media_vision_index(
            payload.database_id
        ).validate_visual_space(space_id)
    except MediaVisionError as error:
        _raise(error)


@router.post("/spaces/{space_id}/activate")
def activate_media_visual_space(
    space_id: str,
    payload: VisualSpaceActionRequest,
    _: None = Depends(require_admin),
):
    try:
        return default_media_vision_index(
            payload.database_id
        ).activate_visual_space(space_id)
    except MediaVisionError as error:
        _raise(error)


@router.post("/spaces/{space_id}/garbage-collect")
def garbage_collect_media_visual_space(
    space_id: str,
    payload: VisualSpaceGarbageCollectRequest,
    _: None = Depends(require_admin),
):
    try:
        return default_media_vision_index(
            payload.database_id
        ).garbage_collect_visual_space(
            space_id,
            confirm_space_id=payload.confirm_space_id,
        )
    except MediaVisionError as error:
        _raise(error)


@router.get("/migrations")
def list_media_visual_migrations(
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    role: str = Depends(get_current_user_role),
):
    try:
        return {
            "tasks": default_media_vision_index(
                database_id
            ).list_migration_tasks(status=status, limit=limit)
        }
    except MediaVisionError as error:
        _raise(error)


@router.get("/migrations/{task_id}")
def get_media_visual_migration(
    task_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        return default_media_vision_index(database_id).get_migration_task(task_id)
    except MediaVisionError as error:
        _raise(error)


@router.post("/migrations/{task_id}/cancel")
def cancel_media_visual_migration(
    task_id: str,
    payload: VisualSpaceActionRequest,
    _: None = Depends(require_admin),
):
    try:
        return default_media_vision_index(
            payload.database_id
        ).cancel_migration_task(task_id)
    except MediaVisionError as error:
        _raise(error)


@router.post("/migrations/{task_id}/retry", status_code=202)
def retry_media_visual_migration(
    task_id: str,
    payload: VisualSpaceActionRequest,
    _: None = Depends(require_admin),
):
    try:
        return default_media_vision_index(
            payload.database_id
        ).retry_migration_task(task_id)
    except MediaVisionError as error:
        _raise(error)


@router.post("/assets/{asset_id}/index")
def index_media_asset(
    asset_id: str,
    payload: MediaVisionIndexRequest,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        result = default_media_vision_index(database_id).index_asset(
            asset_id,
            requested_backend=payload.requested_backend,
            include_caption=payload.include_caption,
        )
        _audit(
            database_id,
            result["book_id"],
            "media_vision.index",
            asset_id,
            {
                "visual_indexed": result["visual"]["indexed"],
                "caption_indexed": result["caption"]["indexed"],
            },
        )
        return result
    except MediaVisionError as error:
        _raise(error)


@router.post("/index-batch")
def index_media_assets_batch(
    payload: MediaVisionBatchRequest,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    index = default_media_vision_index(database_id)
    results = []
    failed = 0
    seen = set()
    for asset_id in payload.asset_ids:
        if asset_id in seen:
            continue
        seen.add(asset_id)
        try:
            result = index.index_asset(
                asset_id,
                requested_backend=payload.requested_backend,
                include_caption=payload.include_caption,
            )
            results.append({"asset_id": asset_id, "status": "indexed", "result": result})
        except MediaVisionError as error:
            failed += 1
            results.append(
                {
                    "asset_id": asset_id,
                    "status": "failed",
                    "error": {"code": error.code, "message": error.safe_message},
                }
            )
            if not payload.continue_on_error:
                break
    digest = hashlib.sha256(
        "\0".join(sorted(seen)).encode("utf-8")
    ).hexdigest()
    _audit(
        database_id,
        "",
        "media_vision.index_batch",
        "media-assets",
        {
            "asset_count": len(seen),
            "failed_count": failed,
            "asset_id_set_digest": digest,
        },
    )
    return {
        "requested": len(seen),
        "indexed": sum(item["status"] == "indexed" for item in results),
        "failed": failed,
        "results": results,
    }


@router.delete("/assets/{asset_id}/index")
def remove_media_asset_index(
    asset_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        result = default_media_vision_index(database_id).remove_asset(asset_id)
        _audit(
            database_id,
            "",
            "media_vision.remove",
            asset_id,
            {"removed_vector_records": result["removed_vector_records"]},
        )
        return result
    except MediaVisionError as error:
        _raise(error)


@router.post("/search/text")
def search_media_by_text(
    payload: MediaVisionTextSearchRequest,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        return default_media_vision_index(database_id).search_text(
            book_id=payload.book_id,
            query=payload.query,
            top_k=payload.top_k,
            lifecycle_statuses=payload.lifecycle_statuses,
            target_type=payload.target_type,
            target_id=payload.target_id,
            requested_backend=payload.requested_backend,
        )
    except MediaVisionError as error:
        _raise(error)


@router.post("/search/image")
def search_media_by_image(
    payload: MediaVisionImageSearchRequest,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        return default_media_vision_index(database_id).search_image(
            book_id=payload.book_id,
            query_asset_id=payload.query_asset_id,
            top_k=payload.top_k,
            lifecycle_statuses=payload.lifecycle_statuses,
            target_type=payload.target_type,
            target_id=payload.target_id,
        )
    except MediaVisionError as error:
        _raise(error)
