from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import struct
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from glass_gateway.app_state import app_state, app_state_registry
from glass_gateway.auth import auth_registry
from glass_gateway.routes.audio import _decode_wav
from glass_gateway.routes.upload_body import read_upload_body
from glass_gateway.schemas.device_protocol import AudioFormat
from glass_gateway.services.reliable_media_store import (
    MediaGapMetadata,
    MediaUploadMetadata,
    MediaUploadValidationError,
    SequenceConflictError,
)


router = APIRouter()
logger = logging.getLogger(__name__)
_END_REASONS = {"rotation", "shutdown", "network_reset", "external_power"}
_IMAGE_BATCH_MAGIC = b"BMB1"
_IMAGE_BATCH_MAX_ITEMS = 6
_IMAGE_BATCH_MAX_MANIFEST_BYTES = 64 * 1024
_IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/x-nv12"}


@router.post("/api/v1/media/gap")
async def record_media_gap(
    authorization: str | None = Header(default=None),
    x_device_id: str = Header(),
    x_boot_id: str = Header(),
    x_sequence: int = Header(),
    x_start_monotonic_ms: int = Header(),
    x_end_monotonic_ms: int = Header(),
    x_reason: str = Header(),
) -> JSONResponse:
    if not auth_registry.authorized_device(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        accepted = await asyncio.to_thread(
            app_state.reliable_media.accept_gap,
            MediaGapMetadata(
                device_id=x_device_id,
                boot_id=x_boot_id,
                sequence=x_sequence,
                start_monotonic_ms=x_start_monotonic_ms,
                end_monotonic_ms=x_end_monotonic_ms,
                reason=x_reason,
            ),
            server_received_at_ms=app_state.capture.now_ms(),
        )
    except MediaUploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SequenceConflictError as exc:
        return JSONResponse(
            status_code=409,
            content={"status": "sequence_conflict", "message": str(exc)},
        )
    record = accepted.record
    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if accepted.status == "already_accepted"
            else status.HTTP_201_CREATED
        ),
        content={
            "status": accepted.status,
            "device_id": record["device_id"],
            "boot_id": record["boot_id"],
            "sequence": record["sequence"],
            "start_monotonic_ms": record["start_monotonic_ms"],
            "end_monotonic_ms": record["end_monotonic_ms"],
            "reason": record["reason"],
            "server_received_at_ms": record["server_received_at_ms"],
        },
    )


