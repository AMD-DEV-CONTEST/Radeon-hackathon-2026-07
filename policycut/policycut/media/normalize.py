"""Video normalization (contract section 7, analysis step 1).

Produces inside ``workdir`` (the project's ``working/`` directory):
  - normalized.mp4  : CFR, <=1080p, yuv420p, libx264 crf20, +faststart, aac audio
  - proxy.mp4       : long edge <= settings.proxy_long_edge, no audio
  - thumbnail.jpg   : frame at 25% of duration
  - asr.wav         : 16 kHz mono s16le (only when the source has audio)
  - normalize_info.json

Only stdlib is required at import time; all work is done through ffmpeg
subprocesses (env vars FFMPEG / FFPROBE override binary paths).
"""
from __future__ import annotations

import collections
import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from policycut.media.probe import (
    MediaCancelled,
    MediaError,
    ffmpeg_path,
    fps_of_stream,
    probe_media,
    probe_raw,
)

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[..., None]]

SCENE_THRESHOLD = 0.4
_STDERR_TAIL = 40  # lines kept for error reporting


def _notify(progress_cb: ProgressCallback, stage: str, progress: float, message: str = "") -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(stage, max(0.0, min(1.0, progress)), message)
    except Exception:  # never let UI plumbing break the pipeline
        logger.debug("progress callback raised", exc_info=True)


def _check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise MediaCancelled("Operation cancelled by user")


def run_ffmpeg(
    args: list[str],
    *,
    duration_s: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancel_event=None,
    keep_stderr: bool = False,
) -> str:
    """Run an ffmpeg command (args exclude the binary name and -y).

    Progress is parsed from ``-progress pipe:1`` output; cancellation kills the
    process and raises MediaCancelled. Returns captured stderr text (full text
    when keep_stderr, else the tail) and raises MediaError on non-zero exit.
    """
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise MediaError(
            "ffmpeg is not installed or not on PATH (set env FFMPEG to override)"
        ) from exc

    stderr_lines: collections.deque[str] | list[str]
    stderr_lines = [] if keep_stderr else collections.deque(maxlen=_STDERR_TAIL)

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line.rstrip("\n"))

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.wait()
                raise MediaCancelled("Operation cancelled by user")
            if on_progress is not None and duration_s and duration_s > 0:
                m = re.match(r"out_time_ms=(\d+)", line)
                if m:
                    done_s = int(m.group(1)) / 1_000_000.0
                    try:
                        on_progress(min(1.0, done_s / duration_s))
                    except Exception:
                        logger.debug("ffmpeg progress hook raised", exc_info=True)
        rc = proc.wait()
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        t.join(timeout=5)

    stderr_text = "\n".join(stderr_lines)
    if rc != 0:
        tail = "\n".join(list(stderr_lines)[-6:]) or "unknown ffmpeg error"
        raise MediaError(f"ffmpeg failed (exit {rc}): {tail}")
    return stderr_text


