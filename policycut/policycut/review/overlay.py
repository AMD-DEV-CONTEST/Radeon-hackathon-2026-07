"""Review overlay builder: boxes + labels burned into a preview MP4.

No redaction is applied here — the overlay shows what WOULD be redacted so a
human can confirm/ignore events. The original audio track from normalized.mp4
is kept (muxed via a second ffmpeg input). cv2 is imported lazily.
"""
from __future__ import annotations

import collections
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from policycut.media.probe import (
    MediaCancelled,
    MediaError,
    ffmpeg_path,
    fps_of_stream,
    probe_media,
    probe_raw,
)
from policycut.media.render import (
    _finish_encoder,
    _get,
    interpolate_box,
)

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[..., None]]

WATERMARK_TEXT = "PolicyCut REVIEW PREVIEW"

# BGR colors per contract: face red, license_plate orange, id_document purple,
# screen blue; manual/unknown green.
CATEGORY_COLORS: dict[str, tuple[int, int, int]] = {
    "face": (0, 0, 220),
    "license_plate": (0, 140, 255),
    "id_document": (211, 0, 148),
    "screen": (255, 80, 0),
    "manual": (0, 190, 0),
}
_DEFAULT_COLOR = (0, 190, 0)


def _notify(progress_cb: ProgressCallback, stage: str, progress: float, message: str = "") -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(stage, max(0.0, min(1.0, progress)), message)
    except Exception:
        logger.debug("progress callback raised", exc_info=True)


def _active(event: Any, t: float) -> bool:
    return float(_get(event, "start_s", 0.0)) <= t <= float(_get(event, "end_s", 0.0))


def _label_for(event: Any) -> str:
    category = str(_get(event, "category", "") or "manual").upper()
    conf = _get(event, "confidence")
    if _get(event, "source") == "manual":
        return category if category != "MANUAL" else "MANUAL REGION"
    try:
        return f"{category} {float(conf):.2f}" if conf is not None else category
    except (TypeError, ValueError):
        return category