@router.post("/api/v1/media/upload")
async def upload_media(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    x_device_id: str = Header(),
    x_boot_id: str = Header(),
    x_stream_id: str = Header(),
    x_sequence: int = Header(),
    x_captured_at_ms: int | None = Header(default=None),
    x_monotonic_ms: int = Header(),
    x_clock_synced: bool = Header(),
    x_duration_ms: int = Header(default=0),
    x_filename: str = Header(),
    x_media_type: str = Header(),
    x_content_length: int = Header(),
    x_content_sha256: str = Header(),
    x_width: int | None = Header(default=None),
    x_height: int | None = Header(default=None),
) -> JSONResponse:
    if not auth_registry.authorized_device(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    body = await read_upload_body(
        request,
        timeout_seconds=app_state.settings.device_upload_body_timeout_seconds,
        media_label="media",
    )
    if not body:
        raise HTTPException(status_code=400, detail="empty media body")
    if len(body) > max(
        app_state.settings.audio_upload_max_bytes,
        app_state.settings.object_perception_max_media_bytes,
        app_state.settings.identity_max_media_bytes,
    ):
        raise HTTPException(status_code=413, detail="media body too large")

    pcm: bytes | None = None
    sample_rate = 0
    channels = 0
    decoded_duration_ms = x_duration_ms
    if x_media_type == "audio/wav":
        pcm, sample_rate, channels, decoded_duration_ms = _decode_wav(body)
        if abs(decoded_duration_ms - x_duration_ms) > 2:
            raise HTTPException(
                status_code=400,
                detail=(
                    "x-duration-ms does not match WAV duration: "
                    f"expected {decoded_duration_ms}, got {x_duration_ms}"
                ),
            )
    elif x_media_type == "image/x-nv12":
        if not x_width or not x_height or x_width <= 0 or x_height <= 0:
            raise HTTPException(
                status_code=400,
                detail="x-width and x-height are required for image/x-nv12",
            )
        expected_bytes = x_width * x_height * 3 // 2
        if len(body) != expected_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"invalid NV12 size: expected {expected_bytes}, got {len(body)}",
            )

    received_at_ms = app_state.capture.now_ms()
    metadata = MediaUploadMetadata(
        device_id=x_device_id,
        boot_id=x_boot_id,
        stream_id=x_stream_id,
        sequence=x_sequence,
        captured_at_device_ms=x_captured_at_ms,
        monotonic_ms=x_monotonic_ms,
        clock_synced=x_clock_synced,
        filename=x_filename,
        media_type=x_media_type,
        content_length=x_content_length,
        sha256=x_content_sha256,
        duration_ms=x_duration_ms,
    )
    try:
        accepted = await asyncio.to_thread(
            app_state.reliable_media.accept,
            metadata,
            body,
            server_received_at_ms=received_at_ms,
        )
    except MediaUploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SequenceConflictError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "status": "sequence_conflict",
                "message": str(exc),
            },
        )

    record = accepted.record
    capture_stream_id = f"{x_device_id}-{x_boot_id}"
    events: list[dict] = []
    evidence = None
    try:
        if x_media_type == "audio/wav" and pcm is not None:
            events = await _project_audio_backlog(
                device_id=x_device_id,
                boot_id=x_boot_id,
                media_stream_id=x_stream_id,
                capture_stream_id=capture_stream_id,
                received_at_ms=received_at_ms,
            )
        elif x_media_type in {"image/jpeg", "image/png", "image/x-nv12"}:
            if record.get("projection_status") != "projected":
                suffix = {
                    "image/jpeg": "jpg",
                    "image/png": "png",
                    "image/x-nv12": "nv12",
                }[x_media_type]
                evidence = await app_state.capture.store_image(
                    device_id=x_device_id,
                    stream_id=capture_stream_id,
                    index=x_sequence,
                    device_monotonic_ms=x_monotonic_ms,
                    server_received_at_ms=received_at_ms,
                    captured_at_corrected_ms=record["captured_at_corrected_ms"],
                    captured_at_device_ms=record["captured_at_device_ms"],
                    clock_synced=record["clock_synced"],
                    boot_id=x_boot_id,
                    media_stream_id=x_stream_id,
                    duration_ms=x_duration_ms,
                    clock_anomaly=record["clock_anomaly"],
                    clock_deviation_ms=record["clock_deviation_ms"],
                    suffix=suffix,
                    body=body,
                    width=x_width,
                    height=x_height,
                )
                await asyncio.to_thread(
                    app_state.reliable_media.mark_projected,
                    device_id=x_device_id,
                    boot_id=x_boot_id,
                    stream_id=x_stream_id,
                    sequence=x_sequence,
                    projected_at_ms=received_at_ms,
                )
                background_tasks.add_task(
                    _enrich_image,
                    state=app_state_registry.current(),
                    evidence=evidence,
                    device_id=x_device_id,
                    capture_stream_id=capture_stream_id,
                    media_type=x_media_type,
                    width=x_width,
                    height=x_height,
                )
        else:
            await asyncio.to_thread(
                app_state.reliable_media.mark_projected,
                device_id=x_device_id,
                boot_id=x_boot_id,
                stream_id=x_stream_id,
                sequence=x_sequence,
                projected_at_ms=received_at_ms,
            )
    except ValueError as exc:
        # The authoritative raw upload is already durable. A capture projection
        # conflict is still surfaced so the device stops retrying bad metadata.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    payload = {
        "status": accepted.status,
        "device_id": x_device_id,
        "boot_id": x_boot_id,
        "stream_id": x_stream_id,
        "sequence": x_sequence,
        "sha256": record["sha256"],
        "content_length": record["content_length"],
        "captured_at_device_ms": record["captured_at_device_ms"],
        "captured_at_corrected_ms": record["captured_at_corrected_ms"],
        "server_received_at_ms": record["server_received_at_ms"],
        "clock_anomaly": record["clock_anomaly"],
        "clock_deviation_ms": record["clock_deviation_ms"],
        "storage_path": record["storage_path"],
        "evidence_id": evidence.evidence_id if evidence is not None else None,
        "image_enrichment": "queued" if evidence is not None else None,
        "events": events,
    }
    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if accepted.status == "already_accepted"
            else status.HTTP_201_CREATED
        ),
        content=payload,
    )


