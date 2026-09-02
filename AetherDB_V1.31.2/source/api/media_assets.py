"""Authenticated unified media asset API."""
from __future__ import annotations

import json
import re
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dependencies.auth import require_capability
from services.audit_log import log_event
from services.db import get_db
from services.media_assets import (
    MediaAssetError,
    add_media_annotation,
    cleanup_media_assets,
    create_media_binding,
    delete_media_binding,
    get_media_asset,
    get_media_content,
    import_media_asset,
    list_effective_chapter_media,
    list_media_assets,
    review_media_annotation,
    soft_delete_media_asset,
    transition_media_asset,
    update_media_asset,
)


router = APIRouter(prefix="/api/media-assets", tags=["media-assets"])
ID_PATTERN = r"^[A-Za-z0-9:._-]{1,160}$"
require_media_read = require_capability("read_content")
require_media_management = require_capability("manage_media")


class MediaAssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_filename: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, Any] | None = None


class MediaBindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str = Field(min_length=1, max_length=100, pattern=ID_PATTERN)
    target_type: Literal[
        "database",
        "book",
        "content_group",
        "chapter",
        "entity",
        "entity_state_segment",
        "event",
        "relation",
        "timeline",
        "temporal_anchor",
        "branch",
    ]
    target_id: str = Field(min_length=1, max_length=160)
    language_code: str | None = Field(
        default=None,
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$",
    )
    binding_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{1,63}$")
    timeline_id: str | None = Field(default=None, max_length=160, pattern=ID_PATTERN)
    branch_id: str | None = Field(default=None, max_length=160, pattern=ID_PATTERN)
    valid_from_anchor_id: str | None = Field(default=None, max_length=160, pattern=ID_PATTERN)
    valid_to_anchor_id: str | None = Field(default=None, max_length=160, pattern=ID_PATTERN)
    entity_state_segment_id: str | None = Field(default=None, max_length=160, pattern=ID_PATTERN)
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)
    notes: str = Field(default="", max_length=2000)


class MediaAnnotationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    version_id: str | None = Field(default=None, max_length=160, pattern=ID_PATTERN)
    annotation_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{1,63}$")
    payload: dict[str, Any]
    source_type: Literal["manual", "model", "imported"] = "manual"
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    model_profile_id: str | None = Field(default=None, max_length=160)
    source_task_id: str | None = Field(default=None, max_length=160, pattern=ID_PATTERN)
    language_code: str = Field(
        default="und",
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$",
    )

    @field_validator("approval_status")
    @classmethod
    def model_annotations_start_pending(cls, value, info):
        if info.data.get("source_type") == "model" and value == "approved":
            raise ValueError("model annotations require explicit later approval")
        return value


class MediaAnnotationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool


def _raise(error: MediaAssetError):
    from fastapi import HTTPException

    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


def _audit(database_id: str, book_id: str, event: str, asset_id: str, details: dict | None = None):
    conn = get_db(database_id)
    try:
        log_event(
            conn,
            event,
            f"Media asset operation completed for {asset_id}",
            details=json.dumps(details or {}, ensure_ascii=True),
            target=asset_id,
            database_id=database_id,
            book_id=book_id,
            success=True,
        )
    finally:
        conn.close()


