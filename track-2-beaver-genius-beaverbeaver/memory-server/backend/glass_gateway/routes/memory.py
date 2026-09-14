from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from glass_gateway.app_state import app_state
from glass_gateway.auth import auth_registry
from glass_gateway.integrations.everos import EverOSClient
from glass_gateway.services.identity_candidates import IdentityCandidateAggregator
from glass_gateway.services.commitment_extractor import commitment_due_bucket
from glass_gateway.services.memory_capsule_bridge import EverOSCapsuleBridge
from glass_gateway.services.object_search_tool import SEARCH_OBJECTS_TOOL_SCHEMA

router = APIRouter()
_EVEROS_WRITEBACK_TIMEOUT_S = 60.0


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    query_type: Literal["auto", "text"] = "auto"


class ObjectSearchRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=20)


class MemoryCorrectionRequest(BaseModel):
    # Legacy whole-Episode contract. Kept for the existing memory page.
    source_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = None
    original_content: str = ""
    corrected_content: str | None = None
    status: Literal["confirmed", "rejected"] = "confirmed"
    note: str | None = None
    # MVP-16 field-level contract.
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    target_type: Literal[
        "capsule", "episode", "person", "object", "commitment", "daily_report"
    ] | None = None
    target_id: str | None = Field(default=None, min_length=1, max_length=300)
    field_path: str | None = Field(default=None, min_length=1, max_length=120)
    old_value: Any = None
    new_value: Any = None
    evidence_refs: list[str] = Field(default_factory=list)


class MemoryCorrectionRevertRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class PersonConfirmRequest(BaseModel):
    candidate_name: str = Field(min_length=1)
    confirmed_name: str = Field(min_length=1)
    relation: str | None = None
    notes: str | None = None
    source_session_ids: list[str] = Field(default_factory=list)


class PersonFreezeRequest(BaseModel):
    candidate_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_session_ids: list[str] = Field(default_factory=list)


class IdentityCandidateConfirmRequest(BaseModel):
    confirmed_name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list)
    relation: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class IdentityCandidateFreezeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class VoiceCandidateConfirmRequest(BaseModel):
    person_id: str | None = Field(default=None, min_length=1, max_length=160)
    confirmed_name: str | None = Field(default=None, min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list)
    relation: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class VoiceCandidateUnbindRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class VoiceCandidateSplitRequest(BaseModel):
    observation_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class IdentityProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list)
    relation: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class IdentityProfileStatusRequest(BaseModel):
    status: Literal["active", "frozen"]


class ObjectObservationRequest(BaseModel):
    object_label: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    image_uri: str = Field(min_length=1)
    captured_at_ms: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    sequence: int | None = None
    location_hint: str | None = None


class ConfirmedObjectRequest(BaseModel):
    label: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    personal_object_id: str | None = None
    visible_description: str | None = None


class MeetingExtractRequest(BaseModel):
    session_id: str = Field(min_length=1)
    transcript: str = Field(min_length=1)
    speaker_hints: list[str] = Field(default_factory=list)


class CommitmentExtractRequest(BaseModel):
    window_id: str = Field(min_length=1, max_length=300)
    capsule_id: str | None = Field(default=None, max_length=300)
    captured_at_ms: int = Field(ge=0)
    transcript: str = Field(min_length=1)
    audio_speakers: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    meeting_id: str | None = Field(default=None, max_length=300)


class CommitmentActionRequest(BaseModel):
    action: Literal["confirm", "update", "complete", "dismiss", "reopen"]
    owner_person_id: str | None = Field(default=None, max_length=300)
    text: str | None = Field(default=None, min_length=1, max_length=800)
    due_hint: str | None = Field(default=None, max_length=160)
    normalized_due_at: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)


class DailyReportGenerateRequest(BaseModel):
    generation_type: Literal["manual"] = "manual"


class TodoCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    normalized_due_at: str | None = Field(default=None, max_length=80)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    owner_person_id: str | None = Field(default=None, max_length=300)


class TodoUpdateRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=800)
    normalized_due_at: str | None = Field(default=None, max_length=80)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    owner_person_id: str | None = Field(default=None, max_length=300)


class TodoActionRequest(BaseModel):
    action: Literal[
        "confirm",
        "start",
        "complete",
        "confirm_completion",
        "reject_completion",
        "cancel",
        "reopen",
    ]
    note: str | None = Field(default=None, max_length=1000)


class PeoplePreuploadRequest(BaseModel):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    relation: str | None = None
    notes: str | None = None
    reminder_threshold: float = Field(default=0.75, ge=0, le=1)
    quiet_hours: dict[str, str] | None = None


class ReminderEvaluateRequest(BaseModel):
    person_name: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    local_time: str = Field(min_length=1)
    reason: str | None = None


class DailyReportCloseRequest(BaseModel):
    date: str = Field(min_length=1)
    corrections: list[str] = Field(default_factory=list)


class MemoryCapsuleRequest(BaseModel):
    window_id: str = Field(min_length=1)
    captured_at_ms: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    scene: str | None = None
    activity: str | None = None
    first_person_caption: str = ""
    event_type: Literal["daily", "object", "person", "meeting", "unknown"] | None = None
    meeting_likelihood: float | None = Field(default=None, ge=0, le=1)
    visible_people: list[dict[str, Any]] = Field(default_factory=list)
    audio_speakers: list[dict[str, Any]] = Field(default_factory=list)
    objects: list[dict[str, Any]] = Field(default_factory=list)
    meeting: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class MemoryCapsuleFlushRequest(BaseModel):
    session_id: str | None = None
    flushed_at_ms: int | None = None


def _authorized(authorization: str | None) -> bool:
    return auth_registry.authorized(authorization)