def _parse_image_batch(
    body: bytes,
    *,
    expected_count: int,
    max_item_bytes: int,
) -> list[tuple[dict[str, Any], bytes]]:
    if expected_count < 1 or expected_count > _IMAGE_BATCH_MAX_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"x-batch-count must be between 1 and {_IMAGE_BATCH_MAX_ITEMS}",
        )
    if len(body) < 8 or body[:4] != _IMAGE_BATCH_MAGIC:
        raise HTTPException(status_code=400, detail="invalid image batch magic")
    manifest_length = struct.unpack_from("<I", body, 4)[0]
    if manifest_length < 2 or manifest_length > _IMAGE_BATCH_MAX_MANIFEST_BYTES:
        raise HTTPException(status_code=400, detail="invalid image batch manifest length")
    payload_offset = 8 + manifest_length
    if payload_offset > len(body):
        raise HTTPException(status_code=400, detail="truncated image batch manifest")
    try:
        manifest = json.loads(body[8:payload_offset].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid image batch manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise HTTPException(status_code=400, detail="unsupported image batch version")
    items = manifest.get("items")
    if not isinstance(items, list) or len(items) != expected_count:
        raise HTTPException(status_code=400, detail="image batch item count mismatch")

    parsed: list[tuple[dict[str, Any], bytes]] = []
    cursor = payload_offset
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"batch item {index} is not an object")
        content_length = item.get("content_length")
        if (
            not isinstance(content_length, int)
            or isinstance(content_length, bool)
            or content_length <= 0
            or content_length > max_item_bytes
        ):
            raise HTTPException(
                status_code=400,
                detail=f"batch item {index} has invalid content_length",
            )
        end = cursor + content_length
        if end > len(body):
            raise HTTPException(status_code=400, detail=f"batch item {index} is truncated")
        parsed.append((item, body[cursor:end]))
        cursor = end
    if cursor != len(body):
        raise HTTPException(status_code=400, detail="image batch has trailing bytes")
    return parsed


def _required_batch_value(item: dict[str, Any], key: str, expected_type: type) -> Any:
    value = item.get(key)
    if expected_type is int:
        valid = isinstance(value, int) and not isinstance(value, bool)
    else:
        valid = isinstance(value, expected_type)
    if not valid:
        raise MediaUploadValidationError(f"invalid batch field: {key}")
    return value