def _even(value: float) -> int:
    return max(2, int(round(value)) // 2 * 2)


def _fit_dims(width: int, height: int, rotation: int, max_height: int) -> tuple[int, int]:
    """Display dimensions after autorotation, downscaled to fit <=1080p-class
    bounds: short edge <= max_height, long edge <= max_height*16/9.

    A landscape 3840x2160 becomes 1920x1080; a portrait 1080x1920 phone clip
    is kept as-is instead of being crushed to 608x1080.
    """
    if rotation in (90, 270):
        width, height = height, width
    long_edge_cap = max_height * 16.0 / 9.0
    scale = min(
        1.0,
        max_height / float(min(width, height)),
        long_edge_cap / float(max(width, height)),
    )
    return _even(width * scale), _even(height * scale)


def _fit_long_edge(width: int, height: int, long_edge: int) -> tuple[int, int]:
    scale = min(1.0, long_edge / float(max(width, height)))
    return _even(width * scale), _even(height * scale)


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _dump_media_info(info: Any) -> dict:
    if hasattr(info, "model_dump"):
        return info.model_dump()
    if isinstance(info, dict):
        return dict(info)
    return {k: v for k, v in vars(info).items() if not k.startswith("_")}


def parse_scene_cuts(showinfo_stderr: str) -> list[float]:
    """Parse pts_time values out of ffmpeg showinfo stderr output."""
    cuts = {round(float(m), 3) for m in re.findall(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)", showinfo_stderr)}
    return sorted(cuts)


def normalize_video(
    src: str | Path,
    workdir: str | Path,
    settings=None,
    progress_cb: ProgressCallback = None,
    cancel_event=None,
) -> dict:
    """Normalize the uploaded source video. Returns the info dict that is also
    written to ``workdir/normalize_info.json`` (relative file names only)."""
    stage = "NORMALIZING"
    src = Path(src)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    max_height = int(getattr(settings, "max_height", 1080) or 1080)
    proxy_long_edge = int(getattr(settings, "proxy_long_edge", 1280) or 1280)

    warnings: list[str] = []
    _notify(progress_cb, stage, 0.0, "Probing source video")
    source_info = probe_media(src)
    raw = probe_raw(src)
    vstream = next(s for s in raw["streams"] if s.get("codec_type") == "video")
    fps, fps_str = fps_of_stream(vstream)
    duration = float(source_info.duration_s)
    has_audio = bool(source_info.has_audio)

    out_w, out_h = _fit_dims(source_info.width, source_info.height, source_info.rotation, max_height)

    normalized_path = workdir / "normalized.mp4"
    proxy_path = workdir / "proxy.mp4"
    thumb_path = workdir / "thumbnail.jpg"
    asr_path = workdir / "asr.wav"

    # ---- 1. normalized.mp4 (CFR, <=1080p, yuv420p, libx264 crf20, faststart, aac)
    _check_cancel(cancel_event)
    _notify(progress_cb, stage, 0.02, "Encoding normalized video")
    tmp = workdir / "normalized.tmp.mp4"
    args = ["-i", str(src), "-map", "0:v:0"]
    if has_audio:
        args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    args += [
        "-vf", f"scale={out_w}:{out_h}",
        "-r", fps_str,
        "-vsync", "cfr",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-sn", "-dn",
        str(tmp),
    ]
    run_ffmpeg(
        args,
        duration_s=duration,
        on_progress=lambda f: _notify(progress_cb, stage, 0.02 + 0.53 * f, "Encoding normalized video"),
        cancel_event=cancel_event,
    )
    os.replace(tmp, normalized_path)
    norm_info = probe_media(normalized_path)

    # ---- 2. proxy.mp4 (long edge <= proxy_long_edge, no audio)
    _check_cancel(cancel_event)
    _notify(progress_cb, stage, 0.55, "Encoding analysis proxy")
    pw, ph = _fit_long_edge(norm_info.width, norm_info.height, proxy_long_edge)
    tmp = workdir / "proxy.tmp.mp4"
    run_ffmpeg(
        [
            "-i", str(normalized_path), "-an",
            "-vf", f"scale={pw}:{ph}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(tmp),
        ],
        duration_s=norm_info.duration_s,
        on_progress=lambda f: _notify(progress_cb, stage, 0.55 + 0.20 * f, "Encoding analysis proxy"),
        cancel_event=cancel_event,
    )
    os.replace(tmp, proxy_path)
    proxy_info = probe_media(proxy_path)

    # ---- 3. thumbnail.jpg at 25% duration (non-fatal on failure)
    _check_cancel(cancel_event)
    _notify(progress_cb, stage, 0.76, "Extracting thumbnail")
    thumbnail_name: str | None = "thumbnail.jpg"
    try:
        thumb_t = max(0.0, norm_info.duration_s * 0.25)
        tw = _even(min(640, norm_info.width))
        tmp = workdir / "thumbnail.tmp.jpg"
        run_ffmpeg(
            [
                "-ss", f"{thumb_t:.3f}", "-i", str(normalized_path),
                "-frames:v", "1", "-vf", f"scale={tw}:-2", "-q:v", "3",
                str(tmp),
            ],
            cancel_event=cancel_event,
        )
        os.replace(tmp, thumb_path)
    except MediaCancelled:
        raise
    except MediaError as exc:
        logger.warning("thumbnail extraction failed: %s", exc)
        warnings.append(f"thumbnail_failed: {exc}")
        thumbnail_name = None

    # ---- 4. asr.wav 16k mono s16le (only when source has audio; non-fatal)
    _check_cancel(cancel_event)
    asr_name: str | None = None
    if has_audio:
        _notify(progress_cb, stage, 0.80, "Extracting ASR audio")
        try:
            tmp = workdir / "asr.tmp.wav"
            run_ffmpeg(
                [
                    "-i", str(src), "-vn",
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                    "-f", "wav", str(tmp),
                ],
                duration_s=duration,
                cancel_event=cancel_event,
            )
            os.replace(tmp, asr_path)
            asr_name = "asr.wav"
        except MediaCancelled:
            raise
        except MediaError as exc:
            logger.warning("asr wav extraction failed: %s", exc)
            warnings.append(f"asr_extract_failed: {exc}")

    # ---- 5. scene cut detection on the proxy (non-fatal)
    _check_cancel(cancel_event)
    _notify(progress_cb, stage, 0.86, "Detecting scene cuts")
    scene_cuts: list[float] = []
    try:
        stderr = run_ffmpeg(
            [
                "-i", str(proxy_path),
                "-vf", f"select=gt(scene\\,{SCENE_THRESHOLD}),showinfo",
                "-an", "-f", "null", "-",
            ],
            cancel_event=cancel_event,
            keep_stderr=True,
        )
        scene_cuts = parse_scene_cuts(stderr)
    except MediaCancelled:
        raise
    except MediaError as exc:
        logger.warning("scene detection failed: %s", exc)
        warnings.append(f"scene_detect_failed: {exc}")

    info = {
        "schema_version": "1.0",
        "source": _dump_media_info(source_info),
        "normalized": {
            "file": "normalized.mp4",
            "width": norm_info.width,
            "height": norm_info.height,
            "fps": norm_info.fps,
            "fps_str": fps_str,
            "duration_s": norm_info.duration_s,
            "has_audio": norm_info.has_audio,
        },
        "proxy": {
            "file": "proxy.mp4",
            "width": proxy_info.width,
            "height": proxy_info.height,
            "fps": proxy_info.fps,
            "duration_s": proxy_info.duration_s,
        },
        "thumbnail": thumbnail_name,
        "asr_wav": asr_name,
        "scene_cuts": scene_cuts,
        "warnings": warnings,
    }
    _write_json_atomic(workdir / "normalize_info.json", info)
    _notify(progress_cb, stage, 1.0, "Normalization complete")
    logger.info(
        "normalized %s -> %dx%d @ %s fps, proxy %dx%d, %d scene cuts",
        src.name, norm_info.width, norm_info.height, fps_str, proxy_info.width, proxy_info.height,
        len(scene_cuts),
    )
    return info
