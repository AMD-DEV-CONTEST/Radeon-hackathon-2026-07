"""Final render: visual redaction effects + audio effects + mux + SRT.

Contract section 7 (render):
  - cv2 frame loop over working/normalized.mp4
  - per frame, apply confirmed visual events active at t:
      alpha from the track's mask npz (resized) when available, else the
      interpolated keyframe box expanded by 8 px and feathered
  - effects: blur / pixelate / solid black; overlap priority applies blur
    first, then pixelate, then solid (so solid > pixelate > blur)
  - frames piped to ffmpeg stdin (libx264 crf18 yuv420p) into a temp file
  - audio: full-rate float32 extraction, audio effects on confirmed audio
    events, mux with -map_metadata -1 +faststart aac 192k
  - ffprobe duration validation (0.1 s) then os.replace into exports/

cv2 and heavy imports are deferred to call time; pure helpers (box
interpolation, effect parameters, SRT writing) work without cv2/ffmpeg.
"""
from __future__ import annotations

import collections
import hashlib
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
    audio_stream_params,
    ffmpeg_path,
    fps_of_stream,
    probe_media,
    probe_raw,
)
from policycut.media.normalize import run_ffmpeg

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[..., None]]

BOX_PAD_PX = 8
FEATHER_PX = 12
MASK_TIME_TOLERANCE_S = 0.75
DURATION_TOLERANCE_S = 0.1
BEEP_FREQ_HZ = 1000.0
BEEP_AMPLITUDE = 10 ** (-12 / 20)  # -12 dBFS
FADE_S = 0.010

_EFFECT_PRIORITY = {"blur": 0, "pixelate": 1, "solid": 2}
_SRT_LABELS = {"phone": "PHONE", "email": "EMAIL", "address": "ADDRESS"}


# --------------------------------------------------------------------------
# generic event field access (works for pydantic models and plain dicts)
# --------------------------------------------------------------------------

def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _action_of(event: Any) -> dict:
    action = _get(event, "action") or {}
    if hasattr(action, "model_dump"):
        action = action.model_dump()
    if not isinstance(action, dict):
        action = {"type": str(action)}
    return action


def _effect_type(event: Any) -> str:
    return str(_action_of(event).get("type") or "pixelate").lower()


def _strength_of(event: Any) -> int:
    try:
        return int(_action_of(event).get("strength") or 65)
    except (TypeError, ValueError):
        return 65


def _is_active(event: Any, t: float) -> bool:
    return float(_get(event, "start_s", 0.0)) <= t <= float(_get(event, "end_s", 0.0))


# --------------------------------------------------------------------------
# pure geometry / parameter helpers (unit-testable without cv2)
# --------------------------------------------------------------------------

