import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.schemas import (
    CalibrationRequest,
    CalibrationSaved,
    ClipStartRequest,
    ErrorCode,
    ErrorEvent,
    utc_now,
)
from command.catalog import PhraseCatalog, catalog_records
from command.inference import save_command_debug
from command.prototype import save_prototype_sample
from session.manager import SessionError, SessionReplacedError
from video.clip import decode_video_clip, save_original_video
from video.mouth_roi import (
    extract_mouth_roi_clip,
    write_aligned_face_video,
    write_mouth_roi_video,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _event(event_type: str, session_id: str, **payload: object) -> dict[str, object]:
    return {
        "type": event_type,
        "sessionId": session_id,
        "timestamp": utc_now().isoformat(),
        **payload,
    }


async def _send_error(
    websocket: WebSocket,
    session_id: str,
    stage: str,
    code: ErrorCode,
    message: str,
    recoverable: bool,
) -> None:
    event = ErrorEvent(
        sessionId=session_id,
        stage=stage,
        code=code,
        message=message,
        recoverable=recoverable,
    )
    await websocket.send_json(event.model_dump(mode="json"))


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        loaded: Any = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _cleanup_temp(session_id: str) -> None:
    temp_dir = Path("/tmp/silent-vision") / session_id
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


def _origin_allowed(origin: str, allowed_origins: set[str]) -> bool:
    return not origin or "*" in allowed_origins or origin in allowed_origins


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    settings = websocket.app.state.settings
    origin = websocket.headers.get("origin", "")
    allowed_origins = settings.allowed_origin_set
    if not _origin_allowed(origin, allowed_origins):
        logger.warning(
            "websocket origin rejected session_id=%s origin=%s allowed_origins=%s",
            session_id,
            origin,
            sorted(allowed_origins),
        )
        await websocket.close(code=1008)
        return

    await websocket.accept()
    logger.info("websocket accepted session_id=%s origin=%s", session_id, origin)
    send_lock = asyncio.Lock()

    async def send_json(payload: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def send_error(
        stage: str, code: ErrorCode, message: str, recoverable: bool
    ) -> None:
        event = ErrorEvent(
            sessionId=session_id,
            stage=stage,
            code=code,
            message=message,
            recoverable=recoverable,
        )
        await send_json(event.model_dump(mode="json"))

    try:
        active = websocket.app.state.session_manager.activate(session_id)
    except SessionError:
        await send_error(
            "session", ErrorCode.INVALID_SESSION, "invalid or expired session", False
        )
        await websocket.close(code=1008)
        return

    async def ensure_current_or_close() -> bool:
        try:
            websocket.app.state.session_manager.ensure_current(active)
        except SessionReplacedError:
            await send_error(
                "session",
                ErrorCode.SESSION_REPLACED,
                "session was replaced by a newer connection",
                False,
            )
            await websocket.close(code=1000)
            return False
        return True

    async def cancel_active_inference(reason: str) -> None:
        task = active.active_inference_task
        if active.inference_cancel_event is not None:
            active.inference_cancel_event.set()
        if task is not None and not task.done():
            logger.info(
                "inference task cancelled session_id=%s reason=%s", session_id, reason
            )
            task.cancel()
            await asyncio.sleep(0)

    async def process_command_clip(
        data: bytes,
        language: str,
        extra_metadata: dict[str, object] | None = None,
    ) -> None:
        started = time.perf_counter()
        debug_dir = (
            settings.debug_window_dir
            or settings.persistence_root / "logs" / "command-runs"
        )
        original_video = None
        aligned_face_video = None
        mouth_roi_video = None
        mouth_roi_npy = None
        if settings.debug_dump_windows:
            original_video = save_original_video(data, debug_dir, session_id)
        await send_json(_event("clip.received", session_id, bytes=len(data)))
        try:
            decoded = await asyncio.to_thread(
                decode_video_clip, data, settings.command_clip_fps
            )
            roi = await asyncio.to_thread(
                extract_mouth_roi_clip,
                frames=decoded.frames,
                face_detector=websocket.app.state.face_detector,
                settings=settings,
            )
            if settings.debug_dump_windows:
                import numpy as np

                mouth_roi_npy = debug_dir / f"{session_id}-mouth_roi.npy"
                np.save(mouth_roi_npy, roi.mouth_frames)
                aligned_face_video = await asyncio.to_thread(
                    write_aligned_face_video,
                    roi.aligned_face_frames,
                    debug_dir / f"{session_id}-aligned_face_video.mp4",
                    settings.command_clip_fps,
                )
                mouth_roi_video = await asyncio.to_thread(
                    write_mouth_roi_video,
                    roi.mouth_frames,
                    debug_dir / f"{session_id}-mouth_roi_video.mp4",
                    settings.command_clip_fps,
                )
            async with websocket.app.state.inference_lock:
                command_decision = await asyncio.to_thread(
                    websocket.app.state.command_classifier.predict,
                    roi.mouth_frames,
                    language,
                    {
                        "frames": len(roi.mouth_frames),
                        "sourceFrames": len(decoded.frames),
                        "fps": decoded.fps,
                        "durationMs": decoded.duration_ms,
                        "detectedFrames": roi.detected_frames,
                        "reusedFrames": roi.reused_frames,
                        "original_video": str(original_video)
                        if original_video
                        else None,
                        "aligned_face_video": str(aligned_face_video)
                        if aligned_face_video
                        else None,
                        "mouth_roi_video": str(mouth_roi_video)
                        if mouth_roi_video
                        else None,
                        "mouth_roi_npy": str(mouth_roi_npy) if mouth_roi_npy else None,
                    }
                    | (extra_metadata or {}),
                )
        except Exception:
            logger.exception(
                "command clip processing failed session_id=%s bytes=%s",
                session_id,
                len(data),
            )
            await send_error(
                "command",
                ErrorCode.INTERNAL_ERROR,
                "command clip processing failed",
                True,
            )
            return

        metadata_path = None
        if settings.debug_dump_windows:
            metadata_path = save_command_debug(settings, session_id, command_decision)
        logger.info(
            "command result session_id=%s intent=%s accepted=%s executable=%s confidence=%.3f margin=%.3f reason=%s latency_ms=%s",
            session_id,
            command_decision.intent,
            command_decision.accepted,
            command_decision.executable,
            command_decision.confidence,
            command_decision.margin,
            command_decision.reason,
            int((time.perf_counter() - started) * 1000),
        )
        await send_json(
            _event(
                "command.result",
                session_id,
                **command_decision.model_dump(),
                debugMetadataPath=str(metadata_path) if metadata_path else None,
            )
        )
        agent = websocket.app.state.agent_policy.decide_command(command_decision)
        await send_json(
            agent.model_dump(mode="json")
            | {"sessionId": session_id, "timestamp": utc_now().isoformat()}
        )

    async def process_calibration_clip(
        data: bytes, calibration: dict[str, Any]
    ) -> None:
        debug_dir = (
            settings.debug_window_dir
            or settings.persistence_root / "logs" / "command-runs"
        )
        profile_id = "global"
        scope = "global"
        target_profile = "global"
        original_video = None
        aligned_face_video = None
        mouth_roi_video = None
        if settings.debug_dump_windows:
            original_video = save_original_video(
                data, debug_dir, session_id, suffix="-calibration.webm"
            )
        await send_json(
            _event("clip.received", session_id, bytes=len(data), calibration=True)
        )
        try:
            decoded = await asyncio.to_thread(
                decode_video_clip, data, settings.command_clip_fps
            )
            roi = await asyncio.to_thread(
                extract_mouth_roi_clip,
                frames=decoded.frames,
                face_detector=websocket.app.state.face_detector,
                settings=settings,
            )
            sample_path = await asyncio.to_thread(
                save_prototype_sample,
                settings.persistence_root,
                target_profile,
                str(calibration["intent"]),
                roi.mouth_frames,
                {
                    "scope": scope,
                    "profileId": profile_id,
                    "language": calibration.get("language", "unknown"),
                    "phraseId": calibration["phraseId"],
                    "phrase": calibration.get("phrase", ""),
                    "sourceFrames": len(decoded.frames),
                    "fps": decoded.fps,
                    "durationMs": decoded.duration_ms,
                    "detectedFrames": roi.detected_frames,
                    "reusedFrames": roi.reused_frames,
                },
            )
            (sample_path / "original.webm").write_bytes(data)
            if settings.debug_dump_windows:
                aligned_face_video = await asyncio.to_thread(
                    write_aligned_face_video,
                    roi.aligned_face_frames,
                    sample_path / "aligned_face_video.mp4",
                    settings.command_clip_fps,
                )
                mouth_roi_video = await asyncio.to_thread(
                    write_mouth_roi_video,
                    roi.mouth_frames,
                    sample_path / "mouth_roi_video.mp4",
                    settings.command_clip_fps,
                )
        except Exception:
            logger.exception(
                "calibration clip processing failed session_id=%s bytes=%s",
                session_id,
                len(data),
            )
            await send_json(
                _event(
                    "calibration.error",
                    session_id,
                    profileId=profile_id,
                    scope=scope,
                    intent=calibration.get("intent"),
                    message="calibration clip processing failed",
                )
            )
            return

        logger.info(
            "calibration sample saved session_id=%s profile_id=%s scope=%s intent=%s sample_path=%s frames=%s detected=%s",
            session_id,
            profile_id,
            scope,
            calibration["intent"],
            sample_path,
            len(roi.mouth_frames),
            roi.detected_frames,
        )
        event = CalibrationSaved(
            sessionId=session_id,
            profileId=profile_id,
            scope=scope,  # type: ignore[arg-type]
            intent=calibration["intent"],
            samplePath=str(sample_path),
            frames=len(roi.mouth_frames),
            detectedFrames=roi.detected_frames,
        ).model_dump(mode="json")
        event["type"] = "calibration.saved"
        event["alignedFaceVideo"] = (
            str(aligned_face_video) if aligned_face_video else None
        )
        event["mouthRoiVideo"] = str(mouth_roi_video) if mouth_roi_video else None
        event["originalVideo"] = (
            str(original_video)
            if original_video
            else str(sample_path / "original.webm")
        )
        await send_json(event)

    await send_json(
        _event(
            "session.ready",
            session_id,
            parameters={
                "captureFps": settings.capture_fps,
                "captureCountdownSeconds": settings.capture_countdown_seconds,
                "mouthSize": settings.mouth_size,
                "recognitionMode": "command",
                "commandClipFps": settings.command_clip_fps,
                "commandClipMinSeconds": settings.command_clip_min_seconds,
                "commandClipMaxSeconds": settings.command_clip_max_seconds,
                "commandConfidenceThreshold": settings.command_confidence_threshold,
                "commandTop1Margin": settings.command_top1_margin,
                "phraseCatalog": catalog_records(websocket.app.state.phrase_catalog),
            },
        )
    )
    logger.info(
        "session ready session_id=%s capture_fps=%s clip_fps=%s clip_seconds=%.1f-%.1f mouth_size=%s",
        session_id,
        settings.capture_fps,
        settings.command_clip_fps,
        settings.command_clip_min_seconds,
        settings.command_clip_max_seconds,
        settings.mouth_size,
    )

    pending_calibration: dict[str, Any] | None = None
    pending_clip_metadata: dict[str, object] = {}
    pending_clip_language: str | None = None

    def clear_pending_request() -> None:
        nonlocal pending_calibration, pending_clip_metadata, pending_clip_language
        pending_calibration = None
        pending_clip_metadata = {}
        pending_clip_language = None

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if not await ensure_current_or_close():
                break
            text = message.get("text")
            if text is not None:
                command_payload = _parse_json_object(text) or {}
                command_type = (
                    command_payload.get("type")
                    if isinstance(command_payload.get("type"), str)
                    else None
                )
                if command_type == "stream.start":
                    await cancel_active_inference("stream restarted")
                    clear_pending_request()
                    active.reset_stream()
                    logger.info("stream started session_id=%s", session_id)
                    await send_json(_event("stream.started", session_id))
                elif command_type == "stream.stop":
                    await cancel_active_inference("stream stopped")
                    clear_pending_request()
                    active.stop_stream()
                    logger.info("stream stopped session_id=%s", session_id)
                    await send_json(_event("stream.stopped", session_id))
                elif command_type == "stream.commit":
                    active.commit_stream()
                    logger.info("stream committed session_id=%s", session_id)
                    await send_json(_event("stream.committed", session_id))
                elif command_type == "ping":
                    await send_json(_event("pong", session_id))
                elif command_type == "clip.start":
                    try:
                        request = ClipStartRequest.model_validate(command_payload)
                    except ValueError as exc:
                        clear_pending_request()
                        active.stop_stream()
                        logger.warning(
                            "clip request rejected session_id=%s reason=%s",
                            session_id,
                            exc,
                        )
                        await send_error(
                            "clip",
                            ErrorCode.INVALID_REQUEST,
                            str(exc),
                            True,
                        )
                        continue
                    await cancel_active_inference("clip started")
                    active.reset_stream()
                    clear_pending_request()
                    pending_clip_metadata = {"profileId": "global"}
                    pending_clip_language = request.language
                    logger.info(
                        "clip started session_id=%s language=%s",
                        session_id,
                        request.language,
                    )
                    await send_json(
                        _event(
                            "clip.started",
                            session_id,
                            language=request.language,
                        )
                    )
                elif command_type == "clip.cancel":
                    await cancel_active_inference("clip cancelled")
                    active.stop_stream()
                    clear_pending_request()
                    logger.info("clip cancelled session_id=%s", session_id)
                    await send_json(_event("stream.stopped", session_id))
                elif command_type == "calibration.start":
                    try:
                        request = CalibrationRequest.model_validate(command_payload)
                        if not settings.allow_global_profile_write:
                            raise ValueError("global profile writes are disabled")
                        calibration = _resolve_calibration(
                            request, websocket.app.state.phrase_catalog
                        ) | {"profileId": "global", "scope": "global"}
                        await cancel_active_inference("calibration started")
                        active.reset_stream()
                        clear_pending_request()
                        pending_calibration = calibration
                        logger.info(
                            "calibration started session_id=%s profile_id=%s scope=%s phrase_id=%s intent=%s",
                            session_id,
                            request.profileId,
                            request.scope,
                            pending_calibration["phraseId"],
                            pending_calibration["intent"],
                        )
                        await send_json(
                            _event(
                                "calibration.started",
                                session_id,
                                profileId=request.profileId,
                                scope=request.scope,
                                phraseId=pending_calibration["phraseId"],
                                intent=pending_calibration["intent"],
                                language=pending_calibration["language"],
                            )
                        )
                    except ValueError as exc:
                        clear_pending_request()
                        active.stop_stream()
                        logger.warning(
                            "calibration request rejected session_id=%s reason=%s",
                            session_id,
                            exc,
                        )
                        await send_error(
                            "calibration",
                            ErrorCode.INVALID_REQUEST,
                            str(exc),
                            True,
                        )
                continue

            data = message.get("bytes")
            if data is None or not active.accepting_frames:
                continue

            if pending_calibration is not None:
                calibration = pending_calibration
                pending_calibration = None
                active.commit_stream()
                await process_calibration_clip(data, calibration)
                continue

            active.commit_stream()
            language = pending_clip_language
            pending_clip_language = None
            if language is None:
                continue
            data_metadata = pending_clip_metadata.copy()
            pending_clip_metadata = {}
            await process_command_clip(data, language, data_metadata)
    except WebSocketDisconnect:
        logger.info("websocket disconnected session_id=%s", session_id)
        websocket.app.state.session_manager.disconnect(session_id)
    finally:
        logger.info(
            "websocket cleanup session_id=%s active_inference_task=%s",
            session_id,
            active.active_inference_task is not None,
        )
        await cancel_active_inference("websocket cleanup")
        clear_pending_request()
        active.stop_stream()
        websocket.app.state.session_manager.disconnect(session_id)
        _cleanup_temp(session_id)


def _resolve_calibration(
    request: CalibrationRequest, catalog: PhraseCatalog
) -> dict[str, str]:
    if request.phraseId == "UNKNOWN":
        phrase = request.phrase.strip()
        if not phrase:
            raise ValueError("UNKNOWN calibration requires a non-empty phrase")
        return {
            "phraseId": "UNKNOWN",
            "phrase": phrase,
            "language": request.language,
            "intent": "UNKNOWN",
        }

    entry = catalog.by_id(request.phraseId)
    if entry.language != request.language:
        raise ValueError("phraseId does not belong to the selected language")
    return {
        "phraseId": entry.phrase_id,
        "phrase": entry.text,
        "language": entry.language,
        "intent": entry.intent.value,
    }
