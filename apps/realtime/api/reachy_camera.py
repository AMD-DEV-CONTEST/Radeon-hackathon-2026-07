"""M23 — Reachy Mini camera proxy + head tracker.

Allan fork's daemon does NOT expose HTTP camera endpoints (see M21 appendix C),
so the Local Agent opens /dev/video* directly with cv2.VideoCapture and exposes:

  GET /api/reachy/camera/devices
      → list V4L2 devices usable for head tracking / vision.

  GET /api/reachy/camera/snapshot?device=0&w=640&h=480
      → single JPEG image (200) or 503 if device busy.

  WS  /ws/reachy/camera?device=0&fps=15&w=640&h=480
      → binary JPEG frames at the requested fps (for browser <img>-via-WS).

  POST /api/reachy/camera/head-tracker/start?device=0
      → starts a background asyncio task that:
          1. Opens the camera with cv2.VideoCapture.
          2. Runs cv2 Haar cascade face detection at ~8 fps.
          3. Maps the face centroid (cx, cy) in normalized [-1, 1] coords
             to a Reachy head (yaw, pitch) target.
          4. POSTs the target to the daemon `/api/move/set_target` every
             ~150 ms while a face is detected; sends "return to neutral"
             when no face is seen for >1 s.

  POST /api/reachy/camera/head-tracker/stop
      → cancels the head tracker.

  GET /api/reachy/camera/head-tracker/status
      → { running, device, fps, last_face_at, last_target }

Dependencies: only cv2 (already used by camera.py). No mediapipe / no extra
python packages required — Haar cascade is bundled with cv2.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

import cv2
import httpx
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from .camera import _probe_devices as _list_camera_devices
from .reachy_proxy import _daemon_url, _daemon_tcp_open

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reachy/camera", tags=["reachy-camera"])
ws_router = APIRouter(tags=["reachy-camera-ws"])

# ---------------------------------------------------------------------------
# Head tracker singleton (single-process Local Agent)
# ---------------------------------------------------------------------------

# Tunables — exposed via env vars in a future iteration if needed.
_TRACKER_FPS = 8.0
_TRACKER_TARGET_INTERVAL_S = 0.15
_TRACKER_NO_FACE_NEUTRAL_S = 1.0
_TRACKER_MAX_YAW_RAD = 0.7   # ~40°
_TRACKER_MAX_PITCH_RAD = 0.4  # ~23°
_TRACKER_DURATION_S = 0.25
_TRACKER_GAIN = 0.8  # gentle — Reachy should not snap

_tracker_task: asyncio.Task[None] | None = None
_tracker_lock = asyncio.Lock()
_tracker_state: dict[str, Any] = {
    "running": False,
    "device": None,
    "fps": _TRACKER_FPS,
    "last_face_at": 0.0,
    "last_target": None,
    "last_error": None,
}

# cv2 Haar cascade — loaded lazily.
_face_cascade: Optional[cv2.CascadeClassifier] = None


def _get_face_cascade() -> Optional[cv2.CascadeClassifier]:
    global _face_cascade
    if _face_cascade is not None:
        return _face_cascade
    try:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(path)
        if _face_cascade.empty():
            logger.warning("Haar cascade file not found at %s", path)
            _face_cascade = None
    except Exception as exc:
        logger.warning("Failed to load Haar cascade: %s", exc)
        _face_cascade = None
    return _face_cascade


async def _post_set_target(yaw: float, pitch: float) -> None:
    """Send a head target to the Allan daemon (fire-and-forget)."""
    body = {
        "target_head_pose": {
            "x": 0.0, "y": 0.0, "z": 0.0,
            "roll": 0.0, "pitch": float(pitch), "yaw": float(yaw),
        },
        "target_antennas": [0.0, 0.0],
        "target_body_yaw": 0.0,
    }
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            await client.post(_daemon_url("/api/move/set_target"), json=body)
    except Exception as exc:
        logger.debug("set_target POST failed: %s", exc)


async def _head_tracker_loop(device: int) -> None:
    cascade = _get_face_cascade()
    if cascade is None:
        _tracker_state["running"] = False
        _tracker_state["last_error"] = "Haar cascade unavailable"
        return

    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        _tracker_state["running"] = False
        _tracker_state["last_error"] = f"Cannot open /dev/video{device}"
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    cap.set(cv2.CAP_PROP_FPS, _TRACKER_FPS)

    period = 1.0 / _TRACKER_FPS
    last_send = 0.0
    last_face_at = 0.0
    last_target: dict[str, float] | None = None
    try:
        while _tracker_state.get("running"):
            loop_start = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                await asyncio.sleep(period)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
            )
            now = time.monotonic()
            if len(faces) > 0:
                # Pick the largest face.
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                cx = (x + w / 2.0) / float(frame.shape[1])  # 0..1
                cy = (y + h / 2.0) / float(frame.shape[0])  # 0..1
                # Normalize to [-1, 1], invert so head turns toward face.
                yaw = -_TRACKER_GAIN * _TRACKER_MAX_YAW_RAD * (2 * cx - 1)
                pitch = _TRACKER_GAIN * _TRACKER_MAX_PITCH_RAD * (2 * cy - 1)
                last_target = {"yaw": yaw, "pitch": pitch}
                last_face_at = now
                _tracker_state["last_face_at"] = now
                _tracker_state["last_target"] = last_target
            else:
                if now - last_face_at > _TRACKER_NO_FACE_NEUTRAL_S and last_target != {"yaw": 0.0, "pitch": 0.0}:
                    last_target = {"yaw": 0.0, "pitch": 0.0}
                    _tracker_state["last_target"] = last_target

            if last_target is not None and (now - last_send) >= _TRACKER_TARGET_INTERVAL_S:
                await _post_set_target(last_target["yaw"], last_target["pitch"])
                last_send = now

            sleep_s = max(0.01, period - (time.monotonic() - loop_start))
            await asyncio.sleep(sleep_s)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _tracker_state["last_error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("head tracker loop crashed")
    finally:
        try:
            cap.release()
        except Exception:
            pass
        _tracker_state["running"] = False


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


@router.get("/devices")
async def reachy_camera_devices() -> JSONResponse:
    """List V4L2 devices available for Reachy vision / head tracking."""
    try:
        # _probe_devices is a synchronous blocking call; run in thread.
        loop = asyncio.get_event_loop()
        devices = await loop.run_in_executor(None, _list_camera_devices)
        return JSONResponse(content={"ok": True, "devices": devices})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"{type(exc).__name__}: {exc}"},
        )


@router.get("/snapshot")
async def reachy_camera_snapshot(
    device: int = Query(0, ge=0, le=64),
    width: int = Query(640, ge=64, le=1920),
    height: int = Query(480, ge=48, le=1080),
) -> Response:
    """Single JPEG snapshot from a V4L2 device."""
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        return Response(
            status_code=503,
            content=json.dumps({"error": f"Cannot open /dev/video{device}"}),
            media_type="application/json",
        )
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # Warm up
        for _ in range(3):
            cap.read()
        ok, frame = cap.read()
        if not ok:
            return Response(
                status_code=503,
                content=json.dumps({"error": "Frame read failed"}),
                media_type="application/json",
            )
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return Response(
                status_code=500,
                content=json.dumps({"error": "JPEG encode failed"}),
                media_type="application/json",
            )
        return Response(content=buf.tobytes(), media_type="image/jpeg")
    finally:
        cap.release()


@router.post("/head-tracker/start")
async def reachy_head_tracker_start(device: int = Query(0, ge=0, le=64)) -> JSONResponse:
    """Start the background head tracker."""
    global _tracker_task
    async with _tracker_lock:
        if _tracker_state.get("running"):
            return JSONResponse(
                content={"ok": True, "already_running": True, "device": _tracker_state.get("device")}
            )
        # Daemon must be online — the tracker sends set_target to it.
        if not _daemon_tcp_open(timeout_s=0.8):
            return JSONResponse(
                status_code=502,
                content={
                    "ok": False,
                    "error": "reachy_daemon_unreachable",
                    "message": "Start the Reachy Mini daemon before enabling head tracking.",
                },
            )
        _tracker_state.update(
            running=True,
            device=device,
            fps=_TRACKER_FPS,
            last_face_at=0.0,
            last_target=None,
            last_error=None,
        )
        _tracker_task = asyncio.create_task(_head_tracker_loop(device))
        return JSONResponse(content={"ok": True, "device": device, "fps": _TRACKER_FPS})


@router.post("/head-tracker/stop")
async def reachy_head_tracker_stop() -> JSONResponse:
    """Stop the head tracker if running."""
    global _tracker_task
    async with _tracker_lock:
        _tracker_state["running"] = False
        task = _tracker_task
        _tracker_task = None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    return JSONResponse(content={"ok": True, "running": False})


@router.get("/head-tracker/status")
async def reachy_head_tracker_status() -> JSONResponse:
    return JSONResponse(content={"ok": True, **_tracker_state})


# ---------------------------------------------------------------------------
# WebSocket: MJPEG-style binary JPEG frames
# ---------------------------------------------------------------------------


@ws_router.websocket("/ws/reachy/camera")
async def ws_reachy_camera(
    websocket: WebSocket,
    device: int = Query(0, ge=0, le=64),
    fps: int = Query(15, ge=1, le=60),
    width: int = Query(640, ge=64, le=1920),
    height: int = Query(480, ge=48, le=1080),
) -> None:
    """Stream JPEG frames to the browser. Each message is one JPEG blob."""
    await websocket.accept()
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        try:
            await websocket.send_text(json.dumps({
                "type": "reachy_camera_error",
                "error": f"Cannot open /dev/video{device}",
            }))
        except Exception:
            pass
        await websocket.close()
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    period = 1.0 / float(fps)
    try:
        while True:
            loop_start = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                await websocket.send_text(json.dumps({
                    "type": "reachy_camera_error",
                    "error": "frame read failed",
                }))
                await asyncio.sleep(period)
                continue
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                continue
            await websocket.send_bytes(buf.tobytes())
            sleep_s = max(0.005, period - (time.monotonic() - loop_start))
            await asyncio.sleep(sleep_s)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            cap.release()
        except Exception:
            pass