async def _accept_batched_image(
    *,
    item: dict[str, Any],
    body: bytes,
    background_tasks: BackgroundTasks,
    device_id: str,
    boot_id: str,
    stream_id: str,
) -> dict[str, Any]:
    sequence = _required_batch_value(item, "sequence", int)
    monotonic_ms = _required_batch_value(item, "monotonic_ms", int)
    clock_synced = _required_batch_value(item, "clock_synced", bool)
    filename = _required_batch_value(item, "filename", str)
    media_type = _required_batch_value(item, "media_type", str)
    content_length = _required_batch_value(item, "content_length", int)
    sha256 = _required_batch_value(item, "sha256", str)
    if media_type not in _IMAGE_MEDIA_TYPES:
        raise MediaUploadValidationError("image batch only accepts image media types")

    captured_at_ms = item.get("captured_at_ms")
    if captured_at_ms is not None and (
        not isinstance(captured_at_ms, int) or isinstance(captured_at_ms, bool)
    ):
        raise MediaUploadValidationError("invalid batch field: captured_at_ms")
    duration_ms = item.get("duration_ms", 0)
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool):
        raise MediaUploadValidationError("invalid batch field: duration_ms")
    width = item.get("width")
    height = item.get("height")
    for key, value in (("width", width), ("height", height)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise MediaUploadValidationError(f"invalid batch field: {key}")
    if media_type == "image/x-nv12":
        if not width or not height or width <= 0 or height <= 0:
            raise MediaUploadValidationError(
                "width and height are required for batched image/x-nv12"
            )
        if len(body) != width * height * 3 // 2:
            raise MediaUploadValidationError("invalid batched NV12 size")

    received_at_ms = app_state.capture.now_ms()
    accepted = await asyncio.to_thread(
        app_state.reliable_media.accept,
        MediaUploadMetadata(
            device_id=device_id,
            boot_id=boot_id,
            stream_id=stream_id,
            sequence=sequence,
            captured_at_device_ms=captured_at_ms,
            monotonic_ms=monotonic_ms,
            clock_synced=clock_synced,
            filename=filename,
            media_type=media_type,
            content_length=content_length,
            sha256=sha256,
            duration_ms=duration_ms,
        ),
        body,
        server_received_at_ms=received_at_ms,
    )
    record = accepted.record
    evidence = None
    capture_stream_id = f"{device_id}-{boot_id}"
    if record.get("projection_status") != "projected":
        suffix = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/x-nv12": "nv12",
        }[media_type]
        evidence = await app_state.capture.store_image(
            device_id=device_id,
            stream_id=capture_stream_id,
            index=sequence,
            device_monotonic_ms=monotonic_ms,
            server_received_at_ms=received_at_ms,
            captured_at_corrected_ms=record["captured_at_corrected_ms"],
            captured_at_device_ms=record["captured_at_device_ms"],
            clock_synced=record["clock_synced"],
            boot_id=boot_id,
            media_stream_id=stream_id,
            duration_ms=duration_ms,
            clock_anomaly=record["clock_anomaly"],
            clock_deviation_ms=record["clock_deviation_ms"],
            suffix=suffix,
            body=body,
            width=width,
            height=height,
        )
        await asyncio.to_thread(
            app_state.reliable_media.mark_projected,
            device_id=device_id,
            boot_id=boot_id,
            stream_id=stream_id,
            sequence=sequence,
            projected_at_ms=received_at_ms,
        )
        background_tasks.add_task(
            _enrich_image,
            state=app_state_registry.current(),
            evidence=evidence,
            device_id=device_id,
            capture_stream_id=capture_stream_id,
            media_type=media_type,
            width=width,
            height=height,
        )
    return {
        "status": accepted.status,
        "sequence": sequence,
        "sha256": record["sha256"],
        "content_length": record["content_length"],
        "server_received_at_ms": record["server_received_at_ms"],
        "evidence_id": evidence.evidence_id if evidence is not None else None,
        "retry": False,
    }


