"""Authenticated durable image-generation task API."""

from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.dependencies.auth import get_current_user_role
from services.audit_log import log_event
from services.db import get_db
from services.media_generation import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    MediaGenerationError,
    cancel_media_generation_task,
    create_media_generation_task,
    get_media_generation_status,
    get_media_generation_task,
    list_media_generation_events,
    list_media_generation_tasks,
    retry_media_generation_task,
)
from services.media_assets import (
    MediaAssetError,
    create_media_binding,
    get_media_asset,
    transition_media_asset,
)


router = APIRouter(prefix="/api/media-generation", tags=["media-generation"])
ID_PATTERN = r"^[A-Za-z0-9:._-]{1,160}$"


class ImageGenerationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(default=768, ge=256, le=1024, multiple_of=64)
    height: int = Field(default=768, ge=256, le=1024, multiple_of=64)
    steps: int = Field(default=30, ge=1, le=100)
    guidance_scale: float = Field(default=4.0, ge=1, le=20)
    strength: float = Field(default=0.3, ge=0.05, le=1)


class MediaGenerationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    database_id: str = Field(min_length=1, max_length=100, pattern=ID_PATTERN)
    book_id: str = Field(min_length=1, max_length=100, pattern=ID_PATTERN)
    operation: Literal[
        "image.generate",
        "image.img2img",
        "image.enhance",
    ] = "image.generate"
    prompt: str = Field(min_length=1, max_length=6000)
    negative_prompt: str = Field(default="", max_length=3000)
    parameters: ImageGenerationParameters = Field(
        default_factory=ImageGenerationParameters
    )
    seed: int | None = Field(default=None, ge=0, le=9_223_372_036_854_775_807)
    source_asset_id: str | None = Field(default=None, pattern=ID_PATTERN)
    model_profile_id: str | None = Field(default=None, pattern=ID_PATTERN)
    package_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$",
    )
    session_id: str | None = Field(default=None, max_length=128, pattern=ID_PATTERN)
    requested_backend: Literal["auto", "rocm_pytorch", "cuda"] = "auto"
    allow_cloud_upload: bool = False

    @model_validator(mode="after")
    def validate_source_and_target(self):
        if self.operation == "image.generate" and self.source_asset_id:
            raise ValueError("text-to-image generation does not accept source_asset_id")
        if self.operation != "image.generate" and not self.source_asset_id:
            raise ValueError("image-to-image operations require source_asset_id")
        if self.model_profile_id and self.package_id:
            raise ValueError("choose one execution target")
        return self


class MediaGenerationPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str = Field(min_length=1, max_length=100, pattern=ID_PATTERN)
    target_type: Literal["content_group", "chapter"] = "content_group"
    target_id: str = Field(min_length=1, max_length=160)
    binding_type: str = Field(
        default="chapter_illustration",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
    )
    language_code: str | None = Field(
        default=None,
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$",
    )
    notes: str = Field(default="", max_length=2000)


def _raise(error: MediaGenerationError):
    raise HTTPException(
        status_code=error.status_code,
        detail={
            "code": error.code,
            "message": error.safe_message,
            **error.details,
        },
    ) from error


def _raise_media(error: MediaAssetError):
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error


def _audit(
    database_id: str,
    book_id: str,
    event_type: str,
    task_id: str,
    details: dict | None = None,
):
    conn = get_db(database_id)
    try:
        log_event(
            conn,
            event_type,
            f"Media generation operation completed for {task_id}",
            details=json.dumps(details or {}, ensure_ascii=True, sort_keys=True),
            target=task_id,
            database_id=database_id,
            book_id=book_id,
            success=True,
        )
    finally:
        conn.close()


@router.get("/status")
def api_media_generation_status(
    role: str = Depends(get_current_user_role),
):
    return get_media_generation_status()


@router.post("/tasks", status_code=202)
def api_create_media_generation_task(
    payload: MediaGenerationCreate,
    role: str = Depends(get_current_user_role),
):
    try:
        task = create_media_generation_task(payload.model_dump())
    except MediaGenerationError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "media_generation.create",
        task["task_id"],
        {
            "operation": task["operation"],
            "target_kind": task["target_kind"],
            "package_id": task["package_id"],
            "model_profile_id": task["model_profile_id"],
        },
    )
    return {"task": task}


