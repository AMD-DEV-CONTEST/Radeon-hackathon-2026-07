"""Camera capture + streaming endpoints (M8.1 + M12 camera hardening).

Provides two streaming modes:
  GET /api/camera/mjpeg?device=0&w=640&h=480&fps=30
      → multipart/x-mixed-replace MJPEG stream (works in <img> tags)

  WS  /ws/camera?device=0&w=640&h=480&fps=30
      → binary WebSocket frames (JPEG bytes per message)

  GET /api/camera/snapshot?device=0
      → single JPEG image

  GET /api/camera/devices
      → list detected V4L2 video devices
         Each entry now includes:
           * ``index`` / ``path`` / ``width`` / ``height`` / ``fps`` / ``backend``
           * ``readable`` – did ``cap.read()`` succeed on the warm-up frame?
           * ``busy`` – True when OpenCV refused to open the device (often
             means another process holds it). Kept distinct from "no video
             device" so the UI can show a targeted message.

  POST /api/camera/stop_streams
      → proactively tear down any MJPEG / WS stream this process is
        currently serving. Used by ``/api/recording/start`` so the
        subsequent ``lerobot-record`` child can open the V4L2 device
        without fighting us (mirrors MakerMods' ``_stop_all_streams``).

The capture loop runs per-connection; no global singleton needed at this stage
since we expect 1–2 concurrent viewers max. Stream cancellation is implemented
via a process-wide registry of ``asyncio.Event`` stop flags so the record
endpoint can signal every open stream to exit before it spawns the CLI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import cv2
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Stream registry — lets ``stop_all_streams()`` preempt any open MJPEG/WS
# generator so its V4L2 handle is released before we launch lerobot-record.
# The registry is module-level (single-process uvicorn is what we ship) and
# guarded by a lock. Streams register on entry and de-register on exit.
# ---------------------------------------------------------------------------


class _StreamHandle:
    """Tracks one open camera stream (MJPEG or WS)."""

    __slots__ = ("id", "kind", "device", "stop_event", "started_at")

    def __init__(self, kind: str, device: str) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind  # "mjpeg" | "ws"
        self.device = device
        # We MUST use threading.Event (not asyncio.Event): MJPEG generators
        # run in the main event loop but camera.py is also called from
        # thread-pool (snapshot) / blocking reads. A threading Event is safe
        # to poll from both. Callers that need to wait can sleep+poll.
        self.stop_event = threading.Event()
        self.started_at = time.monotonic()


_streams: dict[str, _StreamHandle] = {}
_streams_lock = threading.Lock()


def _register_stream(kind: str, device: str) -> _StreamHandle:
    h = _StreamHandle(kind, device)
    with _streams_lock:
        _streams[h.id] = h
    logger.info("camera stream opened: id=%s kind=%s device=%s", h.id, kind, device)
    return h


def _unregister_stream(h: _StreamHandle) -> None:
    with _streams_lock:
        _streams.pop(h.id, None)
    logger.info(
        "camera stream closed: id=%s kind=%s device=%s uptime=%.1fs",
        h.id, h.kind, h.device, time.monotonic() - h.started_at,
    )


def stop_all_streams(wait_s: float = 1.5) -> list[dict[str, Any]]:
    """Signal every open stream to stop and wait for them to drain.

    Returns a list of the streams that were running (for logging). Safe to
    call when no streams are open — just returns ``[]``. This is sync so it
    can be invoked from both async and blocking contexts; inside async you
    should wrap in ``asyncio.to_thread`` to avoid blocking the event loop
    during the small drain sleep.
    """
    with _streams_lock:
        snapshot = list(_streams.values())
        for h in snapshot:
            h.stop_event.set()
    for h in snapshot:
        logger.info("camera stream stop-signal sent: id=%s kind=%s device=%s",
                    h.id, h.kind, h.device)

    # Drain: poll-release until either all streams are gone or wait_s elapses.
    deadline = time.monotonic() + max(0.0, wait_s)
    while time.monotonic() < deadline:
        with _streams_lock:
            if not _streams:
                break
        time.sleep(0.05)

    result = [
        {
            "id": h.id,
            "kind": h.kind,
            "device": h.device,
            "uptime_s": round(time.monotonic() - h.started_at, 2),
        }
        for h in snapshot
    ]
    return result


# ---------------------------------------------------------------------------
# Device probing — distinguishes "no device", "device present but won't open"
# and "opens but can't read a frame" so the UI can show precise messages.
# ---------------------------------------------------------------------------


def _is_capture_node(index: int) -> bool:
    """Skip the metadata-only companion node exposed by many UVC cameras."""
    sysfs_index = Path(f"/sys/class/video4linux/video{index}/index")
    try:
        return sysfs_index.read_text(encoding="utf-8").strip() == "0"
    except OSError:
        return True


def _device_name(index: int) -> str:
    try:
        return Path(
            f"/sys/class/video4linux/video{index}/name"
        ).read_text(encoding="utf-8").strip()
    except OSError:
        return f"Camera {index}"


def _device_holders(index: int) -> list[tuple[str, str]]:
    """Return ``[(pid, cmdline_prefix), ...]`` holding ``/dev/videoN`` (excl. self)."""
    target = f"/dev/video{index}"
    me = str(os.getpid())
    hits: list[tuple[str, str]] = []
    for proc_dir in Path("/proc").glob("[0-9]*"):
        if proc_dir.name == me:
            continue
        fd_dir = proc_dir / "fd"
        try:
            holding = False
            for fd in fd_dir.iterdir():
                try:
                    if os.readlink(fd) == target:
                        holding = True
                        break
                except OSError:
                    continue
            if not holding:
                continue
            try:
                cmd = (proc_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace").strip()
            except OSError:
                cmd = ""
            # Short label for UI
            base = cmd.split()[0] if cmd else "?"
            name = Path(base).name if base else "?"
            hits.append((proc_dir.name, f"{name} ({cmd[:80]})" if cmd else name))
        except (OSError, PermissionError):
            continue
    return hits


def _device_is_held(index: int) -> bool:
    """Return True when another process already has this V4L2 node open."""
    return bool(_device_holders(index))


def _probe_device(index: int, timeout_s: float = 4.0) -> dict[str, Any]:
    """Probe one V4L2 node in a child process so broken drivers cannot hang API."""
    script = r"""