def _require_auth(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _identity_candidate(candidate_id: str) -> dict[str, Any]:
    candidate = next(
        (
            item
            for item in app_state.identity_directory.public_snapshot()["candidates"]
            if item.get("candidate_id") == candidate_id
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="identity candidate not found",
        )
    return candidate


def _voice_candidate(candidate_id: str) -> dict[str, Any]:
    candidate = next(
        (
            item
            for item in app_state.voice_directory.public_snapshot()["candidates"]
            if item.get("candidate_id") == candidate_id
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="voice candidate not found",
        )
    return candidate


def _identity_person_id(seed: str) -> str:
    normalized = seed.strip().casefold()
    return "person:user:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _candidate_media_path(candidate: dict[str, Any]) -> Path:
    representatives = list(candidate.get("representatives") or [])
    observation_ids = [
        str(item.get("observation_id") or "")
        for item in representatives
        if item.get("observation_id")
    ]
    if not observation_ids:
        observation_ids = [str(item) for item in candidate.get("observation_ids") or []]
    assignments = {
        str(item.get("observation_id") or ""): item
        for item in app_state.identity_directory.public_snapshot()["assignments"]
    }
    for observation_id in observation_ids:
        assignment = assignments.get(observation_id) or {}
        job_id = str(assignment.get("job_id") or "")
        job = app_state.identity_job_store.get_job(job_id, internal=True) if job_id else None
        image_path = str((job or {}).get("image_path") or "")
        if not image_path:
            continue
        try:
            resolved = _evidence_path(image_path)
        except HTTPException:
            continue
        if resolved.is_file():
            return resolved
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="candidate representative image not found",
    )


def _voice_candidate_media_path(candidate: dict[str, Any]) -> Path:
    assignments = {
        str(item.get("observation_id") or ""): item
        for item in app_state.voice_directory.public_snapshot()["assignments"]
    }
    for observation_id in candidate.get("observation_ids") or []:
        assignment = assignments.get(str(observation_id)) or {}
        job_id = str(assignment.get("job_id") or "")
        job = app_state.voice_job_store.get_job(job_id, internal=True) if job_id else None
        audio_path = str((job or {}).get("audio_path") or "")
        if not audio_path:
            continue
        try:
            resolved = _evidence_path(audio_path)
        except HTTPException:
            continue
        if resolved.is_file():
            return resolved
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="voice candidate representative audio not found",
    )


def _identity_people_projection() -> dict[str, Any]:
    directory = app_state.identity_directory.public_snapshot()
    review = app_state.memory_review_store.snapshot()
    profiles = {
        str(item.get("person_id") or item.get("id") or ""): item
        for item in review.get("profiles", [])
    }
    gallery_counts: dict[str, int] = {}
    for entry in directory.get("gallery_entries", []):
        person_id = str(entry.get("person_id") or "")
        gallery_counts[person_id] = gallery_counts.get(person_id, 0) + 1
    voice_directory = app_state.voice_directory.public_snapshot()
    voice_gallery_counts: dict[str, int] = {}
    for entry in voice_directory.get("gallery_entries", []):
        if entry.get("status") != "active":
            continue
        person_id = str(entry.get("person_id") or "")
        voice_gallery_counts[person_id] = voice_gallery_counts.get(person_id, 0) + 1
    people = []
    directory_people_by_id = {
        str(item.get("person_id") or ""): item
        for item in directory.get("people", [])
    }
    representative_by_person: dict[str, dict[str, Any]] = {}
    for candidate in directory.get("candidates", []):
        person_id = str(candidate.get("confirmed_person_id") or "")
        representatives = list(candidate.get("representatives") or [])
        if not person_id or not representatives:
            continue
        existing = representative_by_person.get(person_id)
        if existing is None or int(candidate.get("last_seen_at_ms") or 0) > int(
            existing.get("last_seen_at_ms") or 0
        ):
            representative_by_person[person_id] = candidate

    def person_representative(person_id: str) -> dict[str, Any]:
        candidate = representative_by_person.get(person_id)
        if candidate:
            representatives = list(candidate.get("representatives") or [])
            return {
                "representative": representatives[0],
                "representative_media_available": True,
                "representative_media_url": (
                    f"/v1/memory/identity/candidates/{candidate['candidate_id']}/media"
                ),
                "representative_media_source": "face_candidate_crop",
            }

        # Annotation-assisted demos and migrated profiles can predate a face
        # candidate crop. Keep the actual evidence chain visible by using the
        # first image from one of the profile's source windows as a fallback.
        profile = profiles.get(person_id) or {}
        source_refs = {
            str(item) for item in profile.get("source_refs", []) if str(item)
        }
        for capsule in review.get("capsules", []):
            if str(capsule.get("window_id") or "") not in source_refs:
                continue
            for evidence in capsule.get("evidence", []):
                uri = str(evidence.get("uri") or "")
                if evidence.get("kind") != "image" or not uri:
                    continue
                return {
                    "representative": {
                        "evidence_id": evidence.get("id"),
                        "window_id": capsule.get("window_id"),
                    },
                    "representative_media_available": True,
                    "representative_media_url": (
                        "/v1/memory/evidence-file?uri=" + quote(uri, safe="")
                    ),
                    "representative_media_source": "source_window_evidence",
                }
        return {
            "representative": None,
            "representative_media_available": False,
            "representative_media_url": None,
            "representative_media_source": None,
        }

    for person in directory.get("people", []):
        person_id = str(person.get("person_id") or "")
        people.append(
            {
                **person,
                **person_representative(person_id),
                "profile": profiles.get(person_id),
                "gallery_entry_count": gallery_counts.get(person_id, 0),
                "face_gallery_entry_count": gallery_counts.get(person_id, 0),
                "voice_gallery_entry_count": voice_gallery_counts.get(person_id, 0),
            }
        )
    known_people = {str(item.get("person_id") or "") for item in people}
    for person_id, profile in profiles.items():
        if not person_id or person_id in known_people or not profile.get("person_id"):
            continue
        people.append(
            {
                "person_id": person_id,
                "display_name": profile.get("name"),
                "status": "frozen" if profile.get("status") == "frozen" else "active",
                **person_representative(person_id),
                "profile": profile,
                "gallery_entry_count": 0,
                "face_gallery_entry_count": 0,
                "voice_gallery_entry_count": voice_gallery_counts.get(person_id, 0),
            }
        )
    candidates = []
    for candidate in directory.get("candidates", []):
        representatives = list(candidate.get("representatives") or [])
        suggested_person_id = str(
            (candidate.get("gallery_decision") or {}).get("person_id") or ""
        )
        suggested_directory_person = directory_people_by_id.get(suggested_person_id)
        candidates.append(
            {
                **candidate,
                "representative": representatives[0] if representatives else None,
                "representative_media_available": bool(representatives),
                "representative_media_url": (
                    f"/v1/memory/identity/candidates/{candidate['candidate_id']}/media"
                    if representatives
                    else None
                ),
                "suggested_person": (
                    {
                        **suggested_directory_person,
                        "profile": profiles.get(suggested_person_id),
                    }
                    if suggested_directory_person
                    else None
                ),
            }
        )
    candidates.sort(
        key=lambda item: int(item.get("last_seen_at_ms") or 0),
        reverse=True,
    )
    voice_candidates = []
    for candidate in voice_directory.get("candidates", []):
        representative_turns = list(candidate.get("representative_turns") or [])
        suggested_person_id = str(
            (candidate.get("gallery_suggestion") or {}).get("suggested_person_id") or ""
        )
        voice_candidates.append(
            {
                **candidate,
                "representative_turn": (
                    representative_turns[0] if representative_turns else None
                ),
                "representative_media_available": bool(representative_turns),
                "representative_media_url": (
                    f"/v1/memory/voice/candidates/{candidate['candidate_id']}/media"
                    if representative_turns
                    else None
                ),
                "suggested_person": (
                    {
                        "person_id": suggested_person_id,
                        "display_name": (
                            profiles.get(suggested_person_id) or {}
                        ).get("name"),
                        "profile": profiles.get(suggested_person_id),
                    }
                    if suggested_person_id
                    else None
                ),
            }
        )
    voice_candidates.sort(
        key=lambda item: int(item.get("last_heard_at_ms") or 0), reverse=True
    )
    return {
        "candidates": candidates,
        "face_candidates": candidates,
        "voice_candidates": voice_candidates,
        "people": people,
        "legacy_profiles": [
            item for key, item in profiles.items() if not key.startswith("person:user:")
        ],
        "gallery_policy_id": app_state.identity_directory.gallery_policy_id,
        "automatic_real_name_assignment": False,
    }


def _person_names(
    profiles: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    source = (
        profiles
        if profiles is not None
        else app_state.memory_review_store.snapshot().get("profiles", [])
    )
    return {
        str(item.get("person_id") or ""): str(item.get("name") or "")
        for item in source
        if item.get("person_id") and item.get("name") and item.get("status") != "deleted"
    }


def _resolve_capsule_identities(
    capsule: dict[str, Any],
    *,
    people: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = dict(capsule)
    result["audio_speakers"] = app_state.voice_directory.resolve_audio_speakers(
        list(capsule.get("audio_speakers") or []),
        people=people if people is not None else _person_names(),
    )
    return result


async def _wait_for_identity_job(job_id: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = app_state.identity_job_store.get_job(job_id)
        if job and job.get("status") not in {"pending", "running"}:
            return job
        await asyncio.sleep(0.05)
    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail="identity enrollment inference timed out; evidence remains queued",
    )


def _evidence_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif parsed.scheme == "":
        path = Path(uri)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unsupported evidence uri")
    raw_root = Path(app_state.settings.raw_media_dir).resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(raw_root)
    except (OSError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="evidence not found")
    return resolved


def _evidence_media(uri: str) -> tuple[str, str]:
    content_type = mimetypes.guess_type(urlparse(uri).path)[0] or "application/octet-stream"
    if content_type.startswith("image/"):
        viewer_type = "image"
    elif content_type.startswith("audio/"):
        viewer_type = "audio"
    elif content_type == "application/json":
        viewer_type = "json"
    else:
        viewer_type = "file"
    return content_type, viewer_type


def _evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    uri = str(item.get("uri") or "")
    content_type, viewer_type = _evidence_media(uri)
    available = False
    if uri:
        try:
            available = _evidence_path(uri).is_file()
        except HTTPException:
            pass
    return {
        **item,
        "uri": uri,
        "content_type": content_type,
        "viewer_type": viewer_type,
        "available": available,
    }


def _manifest_summary(uri: str | None) -> dict[str, Any] | None:
    if not uri:
        return None
    try:
        path = _evidence_path(uri)
    except HTTPException:
        return {"uri": uri, "available": False}
    if not path.is_file():
        return {"uri": uri, "available": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"uri": uri, "available": True, "error": str(exc)}
    return {
        "uri": uri,
        "available": True,
        "state": payload.get("state"),
        "attempt_count": payload.get("attempt_count"),
        "last_error": payload.get("last_error"),
        "updated_at_ms": payload.get("updated_at_ms") or payload.get("last_attempt_ms"),
        "processing": payload.get("processing") or {},
        "clock": payload.get("clock") or {},
        "technical_window": payload.get("technical_window") or {},
    }


def _results(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    data = envelope.get("data") if isinstance(envelope, dict) else {}
    if not isinstance(data, dict):
        return []
    if "results" in data or "items" in data:
        results = data.get("results", data.get("items", []))
        return [item for item in results if isinstance(item, dict)]
    merged: list[dict[str, Any]] = []
    for key in ("episodes", "profiles", "agent_cases", "agent_skills"):
        values = data.get(key, [])
        if isinstance(values, list):
            merged.extend(item for item in values if isinstance(item, dict))
    return merged


def _content_text(item: dict[str, Any]) -> str:
    content = item.get("content") or item.get("text")
    if not content:
        summary = str(item.get("summary") or "").strip()
        episode = str(item.get("episode") or "").strip()
        content = "\n".join(part for part in (summary, episode) if part)
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("summary", "text", "markdown", "body"):
            value = content.get(key)
            if isinstance(value, str):
                return value
    return str(content)


def _source(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    manifest = metadata.get("manifest") or metadata.get("bridge_manifest")
    return {
        "id": item.get("id") or item.get("memory_id"),
        "session_id": item.get("session_id") or metadata.get("session_id"),
        "manifest": manifest,
        "score": item.get("score"),
        "memory_type": item.get("memory_type"),
    }


def _episode_item(item: dict[str, Any]) -> dict[str, Any]:
    source = _source(item)
    summary = str(item.get("summary") or "").strip()
    episode = str(item.get("episode") or "").strip()
    content = episode or _content_text(item) or summary
    subject = str(item.get("subject") or "").strip()
    return {
        "id": source["id"],
        "session_id": source["session_id"],
        "manifest": source["manifest"],
        "title": subject or summary,
        "summary": summary,
        "content": content,
        "timestamp": item.get("timestamp"),
        "atomic_facts": [
            fact
            for fact in item.get("atomic_facts", [])
            if isinstance(fact, dict)
        ],
        "source": source,
        "everos": item,
    }


def _episode_review_filters() -> dict[str, Any] | None:
    snapshot = app_state.memory_review_store.snapshot()
    captured_at = [
        int(item["captured_at_ms"])
        for item in snapshot.get("capsules", [])
        if isinstance(item.get("captured_at_ms"), int)
    ]
    if not captured_at:
        return None
    return {"timestamp": {"gte": min(captured_at)}}


def _review_message(text: str) -> dict[str, Any]:
    return {
        "sender_id": app_state.settings.everos_user_id,
        "sender_name": "Web reviewer",
        "role": "user",
        "timestamp": int(time.time() * 1000),
        "content": [{"type": "text", "text": text}],
    }


def _correction_writeback_response(item: dict[str, Any]) -> dict[str, Any]:
    response = item.get("last_writeback_response") or {}
    if item.get("writeback_status") == "applied":
        return {
            "status": "flushed",
            "session_id": item.get("everos_session_id"),
            **response,
        }
    return {
        "status": "pending_retry",
        "session_id": item.get("everos_session_id"),
        "stage": item.get("writeback_stage"),
        "error": item.get("last_error"),
        "next_retry_at_ms": item.get("next_retry_at_ms"),
    }


async def _write_text_back_to_everos(session_id: str, text: str) -> dict[str, Any]:
    async def write_and_flush() -> tuple[dict[str, Any], dict[str, Any]]:
        add_result = await app_state.everos.add_messages(session_id, [_review_message(text)])
        flush_result = await app_state.everos.flush(session_id)
        return add_result, flush_result

    try:
        add_result, flush_result = await asyncio.wait_for(
            write_and_flush(),
            timeout=_EVEROS_WRITEBACK_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        return {
            "status": "pending_retry",
            "session_id": session_id,
            "error": f"EverOS writeback timed out after {_EVEROS_WRITEBACK_TIMEOUT_S:g}s",
        }
    except Exception as exc:
        return {
            "status": "pending_retry",
            "session_id": session_id,
            "error": str(exc),
        }
    return {"status": "flushed", "add": add_result, "flush": flush_result}


def _capsule_person_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("label") or item.get("candidate_name") or "").strip()


def _capsule_object_label(item: dict[str, Any]) -> str:
    return str(
        item.get("label")
        or item.get("object_label")
        or item.get("canonical_name")
        or item.get("label_normalized")
        or item.get("normalized_label")
        or item.get("label_raw")
        or item.get("name")
        or ""
    ).strip()


def _capsule_event_type(request: MemoryCapsuleRequest) -> str:
    if request.event_type:
        return request.event_type
    if request.meeting or (request.meeting_likelihood is not None and request.meeting_likelihood >= 0.65):
        return "meeting"
    if request.objects:
        return "object"
    if request.visible_people or request.audio_speakers:
        return "person"
    return "daily"


def _parse_speaker_turns(transcript: str, speaker_hints: list[str]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    known = set(speaker_hints)
    normalized_transcript = transcript.replace("\\r\\n", "\n").replace("\\n", "\n")
    for raw in normalized_transcript.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" in line:
            speaker, text = line.split(":", 1)
        elif "：" in line:
            speaker, text = line.split("：", 1)
        else:
            speaker, text = ("未知说话人", line)
        speaker = speaker.strip() or "未知说话人"
        text = text.strip()
        if speaker_hints and speaker not in known and speaker != "未知说话人":
            speaker = next((hint for hint in speaker_hints if hint.lower() in speaker.lower()), speaker)
        turns.append({"speaker": speaker, "text": text})
    return turns


def _extract_conclusions(turns: list[dict[str, str]]) -> list[str]:
    conclusions: list[str] = []
    for turn in turns:
        text = turn["text"]
        if "结论" in text:
            cleaned = re.sub(r"^.*?结论[是:：]?", "", text).strip(" ，。")
            if cleaned:
                conclusions.append(cleaned)
        elif any(word in text for word in ("决定", "确定", "先验证", "先跑")):
            conclusions.append(text)
    return conclusions[:5]


def _extract_commitments(turns: list[dict[str, str]]) -> list[dict[str, Any]]:
    commitments: list[dict[str, Any]] = []
    for turn in turns:
        text = turn["text"]
        explicit_owner = any(
            word in text
            for word in (
                "我负责",
                "我会",
                "我来",
                "我发",
                "我把",
                "我提交",
                "承诺",
                "答应",
            )
        )
        if not explicit_owner:
            continue
        commitment_text = text
        commitment_text = re.sub(r"^(我负责|我会|我来)", "", commitment_text).strip(" ，。")
        due_hint = None
        for marker in ("今天", "明天", "周五", "周五前", "明天前"):
            if marker in text:
                due_hint = marker
                break
        commitments.append(
            {
                "owner": turn["speaker"],
                "text": commitment_text,
                "due_hint": due_hint,
                "status": "open",
            }
        )
    return commitments[:10]


def _in_quiet_hours(local_time: str, quiet_hours: dict[str, str]) -> bool:
    if not quiet_hours:
        return False
    start = quiet_hours.get("start")
    end = quiet_hours.get("end")
    if not start or not end:
        return False
    try:
        current = datetime.fromisoformat(local_time).time()
        start_time = datetime.strptime(start, "%H:%M").time()
        end_time = datetime.strptime(end, "%H:%M").time()
    except ValueError:
        return False
    if start_time <= end_time:
        return start_time <= current < end_time
    return current >= start_time or current < end_time


def _daily_report_text(report: dict[str, Any], corrections: list[str] | None = None) -> str:
    lines = [f"每日闭环 {report['date']}"]
    content = report.get("content") if isinstance(report.get("content"), dict) else {}
    if content.get("overview"):
        lines.append(str(content["overview"]))
    timeline = [
        str(item.get("text") or "")
        for item in content.get("timeline", [])
        if isinstance(item, dict) and item.get("text")
    ]
    if timeline:
        lines.append("今日回顾：" + "；".join(timeline[:8]))
    notable = [
        str(item.get("text") or "")
        for item in content.get("notable_items", [])
        if isinstance(item, dict) and item.get("text")
    ]
    if notable:
        lines.append("值得留意：" + "；".join(notable[:5]))
    special = [
        str(item.get("text") or "")
        for item in content.get("special_moments", [])
        if isinstance(item, dict) and item.get("text")
    ]
    if special:
        lines.append("特别瞬间：" + "；".join(special[:5]))
    if report.get("confirmed_events"):
        lines.append("已确认事件：" + "；".join(report["confirmed_events"][:5]))
    if report.get("commitments"):
        lines.append(
            "承诺与截止项："
            + "；".join(item.get("text", "") for item in report["commitments"][:5])
        )
    if report.get("object_events"):
        lines.append(
            "视觉记忆："
            + "；".join(
                f"{item.get('object_label')}@{item.get('location_hint') or '未知位置'}"
                for item in report["object_events"][:5]
            )
        )
    if corrections:
        lines.append("修正：" + "；".join(corrections))
    return "\n".join(lines)


@router.post("/v1/memory/search")
async def search_memory(
    request: MemorySearchRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    payload = await app_state.memory_search.search_text(
        everos=app_state.everos,
        review_store=app_state.memory_review_store,
        user_id=app_state.settings.everos_user_id,
        query=request.query,
        query_type=request.query_type,
        top_k=request.top_k,
    )
    return _search_response_with_compat(payload)


@router.get("/v1/tools/search_objects/schema")
async def search_objects_tool_schema(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    return SEARCH_OBJECTS_TOOL_SCHEMA


@router.post("/v1/objects/search")
async def search_objects(
    request: ObjectSearchRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    return await app_state.object_search.search(
        question=request.question,
        top_k=request.top_k,
    )


def _search_response_with_compat(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    top = results[0] if results and isinstance(results[0], dict) else None
    text = str(top.get("content") or top.get("summary") or "") if top else None
    patch = app_state.cards.memory_patch(1, text)
    payload.update(
        {
        "ui_patch": patch.model_dump(mode="json"),
            "source": top.get("source") if top else None,
        }
    )
    return payload


def _image_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


@router.post("/v1/memory/search/media")
async def search_memory_media(
    image: UploadFile = File(...),
    query: str = Form(default=""),
    top_k: int = Form(default=10, ge=1, le=20),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    maximum = app_state.settings.memory_search_upload_max_bytes
    data = await image.read(maximum + 1)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="empty image",
        )
    if len(data) > maximum:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="image exceeds upload limit",
        )
    extension = _image_extension(data)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="only JPEG, PNG and WebP images are supported",
        )
    upload_root = (
        Path(app_state.settings.raw_media_dir).resolve()
        / ".memory-search"
        / "uploads"
    )
    upload_root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    media_path = upload_root / f"{digest[:16]}-{uuid.uuid4().hex}{extension}"
    media_path.write_bytes(data)
    try:
        payload = await app_state.memory_search.search_media(
            everos=app_state.everos,
            review_store=app_state.memory_review_store,
            user_id=app_state.settings.everos_user_id,
            query=query,
            media_path=media_path,
            top_k=top_k,
        )
    finally:
        media_path.unlink(missing_ok=True)
    return _search_response_with_compat(payload)


@router.get("/v1/memory/episodes")
async def list_episodes(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    _require_auth(authorization)
    filters = _episode_review_filters()
    index_error: str | None = None
    try:
        envelope = await app_state.everos.get_episodes(
            app_state.settings.everos_user_id,
            page=page,
            page_size=page_size,
            filters=filters,
        )
    except Exception as exc:
        index_error = str(exc)
        envelope = {
            "status": "pending_retry",
            "error": index_error,
            "data": {"items": []},
        }
    if not _results(envelope) and isinstance(app_state.everos, EverOSClient):
        markdown = app_state.everos_markdown.get_episodes(
            app_state.settings.everos_user_id,
            page=page,
            page_size=page_size,
            filters=filters,
        )
        if _results(markdown):
            markdown["index_status"] = "unavailable" if index_error else "not_visible"
            markdown["index_error"] = index_error
            envelope = markdown
    items: list[dict[str, Any]] = []
    for source in _results(envelope):
        episode = _episode_item(source)
        projected = app_state.memory_review_store.apply_corrections(
            target_type="episode",
            target_id=str(episode.get("id") or ""),
            source=episode,
        )
        if projected is not None:
            items.append(projected)
    return {"items": items, "everos": envelope}


@router.get("/v1/memory/review")
async def memory_review(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    return app_state.memory_review_store.snapshot()


@router.get("/v1/memory/overview")
async def memory_overview(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    return app_state.memory_review_store.overview_snapshot()


@router.get("/v1/memory/identity/status")
async def identity_status(
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Expose public job/candidate state without biometric vectors or paths."""

    _require_auth(authorization)
    coordinator = getattr(app_state, "identity_perception", None)
    if coordinator is None:
        return {
            "status": "disabled",
            "jobs": [],
            "candidates": [],
            "people": [],
        }
    health = await coordinator.health()
    worker_health = health.get("worker")
    if isinstance(worker_health, dict):
        worker_contract = worker_health.get("worker")
        if isinstance(worker_contract, dict):
            worker_contract.pop("allowed_media_root", None)
    directory = app_state.identity_directory.public_snapshot()
    return {
        "status": "available",
        "health": health,
        "jobs": app_state.identity_job_store.recent_jobs(limit=limit),
        "candidates": directory.get("candidates", [])[:limit],
        "people": directory.get("people", [])[:limit],
        "gallery_policy_id": app_state.identity_directory.gallery_policy_id,
    }


@router.get("/v1/memory/identity/people")
async def identity_people(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    return _identity_people_projection()


@router.post("/v1/memory/voice/candidates/{candidate_id}/confirm")
async def confirm_voice_candidate(
    candidate_id: str,
    request: VoiceCandidateConfirmRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    candidate = _voice_candidate(candidate_id)
    profiles = app_state.memory_review_store.snapshot().get("profiles", [])
    profile = next(
        (
            item
            for item in profiles
            if request.person_id and item.get("person_id") == request.person_id
        ),
        None,
    )
    if request.person_id and profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="identity person profile not found",
        )
    requested_name = str(request.confirmed_name or "").strip()
    if profile is None and requested_name:
        key = requested_name.casefold()
        profile = next(
            (
                item
                for item in profiles
                if key
                in {
                    str(item.get("name") or "").strip().casefold(),
                    *{
                        str(alias).strip().casefold()
                        for alias in item.get("aliases") or []
                    },
                }
            ),
            None,
        )
    if profile is not None:
        person_id = str(profile["person_id"])
        display_name = str(profile.get("name") or requested_name)
    else:
        if not requested_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="person_id or confirmed_name is required",
            )
        person_id = _identity_person_id(f"voice-candidate:{candidate_id}:{requested_name}")
        display_name = requested_name
        app_state.identity_directory.upsert_confirmed_person(
            person_id=person_id,
            display_name=display_name,
        )
    try:
        confirmation = app_state.voice_directory.confirm_candidate(
            candidate_id=candidate_id,
            person_id=person_id,
            display_name=display_name,
            actor="user:web",
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    everos_session_id = f"voice-identity-confirm-{int(time.time() * 1000)}"
    current = profile or {}
    updated_profile = app_state.memory_review_store.upsert_identity_profile(
        person_id=person_id,
        name=display_name,
        aliases=request.aliases or list(current.get("aliases") or []),
        relation=request.relation if request.relation is not None else current.get("relation"),
        organization=(
            request.organization
            if request.organization is not None
            else current.get("organization")
        ),
        role=request.role if request.role is not None else current.get("role"),
        notes=request.notes if request.notes is not None else current.get("notes"),
        face_candidate_ids=list(current.get("face_candidate_ids") or []),
        voice_candidate_ids=[candidate_id],
        source_refs=list(candidate.get("evidence_ids") or []),
        source="voice_candidate_user_confirmation",
        everos_session_id=everos_session_id,
    )
    writeback = await _write_text_back_to_everos(
        everos_session_id,
        "用户确认声纹候选与人物档案的关系。\n"
        f"人物：{display_name}\n人物ID：{person_id}\n"
        f"声纹候选：{candidate_id}\n"
        f"来源证据：{', '.join(candidate.get('evidence_ids') or [])}\n"
        "说明：这是用户确认的关系；声纹向量未写入 EverOS。",
    )
    return {
        "confirmation": confirmation,
        "profile": updated_profile,
        "everos_writeback": writeback,
        "automatic_real_name_assignment": False,
    }


@router.get("/v1/memory/voice/candidates/{candidate_id}/media")
async def voice_candidate_media(
    candidate_id: str,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    _require_auth(authorization)
    candidate = _voice_candidate(candidate_id)
    return FileResponse(
        _voice_candidate_media_path(candidate),
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/v1/memory/voice/candidates/{candidate_id}/unbind")
async def unbind_voice_candidate(
    candidate_id: str,
    request: VoiceCandidateUnbindRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    candidate = _voice_candidate(candidate_id)
    person_id = str(candidate.get("confirmed_person_id") or "")
    if not person_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="voice candidate is not bound",
        )
    try:
        detached = app_state.voice_directory.unbind_candidate(
            candidate_id=candidate_id,
            actor="user:web",
            reason=request.reason,
        )
        profile = app_state.memory_review_store.remove_identity_candidate_link(
            person_id=person_id,
            candidate_id=candidate_id,
            modality="voice",
            source="voice_candidate_user_unbind",
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    everos_session_id = f"voice-identity-unbind-{int(time.time() * 1000)}"
    writeback = await _write_text_back_to_everos(
        everos_session_id,
        "用户纠正声纹身份关系。\n"
        f"人物ID：{person_id}\n声纹候选：{candidate_id}\n"
        f"原因：{request.reason}\n"
        "该声纹已恢复匿名；原始音频与历史记忆证据未删除。",
    )
    return {
        "detached": detached,
        "profile": profile,
        "everos_writeback": writeback,
        "raw_audio_deleted": False,
    }


@router.post("/v1/memory/voice/candidates/{candidate_id}/freeze")
async def freeze_voice_candidate(
    candidate_id: str,
    request: IdentityCandidateFreezeRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    candidate = _voice_candidate(candidate_id)
    if candidate.get("confirmed_person_id"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="unbind confirmed voice candidate before freezing",
        )
    try:
        updated = app_state.voice_directory.set_candidate_status(candidate_id, "frozen")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"candidate": updated, "reason": request.reason, "reversible": True}


@router.post("/v1/memory/voice/candidates/{candidate_id}/restore")
async def restore_voice_candidate(
    candidate_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    _voice_candidate(candidate_id)
    try:
        updated = app_state.voice_directory.set_candidate_status(candidate_id, "active")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"candidate": updated}


@router.post("/v1/memory/voice/candidates/{candidate_id}/split")
async def split_voice_candidate(
    candidate_id: str,
    request: VoiceCandidateSplitRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    _voice_candidate(candidate_id)
    try:
        split = app_state.voice_directory.split_candidate(
            candidate_id=candidate_id,
            observation_ids=request.observation_ids,
            actor="user:web",
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"split": split, "observation_conservation_required": True}


@router.delete("/v1/memory/voice/candidates/{candidate_id}")
async def delete_voice_candidate(
    candidate_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    _voice_candidate(candidate_id)
    try:
        deletion = app_state.voice_directory.delete_candidate(
            candidate_id,
            actor="user:web",
        )
        voice_job_cleanup = app_state.voice_job_store.delete_turns(
            list(deletion.get("removed_turn_ids") or [])
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        "deletion": deletion,
        "derived_voice_cleanup": voice_job_cleanup,
        "raw_memory_evidence_deleted": False,
    }


@router.get("/v1/memory/identity/candidates/{candidate_id}/media")
async def identity_candidate_media(
    candidate_id: str,
    authorization: str | None = Header(default=None),
) -> FileResponse:
    _require_auth(authorization)
    candidate = _identity_candidate(candidate_id)
    return FileResponse(
        _candidate_media_path(candidate),
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/v1/memory/identity/candidates/{candidate_id}/confirm")
async def confirm_identity_candidate(
    candidate_id: str,
    request: IdentityCandidateConfirmRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    candidate = _identity_candidate(candidate_id)
    existing_person_id = str(candidate.get("confirmed_person_id") or "")
    requested_name = request.confirmed_name.strip().casefold()
    review_profiles = app_state.memory_review_store.snapshot().get("profiles", [])
    matching_profile = next(
        (
            item
            for item in review_profiles
            if requested_name
            in {
                str(item.get("name") or "").strip().casefold(),
                *{
                    str(alias).strip().casefold()
                    for alias in item.get("aliases") or []
                },
            }
            and item.get("person_id")
        ),
        None,
    )
    suggested_person_id = str(
        (candidate.get("gallery_decision") or {}).get("person_id") or ""
    )
    suggested_person = next(
        (
            item
            for item in app_state.identity_directory.public_snapshot()["people"]
            if item.get("person_id") == suggested_person_id
        ),
        None,
    )
    use_suggestion = bool(
        suggested_person
        and str(suggested_person.get("display_name") or "").strip().casefold()
        == requested_name
    )
    person_id = (
        existing_person_id
        or str((matching_profile or {}).get("person_id") or "")
        or (suggested_person_id if use_suggestion else "")
        or _identity_person_id(f"candidate:{candidate_id}:{request.confirmed_name}")
    )
    try:
        confirmation = app_state.identity_directory.confirm_candidate(
            candidate_id=candidate_id,
            person_id=person_id,
            display_name=request.confirmed_name,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    everos_session_id = f"identity-confirm-{int(time.time() * 1000)}"
    profile = app_state.memory_review_store.upsert_identity_profile(
        person_id=person_id,
        name=request.confirmed_name,
        aliases=request.aliases,
        relation=request.relation,
        organization=request.organization,
        role=request.role,
        notes=request.notes,
        face_candidate_ids=[candidate_id],
        voice_candidate_ids=[],
        source_refs=list(candidate.get("evidence_ids") or []),
        source="face_candidate_user_confirmation",
        everos_session_id=everos_session_id,
    )
    text = (
        "用户确认人物档案。\n"
        f"姓名：{request.confirmed_name}\n"
        f"关系：{request.relation or ''}\n"
        f"组织：{request.organization or ''}\n"
        f"角色：{request.role or ''}\n"
        f"备注：{request.notes or ''}\n"
        f"人脸候选：{candidate_id}\n"
        f"来源证据：{', '.join(candidate.get('evidence_ids') or [])}"
    )
    writeback = await _write_text_back_to_everos(everos_session_id, text)
    return {
        "confirmation": confirmation,
        "profile": profile,
        "everos_writeback": writeback,
        "automatic_real_name_assignment": False,
    }


@router.post("/v1/memory/identity/candidates/{candidate_id}/freeze")
async def freeze_identity_candidate(
    candidate_id: str,
    request: IdentityCandidateFreezeRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    candidate = _identity_candidate(candidate_id)
    if candidate.get("status") == "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="confirmed candidate must be managed through its person profile",
        )
    try:
        updated = app_state.identity_directory.set_candidate_status(
            candidate_id,
            "frozen",
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    review = app_state.memory_review_store.freeze_candidate(
        candidate_name=candidate_id,
        reason=request.reason,
        source_session_ids=list(candidate.get("evidence_ids") or []),
    )
    return {"candidate": updated, "review": review, "reversible": True}


@router.post("/v1/memory/identity/candidates/{candidate_id}/restore")
async def restore_identity_candidate(
    candidate_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    _identity_candidate(candidate_id)
    try:
        updated = app_state.identity_directory.set_candidate_status(
            candidate_id,
            "active",
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    review = app_state.memory_review_store.restore_candidate(
        candidate_name=candidate_id,
    )
    return {"candidate": updated, "review": review}


@router.delete("/v1/memory/identity/candidates/{candidate_id}")
async def delete_identity_candidate(
    candidate_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    candidate = _identity_candidate(candidate_id)
    observation_ids = [
        str(item) for item in candidate.get("observation_ids") or [] if item
    ]
    try:
        deleted = app_state.identity_directory.delete_candidate(candidate_id)
        job_cleanup = app_state.identity_job_store.delete_observations(observation_ids)
        review = app_state.memory_review_store.delete_candidate_review(
            candidate_name=candidate_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        "deletion": deleted,
        "derived_face_cleanup": job_cleanup,
        "review": review,
        "raw_memory_evidence_deleted": False,
    }


@router.put("/v1/memory/identity/people/{person_id}")
async def update_identity_person(
    person_id: str,
    request: IdentityProfileUpdateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    directory_people = app_state.identity_directory.public_snapshot()["people"]
    if not any(item.get("person_id") == person_id for item in directory_people):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="identity person not found",
        )
    person = app_state.identity_directory.upsert_confirmed_person(
        person_id=person_id,
        display_name=request.name,
    )
    current = next(
        (
            item
            for item in app_state.memory_review_store.snapshot().get("profiles", [])
            if item.get("person_id") == person_id
        ),
        {},
    )
    everos_session_id = f"identity-profile-update-{int(time.time() * 1000)}"
    profile = app_state.memory_review_store.upsert_identity_profile(
        person_id=person_id,
        name=request.name,
        aliases=request.aliases,
        relation=request.relation,
        organization=request.organization,
        role=request.role,
        notes=request.notes,
        face_candidate_ids=list(current.get("face_candidate_ids") or []),
        voice_candidate_ids=list(current.get("voice_candidate_ids") or []),
        source_refs=list(current.get("source_refs") or []),
        source="web_profile_update",
        everos_session_id=everos_session_id,
    )
    writeback = await _write_text_back_to_everos(
        everos_session_id,
        "用户更新人物档案。\n"
        f"姓名：{request.name}\n关系：{request.relation or ''}\n"
        f"组织：{request.organization or ''}\n角色：{request.role or ''}\n"
        f"备注：{request.notes or ''}",
    )
    return {"person": person, "profile": profile, "everos_writeback": writeback}


@router.post("/v1/memory/identity/people/{person_id}/status")
async def update_identity_person_status(
    person_id: str,
    request: IdentityProfileStatusRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    try:
        person = app_state.identity_directory.set_person_status(
            person_id,
            request.status,
        )
        voice_status = app_state.voice_directory.set_person_status(
            person_id,
            request.status,
        )
        profile = app_state.memory_review_store.set_identity_profile_status(
            person_id=person_id,
            status="confirmed" if request.status == "active" else request.status,
            source="web_profile_status",
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        "person": person,
        "voice_status": voice_status,
        "profile": profile,
        "reversible": True,
    }


@router.delete("/v1/memory/identity/people/{person_id}")
async def delete_identity_person(
    person_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    directory = app_state.identity_directory.public_snapshot()
    profiles = app_state.memory_review_store.snapshot().get("profiles", [])
    voice_links = app_state.voice_directory.public_snapshot().get("identity_links", [])
    if not (
        any(item.get("person_id") == person_id for item in directory["people"])
        or any(item.get("person_id") == person_id for item in profiles)
        or any(item.get("person_id") == person_id for item in voice_links)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="identity person not found",
        )
    observation_ids = [
        str(observation_id)
        for candidate in directory["candidates"]
        if candidate.get("confirmed_person_id") == person_id
        for observation_id in candidate.get("observation_ids") or []
        if observation_id
    ]
    try:
        if any(item.get("person_id") == person_id for item in directory["people"]):
            deleted = app_state.identity_directory.delete_person(person_id)
        else:
            deleted = {
                "person_id": person_id,
                "deleted": True,
                "removed_candidate_count": 0,
                "removed_gallery_entry_count": 0,
            }
        voice_deleted = app_state.voice_directory.delete_person(
            person_id,
            actor="user:web",
        )
        voice_job_cleanup = app_state.voice_job_store.delete_turns(
            list(voice_deleted.get("removed_turn_ids") or [])
        )
        job_cleanup = app_state.identity_job_store.delete_observations(observation_ids)
        profile = app_state.memory_review_store.delete_identity_profile(
            person_id=person_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        "deletion": deleted,
        "voice_deletion": voice_deleted,
        "derived_voice_cleanup": voice_job_cleanup,
        "derived_face_cleanup": job_cleanup,
        "profile": profile,
        "raw_memory_evidence_deleted": False,
        "everos_history_deleted": False,
    }


@router.post("/v1/memory/identity/people/preupload")
async def preupload_identity_person(
    image: UploadFile = File(...),
    name: str = Form(min_length=1, max_length=120),
    aliases: str = Form(default=""),
    relation: str = Form(default=""),
    organization: str = Form(default=""),
    role: str = Form(default=""),
    notes: str = Form(default=""),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    if app_state.identity_perception is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="identity worker is disabled",
        )
    media_type = str(image.content_type or "").lower()
    suffix = "jpg" if media_type in {"image/jpeg", "image/jpg"} else "png"
    if media_type not in {"image/jpeg", "image/jpg", "image/png"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="only JPEG and PNG enrollment images are supported",
        )
    body = await image.read()
    if not body or len(body) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="enrollment image must be between 1 byte and 10 MiB",
        )
    captured_at_ms = int(time.time() * 1000)
    person_id = _identity_person_id(f"preupload:{name}")
    stream_id = f"person-enrollment-{person_id.rsplit(':', 1)[-1]}"
    evidence = await app_state.capture.store_image(
        device_id="web-user",
        stream_id=stream_id,
        index=captured_at_ms,
        captured_at_ms=captured_at_ms,
        device_monotonic_ms=None,
        server_received_at_ms=captured_at_ms,
        suffix=suffix,
        body=body,
        width=None,
        height=None,
    )
    job = await app_state.identity_perception.submit_image(
        evidence_id=evidence.evidence_id,
        image_path=str(evidence.path.resolve()),
        media_type="image/png" if suffix == "png" else "image/jpeg",
        captured_at_ms=evidence.captured_at_ms,
        boot_session_id="web-person-enrollment",
        window_id=stream_id,
    )
    completed = await _wait_for_identity_job(str(job["job_id"]))
    if completed.get("status") != "ready":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "enrollment image did not produce a usable face",
                "job_status": completed.get("status"),
                "error_code": completed.get("error_code"),
            },
        )
    observations = app_state.identity_job_store.observations_for_job(str(job["job_id"]))
    eligible = [
        item
        for item in observations
        if bool((item.get("quality") or {}).get("eligible_for_match"))
    ]
    if len(eligible) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "enrollment requires exactly one eligible face",
                "eligible_face_count": len(eligible),
                "detected_face_count": len(observations),
            },
        )
    assignment = app_state.identity_directory.assignment_for_observation(
        str(eligible[0]["observation_id"])
    )
    if not assignment or not assignment.get("candidate_id"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="enrollment face has no anonymous candidate assignment",
        )
    candidate_id = str(assignment["candidate_id"])
    confirmation = app_state.identity_directory.confirm_candidate(
        candidate_id=candidate_id,
        person_id=person_id,
        display_name=name,
    )
    alias_values = [item.strip() for item in aliases.split(",") if item.strip()]
    everos_session_id = f"identity-preupload-{int(time.time() * 1000)}"
    profile = app_state.memory_review_store.upsert_identity_profile(
        person_id=person_id,
        name=name,
        aliases=alias_values,
        relation=relation or None,
        organization=organization or None,
        role=role or None,
        notes=notes or None,
        face_candidate_ids=[candidate_id],
        voice_candidate_ids=[],
        source_refs=[evidence.evidence_id],
        source="user_preupload_photo",
        everos_session_id=everos_session_id,
    )
    writeback = await _write_text_back_to_everos(
        everos_session_id,
        "用户预上传人物档案。\n"
        f"姓名：{name}\n关系：{relation}\n组织：{organization}\n"
        f"角色：{role}\n备注：{notes}\n来源证据：{evidence.evidence_id}",
    )
    return {
        "profile": profile,
        "confirmation": confirmation,
        "identity_job": completed,
        "everos_writeback": writeback,
        "automatic_real_name_assignment": False,
    }


@router.get("/v1/memory/capsules")
async def list_capsules(
    authorization: str | None = Header(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    _require_auth(authorization)
    snapshot = app_state.memory_review_store.snapshot()
    people = _person_names(snapshot.get("profiles", []))
    session = app_state.memory_review_store.active_boot_session(
        user_id=app_state.settings.everos_user_id,
    )
    return {
        "boot_session": session,
        "items": [
            _resolve_capsule_identities(item, people=people)
            for item in snapshot["capsules"][:limit]
        ],
        "identity_observations": snapshot["identity_observations"][:limit],
        "meeting_evidence": [
            _resolve_capsule_identities(item, people=people)
            for item in snapshot["meeting_evidence"][:limit]
        ],
        "event_queues": snapshot.get("event_queues", []),
    }


@router.post("/v1/memory/capsules")
async def add_capsule(
    request: MemoryCapsuleRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    boot_session = app_state.memory_review_store.current_boot_session(
        user_id=app_state.settings.everos_user_id,
        captured_at_ms=request.captured_at_ms,
    )
    boot_session_id = str(boot_session["id"])
    event_type = _capsule_event_type(request)
    identity_projection = IdentityCandidateAggregator(
        app_state.memory_review_store,
    ).ingest_window(
        boot_session_id=boot_session_id,
        window_id=request.window_id,
        captured_at_ms=request.captured_at_ms,
        visible_people=request.visible_people,
        audio_speakers=request.audio_speakers,
    )
    visible_people = identity_projection["visible_people"]
    audio_speakers = identity_projection["audio_speakers"]
    caption = request.first_person_caption.strip()
    event_queue_id = None
    if caption:
        projection_result = app_state.memory_review_store.apply_event_projection(
            boot_session_id=boot_session_id,
            window_id=request.window_id,
            captured_at_ms=request.captured_at_ms,
            window_interpretation={
                "window_id": request.window_id,
                "first_person_caption": caption,
                "evidence_refs": [
                    str(item.get("id") or item.get("uri") or "")
                    for item in request.evidence
                    if item.get("id") or item.get("uri")
                ],
                "interpretation_status": "completed",
            },
            projection={
                "contract_version": "semantic-session-boundary-v1",
                "status": "completed",
                "contract_valid": True,
                "stabilizer_mode": "manual_capsule_api",
                "queue_action": "continue",
                "corrected_caption": caption,
                "boundary_reason": "",
                "sealed_event_summary": "",
                "source_window_ids": [request.window_id],
            },
        )
        event_queue_id = projection_result["projection"]["event_queue_id"]
        writeback = {
            "status": "waiting_event_boundary",
            "stage": "event_queue",
            "session_id": boot_session_id,
            "event_queue_id": event_queue_id,
            "attempt_count": 0,
        }
    else:
        writeback = {
            "status": "skipped",
            "stage": "experience_interpretation",
            "session_id": boot_session_id,
            "reason": "first_person_caption_unavailable",
        }
    capsule = app_state.memory_review_store.add_capsule(
        {
            "boot_session_id": boot_session_id,
            "window_id": request.window_id,
            "captured_at_ms": request.captured_at_ms,
            "duration_ms": request.duration_ms,
            "scene": request.scene,
            "activity": request.activity,
            "event_type": event_type,
            "meeting_likelihood": request.meeting_likelihood,
            "text": caption,
            "event_queue_id": event_queue_id,
            "visible_people": visible_people,
            "audio_speakers": audio_speakers,
            "objects": request.objects,
            "evidence": request.evidence,
            "everos_writeback": writeback,
        }
    )
    app_state.memory_review_store.touch_boot_session(
        session_id=boot_session_id,
        captured_at_ms=request.captured_at_ms,
    )

    identity_observations = []
    for channel, people in (("visible", visible_people), ("audio", audio_speakers)):
        for item in people:
            name = _capsule_person_name(item)
            if not name:
                continue
            existing_id = item.get("identity_observation_id")
            if existing_id:
                identity_observations.append(
                    {
                        "id": existing_id,
                        "name": name,
                        "channel": channel,
                        "boot_session_id": boot_session_id,
                        "window_id": request.window_id,
                        "captured_at_ms": request.captured_at_ms,
                        "confidence": item.get("confidence"),
                        "source": item.get("source"),
                        "evidence_id": item.get("evidence_id"),
                    }
                )

    object_observations = []
    for item in request.objects:
        label = _capsule_object_label(item)
        if not label:
            continue
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.5
        object_observations.append(
            app_state.memory_review_store.add_object_observation(
                object_label=label,
                session_id=boot_session_id,
                evidence_id=str(item.get("evidence_id") or request.window_id),
                image_uri=str(item.get("image_uri") or item.get("uri") or ""),
                captured_at_ms=request.captured_at_ms,
                confidence=max(0.0, min(1.0, float(confidence))),
                sequence=item.get("sequence"),
                location_hint=item.get("location_hint") or item.get("location"),
            )
        )

    meeting_evidence = None
    if event_type == "meeting":
        meeting = request.meeting or {}
        meeting_evidence = app_state.memory_review_store.add_meeting_evidence(
            {
                "boot_session_id": boot_session_id,
                "window_id": request.window_id,
                "captured_at_ms": request.captured_at_ms,
                "summary": meeting.get("summary") or request.first_person_caption,
                "commitments": meeting.get("commitments") or [],
                "transcript_excerpt": meeting.get("transcript_excerpt") or "",
                "visible_people": visible_people,
                "audio_speakers": audio_speakers,
                "evidence": request.evidence,
            }
        )

    return {
        "capsule": capsule,
        "boot_session": app_state.memory_review_store.active_boot_session(
            user_id=app_state.settings.everos_user_id,
        ),
        "identity_observations": identity_observations,
        "object_observations": object_observations,
        "meeting_evidence": meeting_evidence,
        "everos_writeback": writeback,
        "flush_writeback": None,
    }


@router.post("/v1/memory/capsules/flush")
async def flush_capsules(
    request: MemoryCapsuleFlushRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    session_id = request.session_id
    if not session_id:
        session = app_state.memory_review_store.active_boot_session(
            user_id=app_state.settings.everos_user_id,
        )
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no active boot session")
        session_id = str(session["id"])
    flushed_at_ms = request.flushed_at_ms or int(time.time() * 1000)
    canonical_writer = app_state.memory_capsule_bridge
    if (
        canonical_writer.review_store is app_state.memory_review_store
        and canonical_writer.everos is app_state.everos
    ):
        event_writer = canonical_writer
    else:
        event_writer = EverOSCapsuleBridge(
            raw_media_root=app_state.memory_review_store.path.parent / "event-outbox",
            converter=app_state.media_converter,
            everos=app_state.everos,
            review_store=app_state.memory_review_store,
            user_id=app_state.settings.everos_user_id,
            sender_name="眼镜用户",
            event_context_stabilizer=app_state.event_context_stabilizer,
        )
    submissions = await event_writer.finalize_open_event(
        boot_session_id=session_id,
        sealed_at_ms=flushed_at_ms,
        reason="explicit_capsule_flush",
    )
    writeback = (
        submissions[-1]["writeback"]
        if submissions
        else {
            "status": "skipped",
            "session_id": session_id,
            "reason": "no_active_event",
        }
    )
    return {"session_id": session_id, "everos_writeback": writeback}


@router.get("/v1/memory/evidence-file")
async def evidence_file(
    uri: str = Query(min_length=1),
    authorization: str | None = Header(default=None),
) -> FileResponse:
    _require_auth(authorization)
    resolved = _evidence_path(uri)
    if not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="evidence not found")
    return FileResponse(
        resolved,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/v1/memory/evidence")
async def evidence_detail(
    authorization: str | None = Header(default=None),
    window_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=100),
) -> dict[str, Any]:
    """Resolve a Web card back to its real Capsule evidence and processing trail."""

    _require_auth(authorization)
    if not window_id and not session_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="window_id or session_id is required",
        )
    snapshot = app_state.memory_review_store.snapshot()
    matches = [
        item
        for item in snapshot.get("capsules", [])
        if (window_id and item.get("window_id") == window_id)
        or (
            session_id
            and session_id in {item.get("boot_session_id"), item.get("window_id")}
        )
    ][:limit]
    if not matches:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="capsule evidence not found")

    capsules: list[dict[str, Any]] = []
    people = _person_names(snapshot.get("profiles", []))
    total = 0
    available = 0
    for item in matches:
        # ASR/VAD runs are processing metadata, not raw media files. Keep them
        # in ``processing`` below so the transcript stays visible, but do not
        # count a URI-less logical run as a missing evidence file.
        evidence = [
            _evidence_item(value)
            for value in item.get("evidence", [])
            if str(value.get("uri") or "").strip()
        ]
        total += len(evidence)
        available += sum(1 for value in evidence if value["available"])
        manifest_uri = str(item.get("manifest") or "") or None
        if not manifest_uri and item.get("window_id"):
            inferred = (
                Path(app_state.settings.raw_media_dir)
                / app_state.settings.everos_user_id
                / str(item["window_id"])
                / "capsule-manifest.json"
            )
            if inferred.is_file():
                manifest_uri = str(inferred)
        manifest = _manifest_summary(manifest_uri)
        manifest_processing = (
            manifest.get("processing")
            if isinstance(manifest, dict) and isinstance(manifest.get("processing"), dict)
            else {}
        )
        image_evidence_ids = [
            str(value.get("id") or "")
            for value in item.get("evidence", [])
            if value.get("kind") == "image" and value.get("id")
        ]
        identity_perception = item.get("identity_perception") or {}
        identity_projection = getattr(
            app_state, "production_identity_recognizer", None
        )
        if identity_projection is not None and image_evidence_ids:
            # Resolve at request time so jobs completed after Capsule creation
            # become visible without rewriting the historical MiMo input.
            identity_perception = identity_projection.evidence_status(
                image_evidence_ids
            )
        voice_perception = item.get("voice_perception") or {}
        voice_projection = getattr(
            app_state, "production_voice_recognizer", None
        )
        if voice_projection is not None and item.get("window_id"):
            # Voice work may finish after the Capsule and EverOS write. Resolve
            # the latest public projection without rewriting historical MiMo input.
            voice_perception = voice_projection.evidence_status(
                str(item["window_id"])
            )
        resolved_audio_speakers = app_state.voice_directory.resolve_audio_speakers(
            list(
                voice_perception.get("audio_speakers")
                or item.get("audio_speakers")
                or []
            ),
            people=people,
        )
        if voice_perception:
            voice_perception = {
                **voice_perception,
                "audio_speakers": resolved_audio_speakers,
            }
        capsules.append(
            {
                "id": item.get("id"),
                "window_id": item.get("window_id"),
                "boot_session_id": item.get("boot_session_id"),
                "captured_at_ms": item.get("captured_at_ms"),
                "event_type": item.get("event_type"),
                "dataset_source": item.get("dataset_source"),
                "evaluation_proxy": bool(item.get("evaluation_proxy", False)),
                "scene": item.get("scene"),
                "activity": item.get("activity"),
                "text": item.get("text"),
                "audio_speakers": resolved_audio_speakers,
                "evidence": evidence,
                "manifest": manifest,
                "processing": {
                    "identity_perception": identity_perception
                    or manifest_processing.get("identity_perception")
                    or {},
                    "voice_perception": voice_perception
                    or manifest_processing.get("voice_perception")
                    or {},
                    "object_perception": manifest_processing.get("object_perception")
                    or (item.get("technical_window") or {}).get("object_perception")
                    or {},
                    "object_cards": manifest_processing.get("object_cards") or {},
                    "audio_presence": item.get("audio_presence") or {},
                    "asr": item.get("asr") or {},
                    "experience_interpretation": item.get("interpretation") or {},
                    "scene_interpretation": item.get("interpretation") or {},
                    "context_stabilization": item.get("stabilized_projection") or {},
                    "everos_writeback": item.get("everos_writeback") or {},
                },
            }
        )
    return {
        "query": {"window_id": window_id, "session_id": session_id},
        "capsules": capsules,
        "summary": {
            "capsule_count": len(capsules),
            "evidence_count": total,
            "available_count": available,
            "missing_count": total - available,
        },
    }


@router.get("/v1/memory/voice/status")
async def voice_status(
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Expose public speaker jobs/candidates without vectors or WAV paths."""

    _require_auth(authorization)
    coordinator = getattr(app_state, "voice_perception", None)
    if coordinator is None:
        return {"status": "disabled", "jobs": [], "candidates": []}
    health = await coordinator.health()
    directory = app_state.voice_directory.public_snapshot()
    return {
        "status": "available",
        "health": health,
        "jobs": app_state.voice_job_store.recent_jobs(limit=limit),
        "candidates": directory.get("candidates", [])[:limit],
        "assignments": directory.get("assignments", [])[:limit],
    }


@router.post("/v1/memory/corrections")
async def correct_memory(
    request: MemoryCorrectionRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_auth(authorization)
    try:
        field_level = bool(request.target_type or request.target_id or request.field_path)
        if field_level:
            if not request.target_type or not request.target_id or not request.field_path:
                raise ValueError("target_type, target_id and field_path are required together")
            key = idempotency_key or request.idempotency_key or f"web:{uuid.uuid4().hex}"
            correction = app_state.memory_review_store.upsert_correction(
                idempotency_key=key,
                target_type=request.target_type,
                target_id=request.target_id,
                field_path=request.field_path,
                old_value=request.old_value,
                new_value=request.new_value,
                decision_status=request.status,
                evidence_refs=request.evidence_refs,
                note=request.note,
                session_id=request.session_id,
            )
        else:
            if not request.source_id:
                raise ValueError("source_id is required for a legacy correction")
            if request.status == "confirmed" and not str(request.corrected_content or "").strip():
                raise ValueError("corrected_content is required for a confirmed correction")
            everos_session_id = f"review-correction-{int(time.time() * 1000)}"
            correction = app_state.memory_review_store.add_correction(
                source_id=request.source_id,
                session_id=request.session_id,
                original_content=request.original_content,
                corrected_content=request.corrected_content or "",
                status=request.status,
                note=request.note,
                everos_session_id=everos_session_id,
            )
        app_state.correction_writeback.timeout_seconds = _EVEROS_WRITEBACK_TIMEOUT_S
        persisted = await app_state.correction_writeback.process(str(correction["id"]))
        persisted = {
            **persisted,
            "idempotent": bool(correction.get("idempotent", False)),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "correction": persisted,
        "everos_writeback": _correction_writeback_response(persisted),
    }


@router.get("/v1/memory/corrections")
async def list_memory_corrections(
    authorization: str | None = Header(default=None),
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    writeback_status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    _require_auth(authorization)
    values = app_state.memory_review_store.snapshot().get("corrections", [])
    if target_type:
        values = [item for item in values if item.get("target_type") == target_type]
    if target_id:
        values = [item for item in values if item.get("target_id") == target_id]
    if writeback_status:
        values = [
            item for item in values if item.get("writeback_status") == writeback_status
        ]
    return {"corrections": values[:limit], "count": min(len(values), limit)}


@router.get("/v1/memory/corrections/{correction_id}")
async def get_memory_correction(
    correction_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    item = app_state.memory_review_store.correction_by_id(correction_id)
    if item is None:
        raise HTTPException(status_code=404, detail="correction not found")
    return {"correction": item}


@router.post("/v1/memory/corrections/{correction_id}/retry")
async def retry_memory_correction(
    correction_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    try:
        item = await app_state.correction_writeback.process(correction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="correction not found") from exc
    return {
        "correction": item,
        "everos_writeback": _correction_writeback_response(item),
    }


@router.post("/v1/memory/corrections/{correction_id}/revert")
async def revert_memory_correction(
    correction_id: str,
    request: MemoryCorrectionRevertRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_auth(authorization)
    try:
        reverted = app_state.memory_review_store.revert_correction(
            correction_id,
            idempotency_key=(
                idempotency_key
                or request.idempotency_key
                or f"web-revert:{uuid.uuid4().hex}"
            ),
            note=request.note,
        )
        item = await app_state.correction_writeback.process(str(reverted["id"]))
        item = {**item, "idempotent": bool(reverted.get("idempotent", False))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="correction not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "correction": item,
        "everos_writeback": _correction_writeback_response(item),
    }


@router.get("/v1/memory/people")
async def list_people(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    review = app_state.memory_review_store.snapshot()
    return {
        "profiles": review["profiles"],
        "frozen_candidates": review["frozen_candidates"],
    }


@router.post("/v1/memory/people/confirm")
async def confirm_person(
    request: PersonConfirmRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    everos_session_id = f"profile-confirm-{int(time.time() * 1000)}"
    profile = app_state.memory_review_store.confirm_person(
        candidate_name=request.candidate_name,
        confirmed_name=request.confirmed_name,
        relation=request.relation,
        notes=request.notes,
        source_session_ids=request.source_session_ids,
        everos_session_id=everos_session_id,
    )
    text = (
        "Person profile confirmed by Web reviewer.\n"
        f"candidate_name: {request.candidate_name}\n"
        f"confirmed_name: {request.confirmed_name}\n"
        f"relation: {request.relation or ''}\n"
        f"notes: {request.notes or ''}\n"
        f"source_session_ids: {', '.join(request.source_session_ids)}"
    )
    writeback = await _write_text_back_to_everos(everos_session_id, text)
    return {"profile": profile, "everos_writeback": writeback}


@router.post("/v1/memory/people/freeze")
async def freeze_person_candidate(
    request: PersonFreezeRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    frozen = app_state.memory_review_store.freeze_candidate(
        candidate_name=request.candidate_name,
        reason=request.reason,
        source_session_ids=request.source_session_ids,
    )
    return {"frozen_candidate": frozen}


@router.post("/v1/memory/objects/observations")
async def add_object_observation(
    request: ObjectObservationRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    observation = app_state.memory_review_store.add_object_observation(
        object_label=request.object_label,
        session_id=request.session_id,
        evidence_id=request.evidence_id,
        image_uri=request.image_uri,
        captured_at_ms=request.captured_at_ms,
        confidence=request.confidence,
        sequence=request.sequence,
        location_hint=request.location_hint,
    )
    uncertainty = observation.get("uncertainty") or (
        "low"
        if request.confidence >= 0.85
        else "medium"
        if request.confidence >= 0.6
        else "high"
    )
    text = (
        "Visual object observation confirmed by bridge.\n"
        f"object_label: {request.object_label}\n"
        f"session_id: {request.session_id}\n"
        f"evidence_id: {request.evidence_id}\n"
        f"image_uri: {request.image_uri}\n"
        f"location_hint: {request.location_hint or ''}\n"
        f"confidence: {request.confidence:.2f}\n"
        f"uncertainty: {uncertainty}"
    )
    everos_session_id = f"object-observation-{int(time.time() * 1000)}"
    writeback = await _write_text_back_to_everos(everos_session_id, text)
    return {"observation": observation, "everos_writeback": writeback}


@router.get("/v1/memory/object-perception")
async def object_perception_status(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    review = app_state.memory_review_store.snapshot()
    coordinator = app_state.object_perception
    if coordinator is None:
        health: dict[str, Any] = {
            "worker": {"status": "disabled"},
            "jobs": {"queue_depth": 0, "counts": {}},
        }
    else:
        try:
            health = await coordinator.health()
        except Exception as exc:
            health = {
                "worker": {
                    "status": "unavailable",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                "jobs": app_state.object_perception_store.summary(),
            }
    candidates = review.get("object_candidate_observations", [])
    confirmed = review.get("confirmed_objects", [])
    return {
        "enabled": coordinator is not None,
        **health,
        "candidate_count": len(candidates),
        "confirmed_count": len(confirmed),
        "recent_candidates": candidates[:20],
        "confirmed_objects": confirmed,
    }


@router.post("/v1/memory/objects/confirmed")
async def confirm_object_vocabulary(
    request: ConfirmedObjectRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    item = app_state.memory_review_store.upsert_confirmed_object(
        label=request.label,
        prompt=request.prompt,
        aliases=request.aliases,
        personal_object_id=request.personal_object_id,
        visible_description=request.visible_description,
    )
    return {
        "object": item,
        "applies_to": "future_jobs_only",
    }


@router.get("/v1/memory/objects/last-seen")
async def last_seen_object(
    authorization: str | None = Header(default=None),
    query: str = Query(min_length=1),
) -> dict[str, Any]:
    _require_auth(authorization)
    result = app_state.memory_review_store.query_last_seen_object(query)
    latest = result.get("latest_reliable")
    if latest is None:
        patch = app_state.cards.memory_patch(1, result["answer"])
        return {
            **result,
            "answer_text": result["answer"],
            "answer": None,
            "evidence_sequence": result.get("later_uncertain", []),
            "ui_patch": patch.model_dump(mode="json"),
        }
    answer_text = result["answer"]
    sequence = [
        *reversed(result.get("other_candidates", [])),
        latest,
        *result.get("later_uncertain", []),
    ]
    patch = app_state.cards.memory_patch(1, answer_text)
    return {
        **result,
        "answer_text": answer_text,
        "answer": latest,
        "evidence_sequence": sequence,
        "ui_patch": patch.model_dump(mode="json"),
    }


def _commitment_by_id(commitment_id: str) -> dict[str, Any]:
    item = next(
        (
            value
            for value in app_state.memory_review_store.snapshot().get("commitments", [])
            if str(value.get("commitment_id") or value.get("id") or "")
            == commitment_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="commitment not found")
    return item


async def _apply_todo_changes(
    todo_id: str,
    *,
    changes: list[tuple[str, Any]],
    idempotency_key: str,
    note: str,
) -> dict[str, Any]:
    current = _commitment_by_id(todo_id)
    evidence_refs = list(current.get("evidence_refs") or [f"todo://{todo_id}"])
    persisted = []
    writebacks = []
    working = dict(current)
    for field, new_value in changes:
        old_value = working.get(field)
        if old_value == new_value:
            continue
        correction = app_state.memory_review_store.upsert_correction(
            idempotency_key=f"{idempotency_key}:{field}",
            target_type="commitment",
            target_id=todo_id,
            field_path=field,
            old_value=old_value,
            new_value=new_value,
            decision_status="confirmed",
            evidence_refs=evidence_refs,
            note=note,
        )
        applied = await app_state.correction_writeback.process(str(correction["id"]))
        persisted.append(applied)
        writebacks.append(_correction_writeback_response(applied))
        working[field] = new_value
    return {
        "todo": _commitment_by_id(todo_id),
        "corrections": persisted,
        "everos_writebacks": writebacks,
        "external_actions_executed": 0,
    }


@router.post("/v1/memory/commitments/extract")
async def extract_commitment_candidates(
    request: CommitmentExtractRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Run the independent text-only pass; model output remains candidate-only."""

    _require_auth(authorization)
    extractor = app_state.commitment_extractor
    if hasattr(extractor, "store"):
        extractor.store = app_state.memory_review_store
    result = await extractor.process_window(
        window_id=request.window_id,
        capsule_id=request.capsule_id or f"capsule-{request.window_id}",
        captured_at_ms=request.captured_at_ms,
        transcript=request.transcript,
        audio_speakers=request.audio_speakers,
        evidence_refs=request.evidence_refs,
        meeting_id=request.meeting_id,
    )
    return result


@router.get("/v1/memory/commitments")
async def list_commitments(
    authorization: str | None = Header(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    due_bucket: str | None = Query(default=None),
    owner_person_id: str | None = Query(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    values = []
    for source in app_state.memory_review_store.snapshot().get("commitments", []):
        item = {**source, "due_bucket": commitment_due_bucket(source.get("normalized_due_at"))}
        if status_filter and item.get("status") != status_filter:
            continue
        if due_bucket and item.get("due_bucket") != due_bucket:
            continue
        if owner_person_id and item.get("owner_person_id") != owner_person_id:
            continue
        values.append(item)
    order = {"overdue": 0, "today": 1, "upcoming": 2, "later": 3, "no_due": 4}
    values.sort(
        key=lambda item: (
            order.get(str(item.get("due_bucket")), 9),
            str(item.get("normalized_due_at") or "9999"),
            str(item.get("created_at") or ""),
        )
    )
    counts = {key: 0 for key in order}
    status_counts: dict[str, int] = {}
    for item in values:
        counts[str(item["due_bucket"])] += 1
        state = str(item.get("status") or "candidate")
        status_counts[state] = status_counts.get(state, 0) + 1
    return {
        "commitments": values,
        "summary": {
            "total": len(values),
            "by_status": status_counts,
            "by_due_bucket": counts,
            "external_actions_executed": 0,
        },
    }


@router.post("/v1/memory/commitments/{commitment_id}/actions")
async def act_on_commitment(
    commitment_id: str,
    request: CommitmentActionRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_auth(authorization)
    current = _commitment_by_id(commitment_id)
    state = str(current.get("status") or "candidate")
    transitions = {
        "confirm": ({"candidate"}, "confirmed"),
        "complete": ({"confirmed"}, "done"),
        "dismiss": ({"candidate", "confirmed"}, "dismissed"),
        "reopen": ({"done", "dismissed"}, "confirmed"),
        "update": ({"candidate", "confirmed"}, state),
    }
    allowed, next_state = transitions[request.action]
    if state not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"cannot {request.action} commitment in {state} state",
        )

    fields_set = request.model_fields_set
    changes: list[tuple[str, Any]] = []
    for field in ("owner_person_id", "text", "due_hint", "normalized_due_at"):
        if field in fields_set:
            changes.append((field, getattr(request, field)))
    if next_state != state:
        changes.append(("status", next_state))
    if not changes:
        return {"commitment": current, "corrections": [], "everos_writebacks": []}

    root_key = (
        idempotency_key
        if isinstance(idempotency_key, str) and idempotency_key.strip()
        else f"commitment-web:{uuid.uuid4().hex}"
    )
    evidence_refs = list(current.get("evidence_refs") or [])
    persisted = []
    writebacks = []
    working = dict(current)
    try:
        for field, new_value in changes:
            old_value = working.get(field)
            if old_value == new_value:
                continue
            correction = app_state.memory_review_store.upsert_correction(
                idempotency_key=f"{root_key}:{field}",
                target_type="commitment",
                target_id=commitment_id,
                field_path=field,
                old_value=old_value,
                new_value=new_value,
                decision_status="confirmed",
                evidence_refs=evidence_refs,
                note=request.note or f"Web commitment action: {request.action}",
            )
            applied = await app_state.correction_writeback.process(str(correction["id"]))
            persisted.append(applied)
            writebacks.append(_correction_writeback_response(applied))
            working[field] = new_value
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "commitment": _commitment_by_id(commitment_id),
        "corrections": persisted,
        "everos_writebacks": writebacks,
        "external_actions_executed": 0,
    }


@router.get("/v1/memory/todos")
async def list_todos(
    authorization: str | None = Header(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> dict[str, Any]:
    _require_auth(authorization)
    items = []
    for source in app_state.memory_review_store.list_todos():
        item = {
            **source,
            "todo_id": str(source.get("id") or source.get("commitment_id") or ""),
            "due_bucket": commitment_due_bucket(source.get("normalized_due_at")),
        }
        if status_filter and item.get("status") != status_filter:
            continue
        items.append(item)
    return {
        "todos": items,
        "summary": {
            "total": len(items),
            "by_status": {
                state: sum(1 for item in items if item.get("status") == state)
                for state in sorted({str(item.get("status") or "") for item in items})
            },
            "external_actions_executed": 0,
        },
    }


@router.post("/v1/memory/todos", status_code=201)
async def create_todo(
    request: TodoCreateRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_auth(authorization)
    key = (
        idempotency_key.strip()
        if isinstance(idempotency_key, str) and idempotency_key.strip()
        else f"todo-create:{uuid.uuid4().hex}"
    )
    try:
        todo = app_state.memory_review_store.create_user_todo(
            text=request.text,
            due_at=request.normalized_due_at,
            priority=request.priority,
            owner_person_id=request.owner_person_id,
            idempotency_key=key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"todo": todo, "external_actions_executed": 0}


@router.patch("/v1/memory/todos/{todo_id}")
async def update_todo(
    todo_id: str,
    request: TodoUpdateRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_auth(authorization)
    _commitment_by_id(todo_id)
    key = (
        idempotency_key.strip()
        if isinstance(idempotency_key, str) and idempotency_key.strip()
        else f"todo-update:{uuid.uuid4().hex}"
    )
    fields_set = request.model_fields_set
    changes = [
        (field, getattr(request, field))
        for field in ("text", "normalized_due_at", "priority", "owner_person_id")
        if field in fields_set
    ]
    try:
        return await _apply_todo_changes(
            todo_id,
            changes=changes,
            idempotency_key=key,
            note="用户修改长期待办",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v1/memory/todos/{todo_id}/actions")
async def act_on_todo(
    todo_id: str,
    request: TodoActionRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_auth(authorization)
    current = _commitment_by_id(todo_id)
    state = str(current.get("status") or "candidate")
    transitions = {
        "confirm": ({"candidate"}, "open"),
        "start": ({"confirmed", "open"}, "in_progress"),
        "complete": (
            {"confirmed", "open", "in_progress", "suspected_completed"},
            "completed",
        ),
        "confirm_completion": ({"suspected_completed"}, "completed"),
        "reject_completion": ({"suspected_completed"}, "in_progress"),
        "cancel": (
            {"candidate", "confirmed", "open", "in_progress", "suspected_completed"},
            "cancelled",
        ),
        "reopen": ({"done", "completed", "dismissed", "cancelled"}, "open"),
    }
    allowed, next_state = transitions[request.action]
    if state not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"cannot {request.action} todo in {state} state",
        )
    key = (
        idempotency_key.strip()
        if isinstance(idempotency_key, str) and idempotency_key.strip()
        else f"todo-action:{uuid.uuid4().hex}"
    )
    result = await _apply_todo_changes(
        todo_id,
        changes=[("status", next_state)],
        idempotency_key=key,
        note=request.note or f"用户待办操作：{request.action}",
    )
    app_state.memory_review_store.record_todo_user_event(
        todo_id=todo_id,
        event_type=next_state,
        idempotency_key=key,
    )
    return result


@router.delete("/v1/memory/todos/{todo_id}")
async def delete_todo(
    todo_id: str,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_auth(authorization)
    key = (
        idempotency_key.strip()
        if isinstance(idempotency_key, str) and idempotency_key.strip()
        else f"todo-delete:{uuid.uuid4().hex}"
    )
    try:
        deleted = app_state.memory_review_store.delete_todo(
            todo_id,
            idempotency_key=key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="todo not found") from exc
    return {"deleted": deleted, "external_actions_executed": 0}


@router.post("/v1/memory/meetings/extract")
async def extract_meeting_memory(
    request: MeetingExtractRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    turns = _parse_speaker_turns(request.transcript, request.speaker_hints)
    conclusions = _extract_conclusions(turns)
    commitments = _extract_commitments(turns)
    meeting = {
        "id": f"meeting-{request.session_id}",
        "session_id": request.session_id,
        "speaker_turns": turns,
        "conclusions": conclusions,
        "commitments": commitments,
        "transcript": request.transcript,
        "created_at_ms": int(time.time() * 1000),
    }
    app_state.memory_review_store.add_meeting(meeting)
    body = (
        "会议摘要\n"
        f"结论：{'；'.join(conclusions) if conclusions else '暂无明确结论'}\n"
        f"承诺：{'；'.join(item['text'] for item in commitments) if commitments else '暂无明确承诺'}"
    )
    everos_session_id = f"meeting-summary-{int(time.time() * 1000)}"
    writeback = await _write_text_back_to_everos(
        everos_session_id,
        "Meeting summary extracted by bridge.\n" + body,
    )
    patch = app_state.cards.memory_patch(1, body)
    return {
        "meeting": meeting,
        "ui_patch": patch.model_dump(mode="json"),
        "everos_writeback": writeback,
    }


@router.post("/v1/memory/people/preupload")
async def preupload_person(
    request: PeoplePreuploadRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    everos_session_id = f"person-preupload-{int(time.time() * 1000)}"
    profile = app_state.memory_review_store.preupload_person(
        name=request.name,
        aliases=request.aliases,
        relation=request.relation,
        notes=request.notes,
        reminder_threshold=request.reminder_threshold,
        quiet_hours=request.quiet_hours,
        everos_session_id=everos_session_id,
    )
    text = (
        "Person profile preuploaded by user.\n"
        f"name: {request.name}\n"
        f"aliases: {', '.join(request.aliases)}\n"
        f"relation: {request.relation or ''}\n"
        f"notes: {request.notes or ''}\n"
        f"reminder_threshold: {request.reminder_threshold:.2f}"
    )
    writeback = await _write_text_back_to_everos(everos_session_id, text)
    return {"profile": profile, "everos_writeback": writeback}


@router.post("/v1/memory/reminders/evaluate")
async def evaluate_reminder(
    request: ReminderEvaluateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    person = app_state.memory_review_store.find_person(request.person_name)
    if person is None:
        item = {
            "person_name": request.person_name,
            "decision": "suppress",
            "reason": "unknown_person",
            "score": request.score,
            "local_time": request.local_time,
        }
        app_state.memory_review_store.add_reminder_evaluation(item)
        return {**item, "person": None}

    threshold = float(person.get("reminder_threshold") or 0.75)
    if request.score < threshold:
        decision = "suppress"
        reason = "below_threshold"
    elif _in_quiet_hours(request.local_time, person.get("quiet_hours") or {}):
        decision = "suppress"
        reason = "quiet_hours"
    else:
        decision = "remind"
        reason = request.reason or "threshold_met"
    item = {
        "person_name": request.person_name,
        "decision": decision,
        "reason": reason,
        "score": request.score,
        "threshold": threshold,
        "local_time": request.local_time,
        "evaluated_at_ms": int(time.time() * 1000),
    }
    app_state.memory_review_store.add_reminder_evaluation(item)
    return {**item, "person": person}


@router.get("/v1/memory/daily-reports")
async def list_daily_report_days(
    authorization: str | None = Header(default=None),
    limit: int = Query(default=90, ge=1, le=366),
) -> dict[str, Any]:
    _require_auth(authorization)
    days = app_state.memory_review_store.daily_report_days(limit=limit)
    return {"days": days, "total": len(days)}


@router.get("/v1/memory/daily-reports/{report_date}")
async def get_daily_report_version(
    report_date: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    try:
        date_type = datetime.fromisoformat(report_date).date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD") from exc
    if date_type.isoformat() != report_date:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    report = app_state.memory_review_store.current_daily_report(report_date)
    if report is None:
        raise HTTPException(status_code=404, detail="daily report not generated")
    return {"daily_report": report}


@router.get("/v1/memory/daily-reports/{report_date}/versions")
async def get_daily_report_versions(
    report_date: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    return {
        "date": report_date,
        "versions": app_state.memory_review_store.daily_report_versions(report_date),
    }


@router.post("/v1/memory/daily-reports/{report_date}/generate")
async def generate_daily_report(
    report_date: str,
    request: DailyReportGenerateRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _require_auth(authorization)
    try:
        report = await app_state.daily_review.generate(
            report_date,
            generation_type=request.generation_type,
            idempotency_key=(
                idempotency_key.strip()
                if isinstance(idempotency_key, str) and idempotency_key.strip()
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD") from exc
    return {"daily_report": report, "job_id": report["id"]}


@router.get("/v1/memory/daily-report-jobs/{job_id}")
async def get_daily_report_job(
    job_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    report = app_state.memory_review_store.daily_report_job(job_id)
    if report is None:
        raise HTTPException(status_code=404, detail="daily report job not found")
    return {"job": report}


@router.get("/v1/memory/daily-report")
async def daily_report(
    authorization: str | None = Header(default=None),
    date: str = Query(min_length=1),
) -> dict[str, Any]:
    _require_auth(authorization)
    report = app_state.memory_review_store.daily_report(date)
    patch = app_state.cards.memory_patch(1, _daily_report_text(report))
    return {**report, "ui_patch": patch.model_dump(mode="json")}


@router.post("/v1/memory/daily-report/close")
async def close_daily_report(
    request: DailyReportCloseRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_auth(authorization)
    everos_session_id = f"daily-report-{request.date}-{int(time.time() * 1000)}"
    closed = app_state.memory_review_store.close_daily_report(
        date=request.date,
        corrections=request.corrections,
        everos_session_id=everos_session_id,
    )
    report = app_state.memory_review_store.daily_report(request.date)
    writeback = await _write_text_back_to_everos(
        everos_session_id,
        "Daily report closed by Web reviewer.\n" + _daily_report_text(report, request.corrections),
    )
    return {"daily_report": closed, "everos_writeback": writeback}