@router.post("", status_code=201)
def upload_media_asset(
    database_id: str = Form(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    book_id: str = Form(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    source_type: Literal["imported", "generated", "captured", "derived"] = Form("imported"),
    created_by_task_id: str | None = Form(default=None, max_length=160, pattern=ID_PATTERN),
    file: UploadFile = File(...),
    _=Depends(require_media_management),
):
    try:
        asset = import_media_asset(
            database_id,
            book_id,
            file.file,
            filename=file.filename or "media",
            declared_mime=file.content_type,
            source_type=source_type,
            created_by_task_id=created_by_task_id,
        )
        _audit(database_id, book_id, "media_asset.import", asset["asset_id"], {"modality": asset["modality"]})
        return {"asset": asset}
    except MediaAssetError as error:
        _raise(error)
    finally:
        file.file.close()


@router.get("")
def api_list_media_assets(
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    book_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    modality: Literal["image", "audio", "video"] | None = None,
    lifecycle_status: Literal[
        "temporary", "pending_review", "approved", "archived", "soft_deleted", "rejected"
    ]
    | None = None,
    target_type: str | None = Query(default=None, max_length=64),
    target_id: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _=Depends(require_media_read),
):
    try:
        return list_media_assets(
            database_id,
            book_id=book_id,
            modality=modality,
            lifecycle_status=lifecycle_status,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
            offset=offset,
        )
    except MediaAssetError as error:
        _raise(error)


@router.get("/effective")
def api_list_effective_chapter_media(
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    book_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    chapter_id: str = Query(..., min_length=1, max_length=160),
    language_code: str | None = Query(
        default=None,
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$",
    ),
    modality: Literal["image", "audio", "video"] | None = None,
    lifecycle_status: Literal[
        "temporary", "pending_review", "approved", "archived", "soft_deleted", "rejected"
    ]
    | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _=Depends(require_media_read),
):
    try:
        return list_effective_chapter_media(
            database_id,
            book_id=book_id,
            chapter_id=chapter_id,
            language_code=language_code,
            modality=modality,
            lifecycle_status=lifecycle_status,
            limit=limit,
            offset=offset,
        )
    except MediaAssetError as error:
        _raise(error)


@router.get("/{asset_id}")
def api_get_media_asset(
    asset_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_read),
):
    try:
        return {"asset": get_media_asset(database_id, asset_id)}
    except MediaAssetError as error:
        _raise(error)


@router.patch("/{asset_id}")
def api_update_media_asset(
    asset_id: str,
    payload: MediaAssetUpdate,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    try:
        asset = update_media_asset(
            database_id,
            asset_id,
            original_filename=payload.original_filename,
            metadata=payload.metadata,
        )
        _audit(database_id, asset["book_id"], "media_asset.update", asset_id)
        return {"asset": asset}
    except MediaAssetError as error:
        _raise(error)


def _transition_response(
    asset_id: str,
    action: Literal["submit", "approve", "reject", "archive"],
    database_id: str,
):
    try:
        asset = transition_media_asset(database_id, asset_id, action)
        _audit(database_id, asset["book_id"], f"media_asset.{action}", asset_id)
        return {"asset": asset}
    except MediaAssetError as error:
        _raise(error)


@router.post("/{asset_id}/submit")
def api_submit_media_asset(
    asset_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    return _transition_response(asset_id, "submit", database_id)


@router.post("/{asset_id}/approve")
def api_approve_media_asset(
    asset_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    return _transition_response(asset_id, "approve", database_id)


@router.post("/{asset_id}/reject")
def api_reject_media_asset(
    asset_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    return _transition_response(asset_id, "reject", database_id)


@router.post("/{asset_id}/archive")
def api_archive_media_asset(
    asset_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    return _transition_response(asset_id, "archive", database_id)


@router.post("/{asset_id}/bindings", status_code=201)
def api_create_media_binding(
    asset_id: str,
    payload: MediaBindingCreate,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    try:
        binding = create_media_binding(database_id, asset_id, payload.model_dump())
        _audit(
            database_id,
            payload.book_id,
            "media_asset.bind",
            asset_id,
            {"binding_id": binding["binding_id"], "target_type": binding["target_type"]},
        )
        return {"binding": binding}
    except MediaAssetError as error:
        _raise(error)


@router.delete("/{asset_id}/bindings/{binding_id}", status_code=204)
def api_delete_media_binding(
    asset_id: str,
    binding_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    try:
        asset = get_media_asset(database_id, asset_id, include_related=False)
        delete_media_binding(database_id, asset_id, binding_id)
        _audit(database_id, asset["book_id"], "media_asset.unbind", asset_id, {"binding_id": binding_id})
    except MediaAssetError as error:
        _raise(error)


@router.post("/{asset_id}/annotations", status_code=201)
def api_add_media_annotation(
    asset_id: str,
    payload: MediaAnnotationCreate,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    try:
        annotation = add_media_annotation(database_id, asset_id, payload.model_dump())
        _audit(database_id, annotation["book_id"], "media_asset.annotate", asset_id)
        return {"annotation": annotation}
    except MediaAssetError as error:
        _raise(error)


@router.post("/{asset_id}/annotations/{annotation_id}/review")
def api_review_media_annotation(
    asset_id: str,
    annotation_id: str,
    payload: MediaAnnotationReview,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    try:
        annotation = review_media_annotation(
            database_id,
            asset_id,
            annotation_id,
            approved=payload.approved,
        )
        _audit(
            database_id,
            annotation["book_id"],
            "media_asset.annotation_review",
            asset_id,
            {
                "annotation_id": annotation_id,
                "approved": payload.approved,
            },
        )
        return {"annotation": annotation}
    except MediaAssetError as error:
        _raise(error)


@router.delete("/{asset_id}")
def api_soft_delete_media_asset(
    asset_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    _=Depends(require_media_management),
):
    try:
        asset = soft_delete_media_asset(database_id, asset_id)
        _audit(database_id, asset["book_id"], "media_asset.delete", asset_id)
        return {"asset": asset}
    except MediaAssetError as error:
        _raise(error)


def _parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or "," in value:
        raise MediaAssetError("INVALID_RANGE", "Only one valid byte range is supported.", 416)
    start_raw, end_raw = match.groups()
    if not start_raw:
        length = int(end_raw or 0)
        if length <= 0:
            raise MediaAssetError("INVALID_RANGE", "Invalid byte range.", 416)
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
    if start >= size or end < start:
        raise MediaAssetError("INVALID_RANGE", "Requested byte range is unavailable.", 416)
    return start, min(end, size - 1)


def _file_chunks(path, start: int, end: int):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/{asset_id}/content")
def api_get_media_content(
    asset_id: str,
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    range_header: str | None = Header(default=None, alias="Range"),
    _=Depends(require_media_read),
):
    try:
        path, asset = get_media_content(database_id, asset_id)
        size = asset["file_size_bytes"]
        requested = _parse_range(range_header, size)
        start, end = requested or (0, size - 1)
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
            "Content-Length": str(end - start + 1),
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(asset['original_filename'])}",
            "ETag": f"\"sha256-{asset['content_hash']}\"",
            "X-Content-Type-Options": "nosniff",
        }
        if requested:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(
            _file_chunks(path, start, end),
            status_code=206 if requested else 200,
            media_type=asset["mime_type"],
            headers=headers,
        )
    except MediaAssetError as error:
        _raise(error)


@router.post("/maintenance/cleanup")
def api_cleanup_media_assets(
    database_id: str = Query(..., min_length=1, max_length=100, pattern=ID_PATTERN),
    retention_days: int = Query(default=7, ge=1, le=3650),
    _=Depends(require_media_management),
):
    try:
        result = cleanup_media_assets(database_id, retention_days=retention_days)
        _audit(
            database_id,
            "",
            "media_asset.cleanup",
            "media-assets",
            {"removed_assets": result["removed_assets"], "removed_objects": result["removed_objects"]},
        )
        return result
    except MediaAssetError as error:
        _raise(error)