import json, sys
import cv2
i = int(sys.argv[1])
path = f"/dev/video{i}"
# Prefer path over integer index — OpenCV intermittently fails with
# "can't open camera by index" on Linux even when the node is free.
cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
if not cap.isOpened():
    cap.release()
    cap = cv2.VideoCapture(path)
opened = cap.isOpened()
out = {
    "opened": opened, "readable": False, "width": 0, "height": 0,
    "fps": 0.0, "backend": "",
}
if opened:
    out["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    out["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out["fps"] = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    out["backend"] = cap.getBackendName()
    for _ in range(2):
        ok, frame = cap.read()
        if ok and frame is not None:
            out["readable"] = True
            break
cap.release()
print(json.dumps(out))
"""
    empty: dict[str, Any] = {
        "opened": False,
        "readable": False,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "backend": "",
    }
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, str(index)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if result.returncode != 0:
            return {**empty, "error": result.stderr.strip()[-300:]}
        return {**empty, **json.loads(result.stdout)}
    except subprocess.TimeoutExpired:
        return {**empty, "error": f"probe timeout after {timeout_s:.1f}s"}
    except Exception as exc:
        return {**empty, "error": str(exc)}


def _probe_devices(max_index: int = 12) -> list[dict[str, Any]]:
    """Scan /dev/video* for V4L2 devices.

    Every entry that has a matching ``/dev/videoN`` is included. The ``busy``
    flag records whether OpenCV could not open it (typically another process
    is holding it). ``readable`` records whether we got a real frame during
    warm-up — some devices open but never deliver (metadata-only V4L nodes).
    """
    devices: list[dict[str, Any]] = []
    for i in range(max_index):
        dev_path = Path(f"/dev/video{i}")
        if not dev_path.exists() or not _is_capture_node(i):
            continue

        held = _device_is_held(i)
        probe = (
            {
                "opened": False,
                "readable": False,
                "width": 0,
                "height": 0,
                "fps": 0.0,
                "backend": "",
                "error": "device held by another process",
            }
            if held
            else _probe_device(i)
        )
        opened = bool(probe.get("opened"))
        entry: dict[str, Any] = {
            "index": i,
            "path": str(dev_path),
            "name": _device_name(i),
            "width": int(probe.get("width") or 0),
            "height": int(probe.get("height") or 0),
            "fps": float(probe.get("fps") or 0.0),
            "backend": str(probe.get("backend") or ""),
            "busy": not opened,
            "readable": bool(probe.get("readable")),
            "error": probe.get("error"),
        }
        if entry["readable"]:
            devices.append(entry)

    return devices


_probe_status_cache: dict[str, Any] = {}
_probe_status_cache_at: float = 0.0
_PROBE_CACHE_TTL_S = 30.0
_probe_status_lock = threading.Lock()
_probe_async_lock: asyncio.Lock | None = None


def _probe_status_placeholder(max_index: int = 12) -> dict[str, Any]:
    """Cheap fallback when a full V4L2 probe is already running."""
    present = sum(
        1
        for i in range(max_index)
        if Path(f"/dev/video{i}").exists() and _is_capture_node(i)
    )
    return {
        "present_count": present,
        "usable_count": 0,
        "busy_count": 0,
        "nodes": [],
        "probe_pending": True,
    }


def _probe_status(max_index: int = 12) -> dict[str, Any]:
    """Richer probe — returns every /dev/video* node plus why it was rejected.

    The Step 1 UI can use this to explain "busy" vs "not present" separately,
    instead of collapsing both into 'No camera detected'.

    Results are cached for 30s. Concurrent callers share one in-flight probe
    instead of flooding the thread pool (each cv2.VideoCapture open can block
    for ~0.5-1s per device and starve /api/robots).
    """
    global _probe_status_cache, _probe_status_cache_at
    now = time.monotonic()
    if _probe_status_cache and (now - _probe_status_cache_at) < _PROBE_CACHE_TTL_S:
        return dict(_probe_status_cache)

    if not _probe_status_lock.acquire(blocking=False):
        if _probe_status_cache:
            return dict(_probe_status_cache)
        return _probe_status_placeholder(max_index)

    try:
        now = time.monotonic()
        if _probe_status_cache and (now - _probe_status_cache_at) < _PROBE_CACHE_TTL_S:
            return dict(_probe_status_cache)

        nodes: list[dict[str, Any]] = []
        usable = 0
        busy = 0
        present = 0
        for i in range(max_index):
            dev_path = Path(f"/dev/video{i}")
            if not dev_path.exists() or not _is_capture_node(i):
                continue
            present += 1
            held = _device_is_held(i)
            probe = (
                {
                    "opened": False,
                    "readable": False,
                    "width": 0,
                    "height": 0,
                    "fps": 0.0,
                    "backend": "",
                    "error": "device held by another process",
                }
                if held
                else _probe_device(i)
            )
            opened = bool(probe.get("opened"))
            entry: dict[str, Any] = {
                "index": i,
                "path": str(dev_path),
                "name": _device_name(i),
                "opened": opened,
                "readable": bool(probe.get("readable")),
                "width": int(probe.get("width") or 0),
                "height": int(probe.get("height") or 0),
                "fps": float(probe.get("fps") or 0.0),
                "backend": str(probe.get("backend") or ""),
                "error": probe.get("error"),
            }
            if opened:
                if entry["readable"]:
                    usable += 1
            else:
                busy += 1
            nodes.append(entry)

        result = {
            "present_count": present,
            "usable_count": usable,
            "busy_count": busy,
            "nodes": nodes,
        }
        _probe_status_cache.clear()
        _probe_status_cache.update(result)
        _probe_status_cache_at = time.monotonic()
        return dict(result)
    finally:
        _probe_status_lock.release()


async def probe_status_async(max_index: int = 12) -> dict[str, Any]:
    """Serialize camera probes so health checks cannot exhaust the thread pool."""
    global _probe_async_lock
    if _probe_async_lock is None:
        _probe_async_lock = asyncio.Lock()
    async with _probe_async_lock:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _probe_status, max_index)


def _open_capture(
    device: int | str,
    width: int,
    height: int,
    fps: int,
) -> cv2.VideoCapture:
    # Normalize to /dev/videoN — integer index open is flaky on Linux UVC.
    try:
        idx = int(device)
        dev: int | str = f"/dev/video{idx}"
    except (ValueError, TypeError):
        dev = device  # type: ignore[assignment]
        if isinstance(dev, str) and dev.isdigit():
            dev = f"/dev/video{int(dev)}"

    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    if not cap.isOpened():
        try:
            cap.release()
        except Exception:
            pass
        cap = cv2.VideoCapture(dev)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera device {device} ({dev})")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


# ─── REST ────────────────────────────────────────────────────────────────

@router.get("/api/camera/devices")
async def list_camera_devices() -> JSONResponse:
    """Return available V4L2 camera devices (usable ones only)."""
    devices = await asyncio.get_event_loop().run_in_executor(None, _probe_devices)
    return JSONResponse({"devices": devices})


@router.get("/api/camera/status")
async def camera_status() -> JSONResponse:
    """Detailed camera status — lets the UI explain 'busy' vs 'absent'."""
    data = await probe_status_async()
    return JSONResponse(data)


@router.post("/api/camera/stop_streams")
async def stop_streams_endpoint() -> JSONResponse:
    """Force-close every MJPEG / WS stream this process is currently serving.

    Used by ``/api/recording/start`` to release V4L2 handles before spawning
    ``lerobot-record``. Callers can also hit it manually from the UI as an
    "unstick camera" button.
    """
    stopped = await asyncio.get_event_loop().run_in_executor(None, stop_all_streams, 1.5)
    return JSONResponse({"stopped": stopped, "count": len(stopped)})


@router.get("/api/camera/snapshot")
async def camera_snapshot(
    device: str = Query("0"),
    w: int = Query(640),
    h: int = Query(480),
    quality: int = Query(85),
) -> Response:
    """Capture and return a single JPEG frame."""
    def _grab():
        cap = _open_capture(device, w, h, 30)
        try:
            for _ in range(5):
                cap.grab()
            ok, frame = cap.read()
            if not ok or frame is None:
                return None
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return bytes(buf)
        finally:
            cap.release()

    jpeg = await asyncio.get_event_loop().run_in_executor(None, _grab)
    if jpeg is None:
        return Response("Failed to capture frame", status_code=503)
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/api/camera/mjpeg")
async def camera_mjpeg_stream(
    device: str = Query("0"),
    w: int = Query(640),
    h: int = Query(480),
    fps: int = Query(30),
    quality: int = Query(75),
) -> StreamingResponse:
    """MJPEG over HTTP — works with <img src="..."> in any browser.

    Registers in the stream registry so ``stop_all_streams()`` can preempt
    the generator when recording is about to start.
    """
    async def _generate():
        cap: Optional[cv2.VideoCapture] = None
        handle = _register_stream("mjpeg", device)
        try:
            cap = _open_capture(device, w, h, fps)
            period = 1.0 / max(1, fps)
            while not handle.stop_event.is_set():
                t0 = time.monotonic()
                ok, frame = cap.read()
                if not ok or frame is None:
                    await asyncio.sleep(0.1)
                    continue
                _, buf = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
                )
                jpeg = bytes(buf)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
                elapsed = time.monotonic() - t0
                delay = period - elapsed
                if delay > 0:
                    await asyncio.sleep(delay)
        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as exc:
            logger.error("MJPEG stream error: %s", exc)
        finally:
            if cap is not None:
                cap.release()
            _unregister_stream(handle)

    return StreamingResponse(
        _generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ─── WebSocket ───────────────────────────────────────────────────────────

@router.websocket("/ws/camera")
async def camera_ws(
    websocket: WebSocket,
    device: str = Query("0"),
    w: int = Query(640),
    h: int = Query(480),
    fps: int = Query(30),
    quality: int = Query(75),
):
    """Binary WebSocket — each message is a raw JPEG buffer.

    The client can also send JSON commands:
      {"type": "set_quality", "value": 60}
      {"type": "set_fps", "value": 15}
    """
    await websocket.accept()
    cap: Optional[cv2.VideoCapture] = None
    current_quality = quality
    current_fps = fps
    handle = _register_stream("ws", device)

    try:
        cap = _open_capture(device, w, h, fps)
        period = 1.0 / max(1, current_fps)

        while not handle.stop_event.is_set():
            t0 = time.monotonic()

            # Drain any pending client commands (non-blocking)
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.001)
                import json
                cmd = json.loads(msg)
                if cmd.get("type") == "set_quality":
                    current_quality = max(10, min(100, int(cmd["value"])))
                elif cmd.get("type") == "set_fps":
                    current_fps = max(1, min(60, int(cmd["value"])))
                    period = 1.0 / current_fps
            except (asyncio.TimeoutError, Exception):
                pass

            ok, frame = cap.read()
            if not ok or frame is None:
                await asyncio.sleep(0.05)
                continue

            _, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, current_quality]
            )
            await websocket.send_bytes(bytes(buf))

            elapsed = time.monotonic() - t0
            delay = period - elapsed
            if delay > 0:
                await asyncio.sleep(delay)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("Camera WS error: %s", exc)
        try:
            await websocket.close(code=1011, reason=str(exc))
        except Exception:
            pass
    finally:
        if cap is not None:
            cap.release()
        _unregister_stream(handle)
        try:
            await websocket.close()
        except Exception:
            pass
