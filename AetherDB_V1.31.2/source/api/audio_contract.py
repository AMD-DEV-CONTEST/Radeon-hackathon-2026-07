"""Authenticated model-neutral audio contract API."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.dependencies.auth import get_current_user_role
from services.audio_contract import (
    AudioContractError,
    cancel_audio_task,
    create_audio_task,
    create_pronunciation_entry,
    create_voice_profile,
    delete_pronunciation_entry,
    get_audio_asset_contract,
    get_audio_contract_status,
    get_audio_task,
    get_audio_waveform,
    get_voice_profile,
    list_audio_task_events,
    list_audio_tasks,
    list_pronunciation_entries,
    list_voice_profiles,
    register_audio_output,
    register_audio_result,
    retry_failed_audio_task,
    review_audio_result,
    update_pronunciation_entry,
    update_voice_profile,
)
from services.audit_log import log_event
from services.db import get_db
from services.media_assets import (
    MediaAssetError,
    create_media_binding,
    get_media_asset,
    transition_media_asset,
)


router = APIRouter(prefix="/api/audio", tags=["audio-contract"])
ID_PATTERN = r"^[A-Za-z0-9:._-]{1,160}$"


class VoiceProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    database_id: str = Field(pattern=ID_PATTERN, max_length=100)
    book_id: str = Field(pattern=ID_PATTERN, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    locale: str = Field(default="und", min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    voice_kind: Literal["provider_voice", "local_reference", "native_voice"]
    model_profile_id: str | None = Field(default=None, pattern=ID_PATTERN)
    provider_voice_name: str | None = Field(default=None, min_length=1, max_length=256)
    reference_asset_id: str | None = Field(default=None, pattern=ID_PATTERN)
    package_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$",
    )
    package_voice_name: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,127}$",
    )
    consent_confirmed: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    locale: str | None = Field(
        default=None,
        min_length=2,
        max_length=40,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class AudioTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    database_id: str = Field(pattern=ID_PATTERN, max_length=100)
    book_id: str = Field(pattern=ID_PATTERN, max_length=100)
    operation: Literal[
        "audio.tts.chapter",
        "audio.tts.segment",
        "audio.asr.transcribe",
        "audio.preview",
        "audio.enhance",
        "audio.merge",
    ]
    chapter_id: str | None = Field(default=None, pattern=ID_PATTERN)
    source_text: str | None = Field(default=None, max_length=1_500_000)
    source_revision: str | None = Field(default=None, max_length=256)
    source_asset_ids: list[str] = Field(default_factory=list, max_length=64)
    voice_profile_id: str | None = Field(default=None, pattern=ID_PATTERN)
    model_profile_id: str | None = Field(default=None, pattern=ID_PATTERN)
    package_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,95}$",
    )
    requested_backend: Literal["auto", "cpu", "rocm_pytorch", "cuda"] = "auto"
    execution_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_targets(self):
        if self.model_profile_id and self.package_id:
            raise ValueError("choose one execution target")
        if len(self.source_asset_ids) != len(set(self.source_asset_ids)):
            raise ValueError("source_asset_ids must be unique")
        return self


class AudioOutputCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(pattern=ID_PATTERN)
    segment_id: str | None = Field(default=None, pattern=ID_PATTERN)
    output_kind: Literal["segment", "preview", "final", "merged", "enhanced"]


class AudioResultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str | None = Field(default=None, pattern=ID_PATTERN)
    result_type: Literal["transcript", "metadata"] = "transcript"
    content_text: str = Field(min_length=1, max_length=1_500_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AudioResultReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool


class AudioTaskPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_type: str = Field(
        default="chapter_narration",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
    )
    notes: str = Field(default="", max_length=2000)


class PronunciationEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_id: str = Field(pattern=ID_PATTERN, max_length=100)
    book_id: str = Field(pattern=ID_PATTERN, max_length=100)
    locale: str = Field(default="und", min_length=2, max_length=40)
    term: str = Field(min_length=1, max_length=160)
    pronunciation: str = Field(min_length=1, max_length=512)
    entry_kind: Literal["replacement", "kokoro_phoneme"] = "replacement"
    enabled: bool = True


class PronunciationEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str | None = Field(default=None, min_length=2, max_length=40)
    term: str | None = Field(default=None, min_length=1, max_length=160)
    pronunciation: str | None = Field(default=None, min_length=1, max_length=512)
    entry_kind: Literal["replacement", "kokoro_phoneme"] | None = None
    enabled: bool | None = None


def _raise(error: AudioContractError):
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.safe_message},
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
    target: str,
    details: dict | None = None,
):
    conn = get_db(database_id)
    try:
        log_event(
            conn,
            event_type,
            f"Audio contract operation completed for {target}",
            details=json.dumps(details or {}, ensure_ascii=True, sort_keys=True),
            target=target,
            database_id=database_id,
            book_id=book_id,
            success=True,
        )
    finally:
        conn.close()


@router.get("/status")
def api_audio_contract_status(
    role: str = Depends(get_current_user_role),
):
    return get_audio_contract_status()


@router.post("/voice-profiles", status_code=201)
def api_create_voice_profile(
    payload: VoiceProfileCreate,
    role: str = Depends(get_current_user_role),
):
    try:
        profile = create_voice_profile(payload.model_dump())
    except AudioContractError as error:
        _raise(error)
    _audit(
        profile["database_id"],
        profile["book_id"],
        "audio.voice_profile.create",
        profile["voice_profile_id"],
        {"voice_kind": profile["voice_kind"]},
    )
    return {"voice_profile": profile}


@router.get("/voice-profiles")
def api_list_voice_profiles(
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    book_id: str | None = Query(default=None, pattern=ID_PATTERN, max_length=100),
    enabled: bool | None = None,
    role: str = Depends(get_current_user_role),
):
    try:
        return {
            "voice_profiles": list_voice_profiles(
                database_id,
                book_id=book_id,
                enabled=enabled,
            )
        }
    except AudioContractError as error:
        _raise(error)


@router.get("/voice-profiles/{voice_profile_id}")
def api_get_voice_profile(
    voice_profile_id: str,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        return {"voice_profile": get_voice_profile(database_id, voice_profile_id)}
    except AudioContractError as error:
        _raise(error)


@router.patch("/voice-profiles/{voice_profile_id}")
def api_update_voice_profile(
    voice_profile_id: str,
    payload: VoiceProfileUpdate,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        profile = update_voice_profile(
            database_id,
            voice_profile_id,
            payload.model_dump(exclude_unset=True),
        )
    except AudioContractError as error:
        _raise(error)
    _audit(
        profile["database_id"],
        profile["book_id"],
        "audio.voice_profile.update",
        profile["voice_profile_id"],
        {"fields": sorted(payload.model_fields_set)},
    )
    return {"voice_profile": profile}


@router.post("/pronunciations", status_code=201)
def api_create_pronunciation_entry(
    payload: PronunciationEntryCreate,
    role: str = Depends(get_current_user_role),
):
    try:
        entry = create_pronunciation_entry(payload.model_dump())
    except AudioContractError as error:
        _raise(error)
    _audit(
        entry["database_id"],
        entry["book_id"],
        "audio.pronunciation.create",
        entry["entry_id"],
        {"locale": entry["locale"], "entry_kind": entry["entry_kind"]},
    )
    return {"entry": entry}


@router.get("/pronunciations")
def api_list_pronunciation_entries(
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    book_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    locale: str | None = Query(default=None, min_length=2, max_length=40),
    enabled: bool | None = None,
    role: str = Depends(get_current_user_role),
):
    try:
        entries = list_pronunciation_entries(
            database_id,
            book_id=book_id,
            locale=locale,
            enabled=enabled,
        )
    except AudioContractError as error:
        _raise(error)
    return {"entries": entries}


@router.patch("/pronunciations/{entry_id}")
def api_update_pronunciation_entry(
    entry_id: str,
    payload: PronunciationEntryUpdate,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        entry = update_pronunciation_entry(
            database_id,
            entry_id,
            payload.model_dump(exclude_unset=True),
        )
    except AudioContractError as error:
        _raise(error)
    _audit(
        entry["database_id"],
        entry["book_id"],
        "audio.pronunciation.update",
        entry_id,
        {"fields": sorted(payload.model_fields_set)},
    )
    return {"entry": entry}


@router.delete("/pronunciations/{entry_id}")
def api_delete_pronunciation_entry(
    entry_id: str,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        result = delete_pronunciation_entry(database_id, entry_id)
    except AudioContractError as error:
        _raise(error)
    _audit(
        database_id,
        result["book_id"],
        "audio.pronunciation.delete",
        entry_id,
    )
    return result


@router.get("/assets/{asset_id}")
def api_get_audio_asset(
    asset_id: str,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        return get_audio_asset_contract(database_id, asset_id)
    except AudioContractError as error:
        _raise(error)


@router.get("/assets/{asset_id}/waveform")
def api_get_audio_waveform(
    asset_id: str,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    points: int = Query(default=512, ge=32, le=4096),
    role: str = Depends(get_current_user_role),
):
    try:
        return {"waveform": get_audio_waveform(database_id, asset_id, points=points)}
    except AudioContractError as error:
        _raise(error)


@router.post("/tasks", status_code=201)
def api_create_audio_task(
    payload: AudioTaskCreate,
    role: str = Depends(get_current_user_role),
):
    try:
        task = create_audio_task(payload.model_dump())
    except AudioContractError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "audio.task.create",
        task["task_id"],
        {
            "operation": task["operation"],
            "target_kind": task["target_kind"],
            "model_profile_id": task["model_profile_id"],
            "package_id": task["package_id"],
        },
    )
    return {"task": task}


@router.get("/tasks")
def api_list_audio_tasks(
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    book_id: str | None = Query(default=None, pattern=ID_PATTERN, max_length=100),
    chapter_id: str | None = Query(default=None, pattern=ID_PATTERN),
    status: Literal[
        "planned",
        "in_progress",
        "pending_review",
        "completed",
        "cancelled",
        "failed",
        "outdated",
    ]
    | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    role: str = Depends(get_current_user_role),
):
    try:
        return list_audio_tasks(
            database_id,
            book_id=book_id,
            chapter_id=chapter_id,
            status=status,
            limit=limit,
            offset=offset,
        )
    except AudioContractError as error:
        _raise(error)


@router.get("/tasks/{task_id}")
def api_get_audio_task(
    task_id: str,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    include_source_text: bool = False,
    include_result_text: bool = False,
    role: str = Depends(get_current_user_role),
):
    try:
        return {
            "task": get_audio_task(
                database_id,
                task_id,
                include_source_text=include_source_text,
                include_result_text=include_result_text,
            )
        }
    except AudioContractError as error:
        _raise(error)


@router.get("/tasks/{task_id}/events")
def api_list_audio_task_events(
    task_id: str,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2_000),
    role: str = Depends(get_current_user_role),
):
    try:
        events = list_audio_task_events(
            database_id,
            task_id,
            after_sequence=after_sequence,
            limit=limit,
        )
    except AudioContractError as error:
        _raise(error)
    return {"events": events}


@router.post("/tasks/{task_id}/cancel")
def api_cancel_audio_task(
    task_id: str,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        task = cancel_audio_task(database_id, task_id)
    except AudioContractError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "audio.task.cancel",
        task_id,
        {"status": task["status"]},
    )
    return {"task": task}


@router.post("/tasks/{task_id}/retry")
def api_retry_audio_task(
    task_id: str,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        task = retry_failed_audio_task(database_id, task_id)
    except AudioContractError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "audio.task.retry",
        task_id,
        {"status": task["status"]},
    )
    return {"task": task}


@router.post("/tasks/{task_id}/outputs", status_code=201)
def api_register_audio_output(
    task_id: str,
    payload: AudioOutputCreate,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        task = register_audio_output(database_id, task_id, payload.model_dump())
    except AudioContractError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "audio.task.output",
        task_id,
        {"asset_id": payload.asset_id, "output_kind": payload.output_kind},
    )
    return {"task": task}


@router.post("/tasks/{task_id}/publish")
def api_publish_audio_task(
    task_id: str,
    payload: AudioTaskPublish,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        task = get_audio_task(database_id, task_id)
    except AudioContractError as error:
        _raise(error)
    asset_id = task.get("output_asset_id")
    chapter_id = task.get("chapter_id")
    if not asset_id or not chapter_id:
        raise HTTPException(
            409,
            detail={
                "code": "AUDIO_OUTPUT_NOT_READY",
                "message": "The audio task has no chapter output to publish",
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
                    "book_id": task["book_id"],
                    "target_type": "chapter",
                    "target_id": chapter_id,
                    "binding_type": payload.binding_type,
                    "notes": payload.notes,
                },
            )
        except MediaAssetError as error:
            if error.code != "BINDING_EXISTS":
                raise
            binding_reused = True
        refreshed = get_audio_task(database_id, task_id)
    except MediaAssetError as error:
        _raise_media(error)
    _audit(
        refreshed["database_id"],
        refreshed["book_id"],
        "audio.task.publish",
        task_id,
        {
            "asset_id": asset_id,
            "chapter_id": chapter_id,
            "binding_type": payload.binding_type,
            "binding_reused": binding_reused,
        },
    )
    return {
        "task": refreshed,
        "asset": asset,
        "binding": binding,
        "binding_reused": binding_reused,
    }


@router.post("/tasks/{task_id}/results", status_code=201)
def api_register_audio_result(
    task_id: str,
    payload: AudioResultCreate,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        task = register_audio_result(database_id, task_id, payload.model_dump())
    except AudioContractError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "audio.task.result",
        task_id,
        {"result_type": payload.result_type},
    )
    return {"task": task}


@router.post("/results/{result_id}/review")
def api_review_audio_result(
    result_id: str,
    payload: AudioResultReview,
    database_id: str = Query(..., pattern=ID_PATTERN, max_length=100),
    role: str = Depends(get_current_user_role),
):
    try:
        task = review_audio_result(
            database_id,
            result_id,
            approved=payload.approved,
        )
    except AudioContractError as error:
        _raise(error)
    _audit(
        task["database_id"],
        task["book_id"],
        "audio.result.review",
        result_id,
        {"approved": payload.approved, "task_id": task["task_id"]},
    )
    return {"task": task}