@router.get("/tasks")
def api_list_media_generation_tasks(
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    book_id: str | None = Query(default=None, max_length=100, pattern=ID_PATTERN),
    status: Literal[
        "queued",
        "running",
        "cancelling",
        "completed",
        "failed",
        "cancelled",
    ]
    | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    role: str = Depends(get_current_user_role),
):
    try:
        return list_media_generation_tasks(
            database_id,
            book_id=book_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    except MediaGenerationError as error:
        _raise(error)


@router.get("/tasks/{task_id}")
def api_get_media_generation_task(
    task_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        return {"task": get_media_generation_task(database_id, task_id)}
    except MediaGenerationError as error:
        _raise(error)


@router.post("/tasks/{task_id}/publish")
def api_publish_media_generation_task(
    task_id: str,
    payload: MediaGenerationPublish,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        task = get_media_generation_task(database_id, task_id)
    except MediaGenerationError as error:
        _raise(error)
    asset_id = task.get("output_asset_id")
    if task["status"] != "completed" or not asset_id:
        raise HTTPException(
            409,
            detail={
                "code": "MEDIA_GENERATION_OUTPUT_NOT_READY",
                "message": "The image generation task has no completed output to publish",
            },
        )
    if payload.book_id != task["book_id"]:
        raise HTTPException(
            409,
            detail={
                "code": "MEDIA_GENERATION_SCOPE_MISMATCH",
                "message": "The publication target is outside the task book scope",
            },
        )
    try:
        asset = get_media_asset(database_id, asset_id, include_related=False)
        if asset["lifecycle_status"] != "approved":
            asset = transition_media_asset(database_id, asset_id, "approve")
        binding = None
        binding_reused = False
        try:
            binding = create_media_binding(
                database_id,
                asset_id,
                {
                    "book_id": payload.book_id,
                    "target_type": payload.target_type,
                    "target_id": payload.target_id,
                    "language_code": payload.language_code,
                    "binding_type": payload.binding_type,
                    "notes": payload.notes,
                },
            )
        except MediaAssetError as error:
            if error.code != "BINDING_EXISTS":
                raise
            binding_reused = True
    except MediaAssetError as error:
        _raise_media(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "media_generation.publish",
        task_id,
        {
            "asset_id": asset_id,
            "target_type": payload.target_type,
            "target_id": payload.target_id,
            "binding_reused": binding_reused,
        },
    )
    return {
        "task": get_media_generation_task(database_id, task_id),
        "asset": asset,
        "binding": binding,
        "binding_reused": binding_reused,
    }


@router.get("/tasks/{task_id}/events")
def api_list_media_generation_events(
    task_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    after_sequence: int = Query(default=-1, ge=-1),
    limit: int = Query(default=100, ge=1, le=500),
    role: str = Depends(get_current_user_role),
):
    try:
        return {
            "events": list_media_generation_events(
                database_id,
                task_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        }
    except MediaGenerationError as error:
        _raise(error)


def _stream_task(database_id: str, task_id: str):
    next_sequence = 0
    while True:
        try:
            events = list_media_generation_events(
                database_id,
                task_id,
                after_sequence=next_sequence - 1,
                limit=100,
            )
            for event in events:
                next_sequence = event["sequence"] + 1
                yield json.dumps(
                    event,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ) + "\n"
            task = get_media_generation_task(
                database_id,
                task_id,
                include_prompt=False,
            )
        except MediaGenerationError as error:
            yield json.dumps(
                {
                    "protocol_version": "1.0",
                    "sequence": next_sequence,
                    "event": "error",
                    "task_id": task_id,
                    "data": {
                        "status": "failed",
                        "code": error.code,
                        "message": error.safe_message,
                    },
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ) + "\n"
            return
        if task["status"] in TERMINAL_STATUSES and not events:
            return
        time.sleep(0.25)


def _stream_response(database_id: str, task_id: str):
    try:
        get_media_generation_task(database_id, task_id, include_prompt=False)
    except MediaGenerationError as error:
        _raise(error)
    return StreamingResponse(
        _stream_task(database_id, task_id),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/tasks/{task_id}/stream")
def api_stream_media_generation_task(
    task_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    return _stream_response(database_id, task_id)


@router.post("/tasks/{task_id}/stream")
def api_stream_media_generation_task_post(
    task_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    return _stream_response(database_id, task_id)


@router.post("/tasks/{task_id}/cancel")
def api_cancel_media_generation_task(
    task_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        task = cancel_media_generation_task(database_id, task_id)
    except MediaGenerationError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "media_generation.cancel",
        task_id,
        {"status": task["status"]},
    )
    return {"task": task}


@router.post("/tasks/{task_id}/retry", status_code=202)
def api_retry_media_generation_task(
    task_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    role: str = Depends(get_current_user_role),
):
    try:
        task = retry_media_generation_task(database_id, task_id)
    except MediaGenerationError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "media_generation.retry",
        task["task_id"],
        {"retry_of": task_id},
    )
    return {"task": task}