def _draw_visual_event(cv2, frame: np.ndarray, event: Any, t: float) -> None:
    box = interpolate_box(_get(event, "boxes") or [], t)
    if box is None:
        return
    fh, fw = frame.shape[:2]
    x, y, w, h = box
    x0 = max(0, int(round(x * fw)))
    y0 = max(0, int(round(y * fh)))
    x1 = min(fw - 1, int(round((x + w) * fw)))
    y1 = min(fh - 1, int(round((y + h) * fh)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    color = CATEGORY_COLORS.get(str(_get(event, "category", "")).lower(), _DEFAULT_COLOR)
    thickness = 2 if _get(event, "status") != "pending" else 2
    cv2.rectangle(frame, (x0, y0), (x1, y1), color, thickness)

    label = _label_for(event)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thick = 0.5, 1
    (tw, th), baseline = cv2.getTextSize(label, font, scale, thick)
    ly = y0 - 6 if y0 - th - baseline - 6 >= 0 else y1 + th + baseline + 4
    lx = min(x0, max(0, fw - tw - 4))
    cv2.rectangle(frame, (lx, ly - th - baseline), (lx + tw + 4, ly + baseline), color, -1)
    cv2.putText(frame, label, (lx + 2, ly), font, scale, (255, 255, 255), thick, cv2.LINE_AA)


def _draw_audio_banner(cv2, frame: np.ndarray, labels: list[str]) -> None:
    if not labels:
        return
    fh, fw = frame.shape[:2]
    banner_h = 36
    y0 = fh - banner_h
    roi = frame[y0:fh]
    frame[y0:fh] = (roi.astype(np.float32) * 0.30).astype(np.uint8)
    text = "  |  ".join(labels)
    cv2.putText(
        frame, text, (12, fh - 12),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2, cv2.LINE_AA,
    )


def _draw_watermark(cv2, frame: np.ndarray) -> None:
    fh, fw = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thick = 0.45, 1
    (tw, th), _ = cv2.getTextSize(WATERMARK_TEXT, font, scale, thick)
    x, y = max(4, fw - tw - 10), th + 8
    # dark backing box + a single text pass (a shadow pass reads as doubled
    # text at small scales after video compression)
    cv2.rectangle(frame, (x - 5, y - th - 4), (x + tw + 5, y + 5), (20, 20, 20), -1)
    cv2.putText(frame, WATERMARK_TEXT, (x, y), font, scale, (215, 215, 215), thick, cv2.LINE_AA)


def build_overlay(
    normalized_path: str | Path,
    events: list,
    out_path: str | Path,
    settings=None,
    progress_cb: ProgressCallback = None,
    cancel_event=None,
) -> dict:
    """Burn review boxes/labels/banners into out_path (MP4, crf23, faststart).

    Keeps the original audio track from normalized.mp4. Returns a small
    metrics dict {frames, wall_s}.
    """
    stage = "BUILDING_PREVIEW"
    t_start = time.perf_counter()
    normalized_path = Path(normalized_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe_media(normalized_path)
    raw = probe_raw(normalized_path)
    vstream = next(s for s in raw["streams"] if s.get("codec_type") == "video")
    fps, fps_str = fps_of_stream(vstream)

    try:
        import cv2
    except ImportError as exc:
        raise MediaError("OpenCV (cv2) is required to build the review overlay") from exc

    shown = [ev for ev in (events or []) if _get(ev, "status") != "ignored"]
    visual_events = [ev for ev in shown if _get(ev, "kind") == "visual"]
    audio_events = [ev for ev in shown if _get(ev, "kind") == "audio"]

    cap = cv2.VideoCapture(str(normalized_path))
    if not cap.isOpened():
        raise MediaError(f"Could not open {normalized_path.name} for overlay rendering")

    tmp_out = out_path.with_name("." + out_path.name + ".tmp.mp4")
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{info.width}x{info.height}", "-r", fps_str, "-i", "pipe:0",
        "-i", str(normalized_path),
        "-map", "0:v:0", "-map", "1:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-shortest",
        str(tmp_out),
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        cap.release()
        raise MediaError("ffmpeg is not installed or not on PATH (set env FFMPEG to override)") from exc
    stderr_tail: collections.deque[bytes] = collections.deque(maxlen=40)

    def _drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line)

    drain_thread = threading.Thread(target=_drain, daemon=True)
    drain_thread.start()

    total_frames = max(1, int(round(info.duration_s * fps)))
    frames = 0
    try:
        _notify(progress_cb, stage, 0.0, "Building review preview")
        while True:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                raise MediaCancelled("Overlay build cancelled by user")
            ok, frame = cap.read()
            if not ok:
                break
            t = frames / fps
            for ev in visual_events:
                if _active(ev, t):
                    _draw_visual_event(cv2, frame, ev, t)
            banner = [
                f"AUDIO: {str(_get(ev, 'category', 'manual') or 'manual').upper()}"
                for ev in audio_events
                if _active(ev, t)
            ]
            _draw_audio_banner(cv2, frame, banner)
            _draw_watermark(cv2, frame)
            try:
                proc.stdin.write(frame.tobytes())
            except BrokenPipeError as exc:
                detail = b"\n".join(list(stderr_tail)[-5:]).decode("utf-8", "replace")
                raise MediaError(f"overlay encoder terminated early: {detail}") from exc
            frames += 1
            if frames % 20 == 0:
                _notify(
                    progress_cb, stage, min(0.99, frames / total_frames),
                    f"Frame {frames}/{total_frames}",
                )
        _finish_encoder(proc, drain_thread, stderr_tail, "overlay")
    finally:
        cap.release()
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            if proc.poll() != 0:
                tmp_out.unlink(missing_ok=True)
        except OSError:
            pass

    if frames == 0:
        raise MediaError(f"No frames decoded from {normalized_path.name}")
    os.replace(tmp_out, out_path)
    wall = time.perf_counter() - t_start
    _notify(progress_cb, stage, 1.0, "Review preview ready")
    logger.info("overlay %s: %d frames in %.1fs", out_path.name, frames, wall)
    return {"frames": frames, "wall_s": round(wall, 3)}