def interpolate_box(boxes: list, t: float) -> tuple[float, float, float, float] | None:
    """Linearly interpolate normalized (x, y, w, h) between BoxKeyframes at t.

    Clamps before the first / after the last keyframe. Returns None when the
    event carries no boxes.
    """
    if not boxes:
        return None
    keys = sorted(
        (
            float(_get(b, "t", 0.0)),
            float(_get(b, "x", 0.0)),
            float(_get(b, "y", 0.0)),
            float(_get(b, "w", 0.0)),
            float(_get(b, "h", 0.0)),
        )
        for b in boxes
    )
    if t <= keys[0][0]:
        return keys[0][1:]
    if t >= keys[-1][0]:
        return keys[-1][1:]
    for (t0, *b0), (t1, *b1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            if t1 <= t0:
                return tuple(b1)
            f = (t - t0) / (t1 - t0)
            return tuple(a + (b - a) * f for a, b in zip(b0, b1))
    return keys[-1][1:]


def box_to_pixels(
    box: tuple[float, float, float, float],
    frame_w: int,
    frame_h: int,
    pad_px: int = BOX_PAD_PX,
) -> tuple[int, int, int, int] | None:
    """Normalized (x,y,w,h) -> clipped pixel rect (x0, y0, x1, y1) with padding."""
    x, y, w, h = box
    x0 = int(round(x * frame_w)) - pad_px
    y0 = int(round(y * frame_h)) - pad_px
    x1 = int(round((x + w) * frame_w)) + pad_px
    y1 = int(round((y + h) * frame_h)) + pad_px
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(frame_w, x1), min(frame_h, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1, y1


def blur_kernel_from_strength(strength: int, region_size: int) -> int:
    """Odd Gaussian kernel size scaled by strength (1..100) and region size."""
    strength = max(1, min(100, int(strength)))
    frac = 0.08 + 0.42 * (strength / 100.0)
    k = int(round(max(region_size, 8) * frac))
    k = max(7, min(k, 199))
    return k | 1


def pixelate_block_from_strength(strength: int, region_size: int) -> int:
    """Pixel block size: stronger => fewer, larger blocks across the region."""
    strength = max(1, min(100, int(strength)))
    n_blocks = max(4.0, 26.0 - 22.0 * (strength / 100.0))
    return max(2, int(round(max(region_size, 8) / n_blocks)))


# --------------------------------------------------------------------------
# masks
# --------------------------------------------------------------------------

def _load_masks_fallback(path: Path) -> dict[float, np.ndarray]:
    """Minimal npz reader used when vision.masks is unavailable.

    Understands {str(t): bool 2-D array} and packed 1-D bit arrays with a
    stored 'shape' entry.
    """
    out: dict[float, np.ndarray] = {}
    with np.load(str(path), allow_pickle=False) as data:
        shape = None
        if "shape" in data.files:
            try:
                shape = tuple(int(v) for v in np.asarray(data["shape"]).ravel()[:2])
            except Exception:
                shape = None
        for key in data.files:
            if key in ("shape", "times", "meta"):
                continue
            try:
                t = float(key)
            except ValueError:
                continue
            arr = data[key]
            if arr.ndim == 2:
                out[t] = arr.astype(bool)
            elif arr.ndim == 1 and shape is not None:
                bits = np.unpackbits(arr.astype(np.uint8))[: shape[0] * shape[1]]
                out[t] = bits.reshape(shape).astype(bool)
    return out


def _load_track_masks(masks_dir: Path | None, track_id: str | None) -> tuple[list[float], dict[float, np.ndarray]] | None:
    if not masks_dir or not track_id:
        return None
    path = Path(masks_dir) / f"{track_id}.npz"
    if not path.exists():
        return None
    masks: dict[float, np.ndarray] | None = None
    try:
        from policycut.vision.masks import load_masks_npz  # lazy: other module owns this
        masks = load_masks_npz(path)
    except Exception:
        try:
            masks = _load_masks_fallback(path)
        except Exception as exc:
            logger.warning("could not read masks %s: %s", path.name, exc)
            return None
    if not masks:
        return None
    clean: dict[float, np.ndarray] = {}
    for key, arr in masks.items():
        try:
            t = float(key)
        except (TypeError, ValueError):
            continue
        arr = np.asarray(arr)
        if arr.ndim == 2:
            clean[t] = arr.astype(bool)
    if not clean:
        return None
    return sorted(clean), clean


def _nearest_mask(track_masks, t: float) -> np.ndarray | None:
    times, masks = track_masks
    best = min(times, key=lambda mt: abs(mt - t))
    if abs(best - t) > MASK_TIME_TOLERANCE_S:
        return None
    return masks[best]


# --------------------------------------------------------------------------
# per-frame alpha + effect application (cv2 passed in, imported once)
# --------------------------------------------------------------------------

def _event_alpha(
    cv2,
    event: Any,
    t: float,
    frame_w: int,
    frame_h: int,
    track_masks,
) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
    """Return (alpha ROI float32 0..1, (x0, y0, x1, y1)) for an event at t."""
    if track_masks is not None:
        mask = _nearest_mask(track_masks, t)
        if mask is not None and mask.any():
            m = cv2.resize(
                mask.astype(np.uint8) * 255, (frame_w, frame_h),
                interpolation=cv2.INTER_NEAREST,
            )
            m = cv2.GaussianBlur(m, (9, 9), 0)
            alpha_full = m.astype(np.float32) / 255.0
            ys, xs = np.where(alpha_full > 0.02)
            if ys.size:
                y0, y1 = int(ys.min()), int(ys.max()) + 1
                x0, x1 = int(xs.min()), int(xs.max()) + 1
                if x1 - x0 >= 2 and y1 - y0 >= 2:
                    return alpha_full[y0:y1, x0:x1], (x0, y0, x1, y1)
        # fall through to box fallback

    box = interpolate_box(_get(event, "boxes") or [], t)
    if box is None:
        return None
    rect = box_to_pixels(box, frame_w, frame_h, BOX_PAD_PX)
    if rect is None:
        return None
    bx0, by0, bx1, by1 = rect
    margin = FEATHER_PX * 2
    x0, y0 = max(0, bx0 - margin), max(0, by0 - margin)
    x1, y1 = min(frame_w, bx1 + margin), min(frame_h, by1 + margin)
    alpha = np.zeros((y1 - y0, x1 - x0), dtype=np.float32)
    alpha[by0 - y0 : by1 - y0, bx0 - x0 : bx1 - x0] = 1.0
    k = FEATHER_PX * 2 + 1
    alpha = cv2.GaussianBlur(alpha, (k, k), 0)
    return alpha, (x0, y0, x1, y1)


def _apply_effect_roi(cv2, roi: np.ndarray, effect: str, strength: int) -> np.ndarray:
    rh, rw = roi.shape[:2]
    size = max(rw, rh)
    if effect == "solid":
        return np.zeros_like(roi)
    if effect == "blur":
        k = blur_kernel_from_strength(strength, size)
        return cv2.GaussianBlur(roi, (k, k), 0)
    # default / "pixelate"
    block = pixelate_block_from_strength(strength, size)
    dw, dh = max(1, rw // block), max(1, rh // block)
    down = cv2.resize(roi, (dw, dh), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(down, (rw, rh), interpolation=cv2.INTER_NEAREST)


def redact_frame(
    cv2,
    frame: np.ndarray,
    events: list,
    t: float,
    masks_by_event: dict[int, Any],
) -> np.ndarray:
    """Apply all active confirmed visual events to a BGR frame in place."""
    frame_h, frame_w = frame.shape[:2]
    active = [ev for ev in events if _is_active(ev, t)]
    if not active:
        return frame
    active.sort(key=lambda ev: _EFFECT_PRIORITY.get(_effect_type(ev), 1))
    for ev in active:
        res = _event_alpha(cv2, ev, t, frame_w, frame_h, masks_by_event.get(id(ev)))
        if res is None:
            continue
        alpha, (x0, y0, x1, y1) = res
        roi = frame[y0:y1, x0:x1]
        eff = _apply_effect_roi(cv2, roi, _effect_type(ev), _strength_of(ev))
        a = alpha[..., None]
        blended = roi.astype(np.float32) * (1.0 - a) + eff.astype(np.float32) * a
        frame[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
    return frame


# --------------------------------------------------------------------------
# audio effects (local fallback; policycut.audio.effects preferred)
# --------------------------------------------------------------------------

def apply_audio_effects_local(
    samples: np.ndarray, sample_rate: int, audio_events: list
) -> np.ndarray:
    """Apply mute/beep to float32 samples (n, ch). Mute wins overlaps; 10 ms
    linear fades on both ends of every effect span."""
    out = np.array(samples, dtype=np.float32, copy=True)
    if out.ndim == 1:
        out = out[:, None]
    n = out.shape[0]
    fade = max(1, int(round(FADE_S * sample_rate)))

    def _span(ev) -> tuple[int, int] | None:
        s0 = int(round(float(_get(ev, "start_s", 0.0)) * sample_rate))
        s1 = int(round(float(_get(ev, "end_s", 0.0)) * sample_rate))
        s0, s1 = max(0, s0), min(n, s1)
        return (s0, s1) if s1 - s0 > 1 else None

    def _weight(length: int) -> np.ndarray:
        w = np.ones(length, dtype=np.float32)
        f = min(fade, length // 2)
        if f > 0:
            w[:f] = np.linspace(0.0, 1.0, f, dtype=np.float32)
            w[length - f :] = np.linspace(1.0, 0.0, f, dtype=np.float32)
        return w

    # Beeps first, then mutes, so mute wins overlaps.
    ordered = sorted(
        (ev for ev in audio_events if _effect_type(ev) in ("beep", "mute")),
        key=lambda ev: 0 if _effect_type(ev) == "beep" else 1,
    )
    for ev in ordered:
        span = _span(ev)
        if span is None:
            continue
        s0, s1 = span
        w = _weight(s1 - s0)[:, None]
        if _effect_type(ev) == "beep":
            tt = (np.arange(s0, s1, dtype=np.float64) / sample_rate)
            tone = (BEEP_AMPLITUDE * np.sin(2.0 * np.pi * BEEP_FREQ_HZ * tt)).astype(np.float32)
            out[s0:s1] = out[s0:s1] * (1.0 - w) + tone[:, None] * w
        else:  # mute
            out[s0:s1] *= 1.0 - w
    np.clip(out, -1.0, 1.0, out=out)
    return out


def _apply_audio_effects(samples: np.ndarray, sample_rate: int, audio_events: list, warnings: list[str]) -> np.ndarray:
    """Prefer policycut.audio.effects.apply_audio_effects, fall back locally."""
    try:
        from policycut.audio.effects import apply_audio_effects  # lazy, other module
        processed = apply_audio_effects(samples, sample_rate, audio_events)
        processed = np.asarray(processed, dtype=np.float32)
        if processed.shape == samples.shape and np.isfinite(processed).all():
            return np.clip(processed, -1.0, 1.0)
        raise ValueError("audio.effects returned unexpected shape or non-finite data")
    except Exception as exc:
        logger.warning("audio.effects unavailable (%s); using local implementation", exc)
        warnings.append("audio_effects_local_fallback")
        return apply_audio_effects_local(samples, sample_rate, audio_events)


# --------------------------------------------------------------------------
# hashing / small utils
# --------------------------------------------------------------------------

def sha256_of_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _notify(progress_cb: ProgressCallback, stage: str, progress: float, message: str = "") -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(stage, max(0.0, min(1.0, progress)), message)
    except Exception:
        logger.debug("progress callback raised", exc_info=True)


def _check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise MediaCancelled("Render cancelled by user")


def _resolve_paths(paths: dict) -> tuple[Path, Path, Path | None]:
    normalized = paths.get("normalized") or paths.get("normalized_mp4") or paths.get("input")
    if normalized is None and paths.get("workdir"):
        normalized = Path(paths["workdir"]) / "normalized.mp4"
    exports_dir = paths.get("exports_dir") or paths.get("exports") or paths.get("out_dir")
    if normalized is None or exports_dir is None:
        raise MediaError("render paths must include 'normalized' and 'exports_dir'")
    masks_dir = paths.get("masks_dir") or paths.get("masks")
    return Path(normalized), Path(exports_dir), Path(masks_dir) if masks_dir else None


def _spawn_video_encoder(width: int, height: int, fps_str: str, out_path: Path):
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
        "-r", fps_str, "-i", "pipe:0",
        "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise MediaError("ffmpeg is not installed or not on PATH (set env FFMPEG to override)") from exc
    tail: collections.deque[bytes] = collections.deque(maxlen=40)

    def _drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            tail.append(line)

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    return proc, thread, tail


def _finish_encoder(proc, thread, tail, what: str) -> None:
    if proc.stdin is not None:
        try:
            proc.stdin.close()
        except Exception:
            pass
    rc = proc.wait()
    thread.join(timeout=10)
    if rc != 0:
        detail = b"\n".join(list(tail)[-5:]).decode("utf-8", "replace") or "unknown ffmpeg error"
        raise MediaError(f"{what} encoding failed (exit {rc}): {detail}")


# --------------------------------------------------------------------------
# main entry points
# --------------------------------------------------------------------------

def render_video(
    project,
    events: list,
    paths: dict,
    settings=None,
    progress_cb: ProgressCallback = None,
    cancel_event=None,
) -> dict:
    """Render exports/redacted.mp4 by applying confirmed events.

    ``paths`` keys: normalized (working/normalized.mp4), exports_dir
    (project exports/ dir), masks_dir (analysis/masks, optional).
    Returns metrics including input/output sha256 and timing.
    """
    t_total = time.perf_counter()
    warnings: list[str] = []
    normalized, exports_dir, masks_dir = _resolve_paths(paths)
    exports_dir.mkdir(parents=True, exist_ok=True)

    confirmed = [ev for ev in (events or []) if _get(ev, "status") == "confirmed"]
    visual_events = [ev for ev in confirmed if _get(ev, "kind") == "visual"]
    audio_events = [ev for ev in confirmed if _get(ev, "kind") == "audio"]

    info = probe_media(normalized)
    raw = probe_raw(normalized)
    vstream = next(s for s in raw["streams"] if s.get("codec_type") == "video")
    fps, fps_str = fps_of_stream(vstream)
    width, height = info.width, info.height
    input_sha = sha256_of_file(normalized)

    try:
        import cv2  # heavy-ish dependency, imported lazily
    except ImportError as exc:
        raise MediaError("OpenCV (cv2) is required for rendering but is not installed") from exc

    masks_by_event: dict[int, Any] = {}
    for ev in visual_events:
        track_masks = _load_track_masks(masks_dir, _get(ev, "track_id"))
        if track_masks is not None:
            masks_by_event[id(ev)] = track_masks
        elif _get(ev, "track_id") and not (_get(ev, "boxes") or []):
            warnings.append(f"event_{_get(ev, 'id')}_no_mask_no_boxes")

    cap = cv2.VideoCapture(str(normalized))
    if not cap.isOpened():
        raise MediaError(f"Could not open {normalized.name} for rendering")

    tmp_video = exports_dir / ".render_video.tmp.mp4"
    tmp_out = exports_dir / ".redacted.tmp.mp4"
    tmp_audio_in = exports_dir / ".render_audio_in.f32"
    tmp_audio_out = exports_dir / ".render_audio_out.f32"
    final_path = exports_dir / "redacted.mp4"

    total_frames = max(1, int(round(info.duration_s * fps)))
    frames_written = 0
    t_render = time.perf_counter()
    proc, drain_thread, stderr_tail = _spawn_video_encoder(width, height, fps_str, tmp_video)

    try:
        _notify(progress_cb, "RENDERING", 0.0, "Applying visual redactions")
        while True:
            _check_cancel(cancel_event)
            ok, frame = cap.read()
            if not ok:
                break
            t = frames_written / fps
            frame = redact_frame(cv2, frame, visual_events, t, masks_by_event)
            try:
                proc.stdin.write(frame.tobytes())
            except BrokenPipeError as exc:
                detail = b"\n".join(list(stderr_tail)[-5:]).decode("utf-8", "replace")
                raise MediaError(f"video encoder terminated early: {detail}") from exc
            frames_written += 1
            if frames_written % 15 == 0:
                _notify(
                    progress_cb, "RENDERING",
                    min(0.99, frames_written / total_frames),
                    f"Frame {frames_written}/{total_frames}",
                )
        _finish_encoder(proc, drain_thread, stderr_tail, "render")
    except MediaCancelled:
        try:
            proc.kill()
        except Exception:
            pass
        raise
    finally:
        cap.release()

    if frames_written == 0:
        raise MediaError(f"No frames decoded from {normalized.name}")
    render_wall = time.perf_counter() - t_render

    # ---- audio + mux -----------------------------------------------------
    t_mux = time.perf_counter()
    _notify(progress_cb, "MUXING", 0.0, "Processing audio and muxing")
    try:
        if info.has_audio:
            sr, ch = audio_stream_params(normalized)
            run_ffmpeg(
                [
                    "-i", str(normalized), "-vn",
                    "-f", "f32le", "-acodec", "pcm_f32le",
                    "-ar", str(sr), "-ac", str(ch),
                    str(tmp_audio_in),
                ],
                cancel_event=cancel_event,
            )
            samples = np.fromfile(tmp_audio_in, dtype=np.float32)
            samples = samples.reshape(-1, ch) if ch > 1 else samples[:, None]
            _check_cancel(cancel_event)
            if audio_events:
                samples = _apply_audio_effects(samples, sr, audio_events, warnings)
            samples.astype(np.float32).tofile(tmp_audio_out)
            _notify(progress_cb, "MUXING", 0.4, "Muxing audio and video")
            run_ffmpeg(
                [
                    "-i", str(tmp_video),
                    "-f", "f32le", "-ar", str(sr), "-ac", str(ch), "-i", str(tmp_audio_out),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    "-map_metadata", "-1",
                    "-movflags", "+faststart",
                    "-shortest",
                    str(tmp_out),
                ],
                cancel_event=cancel_event,
            )
        else:
            run_ffmpeg(
                [
                    "-i", str(tmp_video),
                    "-map", "0:v:0", "-c", "copy",
                    "-map_metadata", "-1",
                    "-movflags", "+faststart",
                    str(tmp_out),
                ],
                cancel_event=cancel_event,
            )

        # ---- validate + atomic replace ----------------------------------
        _notify(progress_cb, "MUXING", 0.8, "Validating output")
        out_info = probe_media(tmp_out)
        expected = frames_written / fps
        diff = min(
            abs(out_info.duration_s - expected),
            abs(out_info.duration_s - info.duration_s),
        )
        if diff > DURATION_TOLERANCE_S:
            raise MediaError(
                f"Rendered file duration {out_info.duration_s:.3f}s deviates from "
                f"expected {expected:.3f}s by more than {DURATION_TOLERANCE_S}s"
            )
        os.replace(tmp_out, final_path)
    finally:
        for tmp in (tmp_video, tmp_out, tmp_audio_in, tmp_audio_out):
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    mux_wall = time.perf_counter() - t_mux
    output_sha = sha256_of_file(final_path)
    out_info = probe_media(final_path)
    total_wall = time.perf_counter() - t_total
    _notify(progress_cb, "MUXING", 1.0, "Render complete")
    logger.info(
        "rendered %s: %d frames in %.1fs (%.1f fps), mux %.1fs",
        final_path.name, frames_written, render_wall,
        frames_written / max(render_wall, 1e-6), mux_wall,
    )
    return {
        "input_sha256": input_sha,
        "output_sha256": output_sha,
        "wall_s": round(total_wall, 3),
        "render_wall_s": round(render_wall, 3),
        "mux_wall_s": round(mux_wall, 3),
        "frames": frames_written,
        "effective_fps": round(frames_written / max(render_wall, 1e-6), 2),
        "realtime_factor": round(info.duration_s / max(total_wall, 1e-6), 3),
        "output": {
            "width": out_info.width,
            "height": out_info.height,
            "duration_s": out_info.duration_s,
        },
        "visual_events_applied": len(visual_events),
        "audio_events_applied": len(audio_events),
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# SRT
# --------------------------------------------------------------------------

def _srt_timestamp(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _seg_time(seg: Any, *names: str) -> float | None:
    for name in names:
        value = _get(seg, name)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _redaction_label(category: Any) -> str:
    return _SRT_LABELS.get(str(category or "").lower(), "MANUAL")


def write_srt(transcript_segments: list, confirmed_audio_events: list, out_path: str | Path) -> Path:
    """Write an SRT with words overlapping confirmed audio events replaced by
    [REDACTED: PHONE|EMAIL|ADDRESS|MANUAL]; whole segment when only
    segment-level timestamps exist."""
    intervals: list[tuple[float, float, str]] = []
    for ev in confirmed_audio_events or []:
        kind = _get(ev, "kind", "audio")
        if kind not in (None, "audio"):
            continue
        status = _get(ev, "status")
        if status not in (None, "confirmed"):
            continue
        intervals.append(
            (
                float(_get(ev, "start_s", 0.0)),
                float(_get(ev, "end_s", 0.0)),
                _redaction_label(_get(ev, "category")),
            )
        )
    intervals.sort()

    def _overlap_label(start: float, end: float) -> str | None:
        for i_start, i_end, label in intervals:
            if start < i_end and end > i_start:
                return label
        return None

    entries: list[tuple[float, float, str]] = []
    for seg in transcript_segments or []:
        seg_start = _seg_time(seg, "start", "start_s", "t0") or 0.0
        seg_end = _seg_time(seg, "end", "end_s", "t1")
        if seg_end is None:
            seg_end = seg_start
        text = str(_get(seg, "text", "") or "").strip()
        words = _get(seg, "words") or []
        timed_words = []
        for w in words:
            ws = _seg_time(w, "start", "start_s", "t0")
            we = _seg_time(w, "end", "end_s", "t1")
            token = str(_get(w, "word", None) or _get(w, "text", "") or "").strip()
            if ws is not None and we is not None and token:
                timed_words.append((ws, we, token))
        if timed_words:
            tokens: list[str] = []
            for ws, we, token in timed_words:
                label = _overlap_label(ws, we)
                out_token = f"[REDACTED: {label}]" if label else token
                if label and tokens and tokens[-1] == out_token:
                    continue  # collapse consecutive redacted words
                tokens.append(out_token)
            rendered = " ".join(tokens).strip()
        else:
            label = _overlap_label(seg_start, seg_end)
            rendered = f"[REDACTED: {label}]" if label else text
        if rendered:
            entries.append((seg_start, seg_end, rendered))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for idx, (start, end, text) in enumerate(entries, start=1):
        lines.append(str(idx))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(max(end, start))}")
        lines.append(text)
        lines.append("")
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.replace(tmp, out_path)
    return out_path
