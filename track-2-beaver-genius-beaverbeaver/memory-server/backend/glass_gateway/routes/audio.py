from __future__ import annotations

from io import BytesIO
import re
import wave

from fastapi import APIRouter, Header, HTTPException, Request, status

from glass_gateway.app_state import app_state
from glass_gateway.auth import auth_registry
from glass_gateway.routes.upload_body import read_upload_body
from glass_gateway.schemas.device_protocol import AudioFormat


router = APIRouter()
_SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]+")
_END_REASONS = {"rotation", "shutdown", "network_reset", "external_power"}


def _authorized(authorization: str | None) -> bool:
    return auth_registry.authorized_device(authorization)


def _safe_part(value: str, default: str) -> str:
    cleaned = _SAFE_PART.sub("_", value).strip("._")
    return cleaned or default


def _decode_wav(body: bytes) -> tuple[bytes, int, int, int]:
    try:
        with wave.open(BytesIO(body), "rb") as source:
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            sample_width = source.getsampwidth()
            compression = source.getcomptype()
            frame_count = source.getnframes()
            pcm = source.readframes(frame_count)
    except (EOFError, wave.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid wav: {exc}",
        ) from exc

    if compression != "NONE":
        raise HTTPException(status_code=400, detail="wav must be uncompressed PCM")
    if channels != 1 or sample_width != 2:
        raise HTTPException(status_code=400, detail="wav must be mono PCM16")
    if sample_rate < 8000 or sample_rate > 48000:
        raise HTTPException(status_code=400, detail="wav sample rate must be 8000-48000 Hz")
    if frame_count <= 0 or not pcm:
        raise HTTPException(status_code=400, detail="wav contains no audio frames")
    duration_ms = frame_count * 1000 // sample_rate
    if duration_ms > 30000:
        raise HTTPException(status_code=400, detail="wav chunk must not exceed 30 seconds")
    return pcm, sample_rate, channels, duration_ms


@router.post("/v1/device/audio", status_code=status.HTTP_202_ACCEPTED)
async def upload_audio(
    request: Request,
    authorization: str | None = Header(default=None),
    x_device_id: str = Header(default="unknown"),
    x_stream_id: str | None = Header(default=None),
    x_sequence: int = Header(default=0),
    x_captured_at_ms: int | None = Header(default=None),
    x_device_monotonic_ms: int | None = Header(default=None),
    x_boot_session_key: str | None = Header(default=None),
) -> dict[str, object]:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    if x_sequence < 0:
        raise HTTPException(status_code=400, detail="x-sequence must be non-negative")

    body = await read_upload_body(
        request,
        timeout_seconds=app_state.settings.device_upload_body_timeout_seconds,
        media_label="audio",
    )
    if not body:
        raise HTTPException(status_code=400, detail="empty audio body")
    if len(body) > app_state.settings.audio_upload_max_bytes:
        raise HTTPException(status_code=413, detail="audio body too large")
    pcm, sample_rate, channels, duration_ms = _decode_wav(body)

    device_id = _safe_part(x_device_id, "unknown")
    stream_id = _safe_part(x_stream_id or device_id, "audio")
    boot_session_key = _safe_part(x_boot_session_key or stream_id, stream_id)
    active = app_state.capture.active_stream_info(device_id=device_id)
    if active is not None and (
        active["stream_id"] != stream_id
        or active["boot_session_key"] != boot_session_key
        or active["sample_rate"] != sample_rate
        or active["channels"] != channels
    ):
        await app_state.capture.end_stream(
            device_id=device_id,
            stream_id=str(active["stream_id"]),
            ended_at_ms=0,
            server_received_at_ms=app_state.capture.now_ms(),
            reason="rotation",
        )
        active = None
    if active is None:
        app_state.capture.start_stream(
            device_id=device_id,
            stream_id=stream_id,
            device_monotonic_ms=x_device_monotonic_ms,
            server_received_at_ms=app_state.capture.now_ms(),
            boot_session_key=boot_session_key,
            format=AudioFormat(
                encoding="pcm_s16le",
                sample_rate=sample_rate,
                channels=channels,
            ),
        )

    try:
        events = await app_state.capture.add_audio_chunk(
            device_id=device_id,
            stream_id=stream_id,
            index=x_sequence,
            captured_at_ms=x_captured_at_ms,
            device_monotonic_ms=x_device_monotonic_ms,
            server_received_at_ms=app_state.capture.now_ms(),
            pcm=pcm,
            defer_window_processing=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    ack = events[0]
    return {
        "status": "accepted",
        "device_id": device_id,
        "stream_id": stream_id,
        "sequence": x_sequence,
        "expected_sequence": ack.get("expected_index"),
        "duplicate": bool(ack.get("duplicate")),
        "wav_bytes": len(body),
        "pcm_bytes": len(pcm),
        "sample_rate": sample_rate,
        "channels": channels,
        "duration_ms": duration_ms,
        "events": events,
    }


@router.post("/v1/device/audio/end")
async def end_audio_stream(
    authorization: str | None = Header(default=None),
    x_device_id: str = Header(default="unknown"),
    x_stream_id: str | None = Header(default=None),
    x_device_monotonic_ms: int | None = Header(default=None),
    x_reason: str = Header(default="shutdown"),
) -> dict[str, object]:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    reason = x_reason if x_reason in _END_REASONS else "shutdown"
    device_id = _safe_part(x_device_id, "unknown")
    stream_id = _safe_part(x_stream_id or device_id, "audio")
    active = app_state.capture.active_stream_info(device_id=device_id)
    if active is None:
        return {"status": "already_ended", "stream_id": stream_id, "events": []}
    if active["stream_id"] != stream_id:
        raise HTTPException(status_code=409, detail="different capture stream is active")
    events = await app_state.capture.end_stream(
        device_id=device_id,
        stream_id=stream_id,
        ended_at_ms=0,
        device_monotonic_ms=x_device_monotonic_ms,
        server_received_at_ms=app_state.capture.now_ms(),
        reason=reason,
    )
    return {"status": "ended", "stream_id": stream_id, "events": events}
