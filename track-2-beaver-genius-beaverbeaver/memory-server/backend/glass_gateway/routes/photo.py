from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from glass_gateway.app_state import app_state
from glass_gateway.auth import auth_registry
from glass_gateway.routes.upload_body import read_upload_body

router = APIRouter()

_SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]+")


def _authorized(authorization: str | None) -> bool:
    return auth_registry.authorized_device(authorization)


def _safe_part(value: str, default: str) -> str:
    cleaned = _SAFE_PART.sub("_", value).strip("._")
    return cleaned or default


def _parse_detected_objects(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        raw = raw.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid x-detected-objects json",
        ) from exc
    if not isinstance(payload, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="x-detected-objects must be a json array",
        )
    return [item for item in payload if isinstance(item, dict)]


@router.post("/v1/device/photo")
async def upload_photo(
    request: Request,
    authorization: str | None = Header(default=None),
    x_device_id: str = Header(default="unknown"),
    x_stream_id: str | None = Header(default=None),
    x_image_format: str = Header(default="bin"),
    x_width: int | None = Header(default=None),
    x_height: int | None = Header(default=None),
    x_sequence: int | None = Header(default=None),
    x_captured_at_ms: int | None = Header(default=None),
    x_device_monotonic_ms: int | None = Header(default=None),
    x_detected_objects: str | None = Header(default=None),
) -> dict[str, object]:
    if not _authorized(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    body = await read_upload_body(
        request,
        timeout_seconds=app_state.settings.device_upload_body_timeout_seconds,
        media_label="photo",
    )
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty photo body")

    fmt = _safe_part(x_image_format.lower(), "bin")
    if fmt in {"jpg", "jpeg", "image/jpeg"}:
        suffix = "jpg"
    elif fmt in {"png", "image/png"}:
        suffix = "png"
    elif fmt in {"nv12", "yuv"}:
        suffix = fmt
    else:
        suffix = "bin"

    device_id = _safe_part(x_device_id, "unknown")
    stream_id = _safe_part(x_stream_id or device_id, "photos")
    seq = x_sequence if x_sequence is not None else 0
    captured_at_ms = x_captured_at_ms if x_captured_at_ms is not None else 0
    evidence = await app_state.capture.store_image(
        device_id=device_id,
        stream_id=stream_id,
        index=seq,
        captured_at_ms=captured_at_ms,
        device_monotonic_ms=x_device_monotonic_ms,
        server_received_at_ms=app_state.capture.now_ms(),
        suffix=suffix,
        body=body,
        width=x_width,
        height=x_height,
    )

    # Keep the device's raw frame as authoritative evidence, but external
    # perception services only accept common encoded image formats.  Glasses
    # currently upload NV12, so derive one JPEG once and share it between the
    # object and face pipelines.  A conversion failure must never discard the
    # raw evidence or fail the upload request.
    perception_path: str | None = str(evidence.path.resolve())
    perception_media_type: str | None = (
        "image/png" if suffix == "png" else "image/jpeg" if suffix == "jpg" else None
    )
    perception_prepare_error: str | None = None
    if suffix in {"nv12", "yuv"}:
        if x_width and x_height:
            try:
                prepared = await asyncio.to_thread(
                    app_state.media_converter.nv12_to_jpeg,
                    evidence,
                    width=x_width,
                    height=x_height,
                )
                perception_path = str(prepared.path.resolve())
                perception_media_type = prepared.media_type
            except Exception as exc:
                perception_path = None
                perception_prepare_error = f"{type(exc).__name__}: {exc}"
        else:
            perception_path = None
            perception_prepare_error = "NV12 conversion requires x-width and x-height"
    elif perception_media_type is None:
        perception_path = None
        perception_prepare_error = f"unsupported image format: {suffix}"

    perception_job: dict[str, Any]
    context = app_state.capture.image_job_context(
        device_id=device_id,
        stream_id=stream_id,
    )
    if app_state.object_perception is None:
        perception_job = {"status": "not_requested", "reason": "disabled"}
    elif perception_path is None or perception_media_type is None:
        perception_job = {
            "status": "not_requested",
            "reason": "media_conversion_failed",
            "error": perception_prepare_error,
        }
    else:
        try:
            job = await app_state.object_perception.submit_image(
                evidence_id=evidence.evidence_id,
                image_path=perception_path,
                media_type=perception_media_type,
                captured_at_ms=evidence.captured_at_ms,
                window_id=context["window_id"],
                boot_session_key=context["boot_session_key"],
                width=x_width,
                height=x_height,
            )
            perception_job = {
                "job_id": job.get("job_id"),
                "status": job.get("status") or "pending",
            }
        except Exception as exc:
            # Raw evidence capture is authoritative; optional enrichment must
            # never turn a successful image upload into data loss.
            perception_job = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

    identity_job: dict[str, Any]
    if app_state.identity_perception is None:
        identity_job = {"status": "not_requested", "reason": "disabled"}
    elif perception_path is None or perception_media_type is None:
        identity_job = {
            "status": "not_requested",
            "reason": "media_conversion_failed",
            "error": perception_prepare_error,
        }
    else:
        try:
            job = await app_state.identity_perception.submit_image(
                evidence_id=evidence.evidence_id,
                image_path=perception_path,
                media_type=perception_media_type,
                captured_at_ms=evidence.captured_at_ms,
                boot_session_id=context["boot_session_key"],
                window_id=context["window_id"],
            )
            identity_job = {
                "job_id": job.get("job_id"),
                "status": job.get("status") or "pending",
            }
        except Exception as exc:
            # Face enrichment is optional. Persisting the photo remains the
            # successful, authoritative operation.
            identity_job = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

    object_observations: list[dict[str, Any]] = []
    for item in _parse_detected_objects(x_detected_objects):
        label = str(item.get("object_label") or item.get("label") or "").strip()
        if not label:
            continue
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            continue
        if confidence < 0 or confidence > 1:
            continue
        object_observations.append(
            app_state.memory_review_store.add_object_observation(
                object_label=label,
                session_id=stream_id,
                evidence_id=evidence.evidence_id,
                image_uri=str(evidence.path),
                captured_at_ms=evidence.captured_at_ms,
                confidence=confidence,
                sequence=seq,
                location_hint=item.get("location_hint"),
            )
        )

    return {
        "status": "ok",
        "path": str(evidence.path),
        "evidence_id": evidence.evidence_id,
        "bytes": len(body),
        "format": suffix,
        "width": x_width,
        "height": x_height,
        "sequence": x_sequence,
        "captured_at_ms": evidence.captured_at_ms,
        "device_monotonic_ms": evidence.device_monotonic_ms,
        "server_received_at_ms": evidence.server_received_at_ms,
        "server_anchor_ms": evidence.server_anchor_ms,
        "timezone_name": evidence.timezone_name,
        "capture_time_source": evidence.capture_time_source,
        "object_observations": object_observations,
        "object_perception": perception_job,
        "identity_perception": identity_job,
    }