@router.post("/api/v1/media/upload-batch")
async def upload_image_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    x_device_id: str = Header(),
    x_boot_id: str = Header(),
    x_stream_id: str = Header(),
    x_batch_count: int = Header(),
    x_batch_content_length: int = Header(),
) -> JSONResponse:
    if not auth_registry.authorized_device(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    body = await read_upload_body(
        request,
        timeout_seconds=app_state.settings.device_upload_body_timeout_seconds,
        media_label="image batch",
    )
    if not body:
        raise HTTPException(status_code=400, detail="empty image batch body")
    if len(body) != x_batch_content_length:
        raise HTTPException(status_code=400, detail="x-batch-content-length mismatch")
    max_item_bytes = max(
        app_state.settings.object_perception_max_media_bytes,
        app_state.settings.identity_max_media_bytes,
    )
    if len(body) > 8 + _IMAGE_BATCH_MAX_MANIFEST_BYTES + (
        _IMAGE_BATCH_MAX_ITEMS * max_item_bytes
    ):
        raise HTTPException(status_code=413, detail="image batch body too large")
    items = _parse_image_batch(
        body,
        expected_count=x_batch_count,
        max_item_bytes=max_item_bytes,
    )

    results: list[dict[str, Any]] = []
    for item, image_body in items:
        sequence = item.get("sequence")
        try:
            results.append(
                await _accept_batched_image(
                    item=item,
                    body=image_body,
                    background_tasks=background_tasks,
                    device_id=x_device_id,
                    boot_id=x_boot_id,
                    stream_id=x_stream_id,
                )
            )
        except SequenceConflictError as exc:
            results.append(
                {
                    "status": "sequence_conflict",
                    "sequence": sequence,
                    "message": str(exc),
                    "retry": False,
                }
            )
        except (MediaUploadValidationError, ValueError) as exc:
            results.append(
                {
                    "status": "invalid",
                    "sequence": sequence,
                    "message": str(exc),
                    "retry": False,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive partial retry path
            logger.exception(
                "batched image ingestion failed device_id=%s sequence=%s",
                x_device_id,
                sequence,
            )
            results.append(
                {
                    "status": "retry",
                    "sequence": sequence,
                    "message": str(exc),
                    "retry": True,
                }
            )

    complete = all(item["status"] in {"accepted", "already_accepted"} for item in results)
    return JSONResponse(
        status_code=status.HTTP_200_OK if complete else status.HTTP_207_MULTI_STATUS,
        content={
            "status": "accepted" if complete else "partial",
            "device_id": x_device_id,
            "boot_id": x_boot_id,
            "stream_id": x_stream_id,
            "batch_count": len(results),
            "items": results,
        },
    )


async def _enrich_image(
    *,
    state: Any,
    evidence: Any,
    device_id: str,
    capture_stream_id: str,
    media_type: str,
    width: int | None,
    height: int | None,
) -> None:
    """Submit optional visual enrichment after the durable media ACK path."""
    if state.object_perception is None and state.identity_perception is None:
        return
    perception_path = str(evidence.path.resolve())
    perception_media_type = media_type
    if media_type == "image/x-nv12":
        try:
            prepared = await asyncio.to_thread(
                state.media_converter.nv12_to_jpeg,
                evidence,
                width=int(width or 0),
                height=int(height or 0),
            )
        except Exception:
            logger.exception("NV12 conversion failed evidence_id=%s", evidence.evidence_id)
            return
        perception_path = str(prepared.path.resolve())
        perception_media_type = prepared.media_type

    context = state.capture.image_job_context(
        device_id=device_id,
        stream_id=capture_stream_id,
    )
    if state.object_perception is not None:
        try:
            await state.object_perception.submit_image(
                evidence_id=evidence.evidence_id,
                image_path=perception_path,
                media_type=perception_media_type,
                captured_at_ms=evidence.captured_at_ms,
                window_id=context["window_id"],
                boot_session_key=context["boot_session_key"],
                width=width,
                height=height,
            )
        except Exception:
            logger.exception(
                "object enrichment failed evidence_id=%s", evidence.evidence_id
            )
    if state.identity_perception is not None:
        try:
            await state.identity_perception.submit_image(
                evidence_id=evidence.evidence_id,
                image_path=perception_path,
                media_type=perception_media_type,
                captured_at_ms=evidence.captured_at_ms,
                boot_session_id=context["boot_session_key"],
                window_id=context["window_id"],
            )
        except Exception:
            logger.exception(
                "identity enrichment failed evidence_id=%s", evidence.evidence_id
            )


def _read_decode_wav(storage_path: str) -> tuple[bytes, int, int, int]:
    """Read a stored WAV from the raw-media store and decode it to PCM.

    Both the file read and the WAV decode are blocking and can hit slow
    storage (e.g. an NTFS-3G mount), so callers run this via
    ``asyncio.to_thread`` instead of holding the event loop.
    """
    return _decode_wav(Path(storage_path).read_bytes())


async def _project_audio_backlog(
    *,
    device_id: str,
    boot_id: str,
    media_stream_id: str,
    capture_stream_id: str,
    received_at_ms: int,
) -> list[dict]:
    pending = await asyncio.to_thread(
        app_state.reliable_media.pending_projection_records,
        device_id=device_id,
        boot_id=boot_id,
        stream_id=media_stream_id,
    )
    if not pending:
        return []
    active = app_state.capture.active_stream_info(device_id=device_id)
    if active is not None and active["stream_id"] != capture_stream_id:
        await app_state.capture.end_stream(
            device_id=device_id,
            stream_id=str(active["stream_id"]),
            ended_at_ms=0,
            server_received_at_ms=received_at_ms,
            reason="rotation",
        )
        active = None
    first_pcm, sample_rate, channels, _ = await asyncio.to_thread(
        _read_decode_wav, pending[0]["storage_path"]
    )
    del first_pcm
    if active is None:
        projected = await asyncio.to_thread(
            app_state.reliable_media.max_projected_sequence,
            device_id=device_id,
            boot_id=boot_id,
            stream_id=media_stream_id,
        )
        app_state.capture.start_stream(
            device_id=device_id,
            stream_id=capture_stream_id,
            device_monotonic_ms=int(pending[0]["monotonic_ms"]),
            server_received_at_ms=received_at_ms,
            boot_session_key=capture_stream_id,
            expected_index=(projected + 1 if projected is not None else 0),
            format=AudioFormat(
                encoding="pcm_s16le",
                sample_rate=sample_rate,
                channels=channels,
            ),
        )
    elif active["sample_rate"] != sample_rate or active["channels"] != channels:
        raise ValueError("audio format changed within one media stream")

    events: list[dict] = []
    for row in pending:
        pcm, row_sample_rate, row_channels, decoded_duration_ms = await asyncio.to_thread(
            _read_decode_wav, row["storage_path"]
        )
        if row_sample_rate != sample_rate or row_channels != channels:
            raise ValueError("audio format changed within one media stream")
        if abs(decoded_duration_ms - int(row["duration_ms"])) > 2:
            raise ValueError("stored WAV duration no longer matches upload metadata")
        events.extend(
            await app_state.capture.add_audio_chunk(
                device_id=device_id,
                stream_id=capture_stream_id,
                index=int(row["sequence"]),
                device_monotonic_ms=int(row["monotonic_ms"]),
                server_received_at_ms=int(row["server_received_at_ms"]),
                captured_at_corrected_ms=int(row["captured_at_corrected_ms"]),
                captured_at_device_ms=row["captured_at_device_ms"],
                clock_synced=bool(row["clock_synced"]),
                boot_id=boot_id,
                media_stream_id=media_stream_id,
                duration_ms=int(row["duration_ms"]),
                clock_anomaly=bool(row["clock_anomaly"]),
                clock_deviation_ms=row["clock_deviation_ms"],
                pcm=pcm,
                defer_window_processing=True,
            )
        )
        current = app_state.capture.active_stream_info(device_id=device_id)
        if current is not None and int(current["expected_index"]) > 0:
            await asyncio.to_thread(
                app_state.reliable_media.mark_projected_through,
                device_id=device_id,
                boot_id=boot_id,
                stream_id=media_stream_id,
                sequence=int(current["expected_index"]) - 1,
                projected_at_ms=received_at_ms,
            )
    return events


@router.get("/api/v1/media/status")
async def media_status(
    authorization: str | None = Header(default=None),
    device_id: str = Query(),
    boot_id: str = Query(),
    stream_id: str = Query(),
) -> dict[str, object]:
    if not auth_registry.authorized_device(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        records = await asyncio.to_thread(
            app_state.reliable_media.records,
            device_id=device_id,
            boot_id=boot_id,
            stream_id=stream_id,
        )
        gaps = await asyncio.to_thread(
            app_state.reliable_media.gaps,
            device_id=device_id,
            boot_id=boot_id,
            stream_id=stream_id,
        )
        declared_gaps = await asyncio.to_thread(
            app_state.reliable_media.declared_gaps,
            device_id=device_id,
            boot_id=boot_id,
        )
    except MediaUploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "device_id": device_id,
        "boot_id": boot_id,
        "stream_id": stream_id,
        "records": records,
        "gaps": gaps,
        "declared_gaps": declared_gaps,
    }


@router.post("/api/v1/media/end")
async def end_media_boot(
    authorization: str | None = Header(default=None),
    x_device_id: str = Header(),
    x_boot_id: str = Header(),
    x_monotonic_ms: int | None = Header(default=None),
    x_reason: str = Header(default="shutdown"),
) -> dict[str, object]:
    if not auth_registry.authorized_device(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    capture_stream_id = f"{x_device_id}-{x_boot_id}"
    active = app_state.capture.active_stream_info(device_id=x_device_id)
    if active is None:
        return {
            "status": "already_ended",
            "device_id": x_device_id,
            "boot_id": x_boot_id,
            "events": [],
        }
    if active["stream_id"] != capture_stream_id:
        raise HTTPException(status_code=409, detail="different device boot is active")
    events = await app_state.capture.end_stream(
        device_id=x_device_id,
        stream_id=capture_stream_id,
        ended_at_ms=0,
        device_monotonic_ms=x_monotonic_ms,
        server_received_at_ms=app_state.capture.now_ms(),
        reason=x_reason if x_reason in _END_REASONS else "shutdown",
    )
    return {
        "status": (
            "awaiting_missing"
            if any(item.get("type") == "capture.stream.awaiting_missing" for item in events)
            else "ended"
        ),
        "device_id": x_device_id,
        "boot_id": x_boot_id,
        "events": events,
    }
