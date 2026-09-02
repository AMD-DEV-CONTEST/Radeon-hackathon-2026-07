"""ffprobe subprocess wrapper producing MediaInfo.

Pure stdlib at import time. ffprobe/ffmpeg binaries are resolved lazily and can
be overridden with the ``FFPROBE`` / ``FFMPEG`` environment variables.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_S = 60


class MediaError(Exception):
    """Raised for corrupt/unsupported media or failed ffmpeg/ffprobe calls.

    The message is always a human-readable reason suitable for the UI.
    """


class MediaCancelled(MediaError):
    """Raised when a media operation is cancelled via cancel_event."""


def ffprobe_path() -> str:
    """Path to the ffprobe binary; env var FFPROBE overrides."""
    return os.environ.get("FFPROBE") or "ffprobe"


def ffmpeg_path() -> str:
    """Path to the ffmpeg binary; env var FFMPEG overrides."""
    return os.environ.get("FFMPEG") or "ffmpeg"


def have_ffmpeg() -> bool:
    """True when both ffmpeg and ffprobe are resolvable."""
    return (
        shutil.which(ffprobe_path()) is not None
        and shutil.which(ffmpeg_path()) is not None
    )


def probe_raw(path: str | Path) -> dict:
    """Run ffprobe and return the parsed JSON document (format + streams).

    Raises MediaError with a readable reason on any failure.
    """
    p = Path(path)
    if not p.exists():
        raise MediaError(f"File not found: {p.name}")
    if p.stat().st_size == 0:
        raise MediaError(f"File is empty: {p.name}")
    cmd = [
        ffprobe_path(),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(p),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S
        )
    except FileNotFoundError as exc:
        raise MediaError(
            "ffprobe is not installed or not on PATH (set env FFPROBE to override)"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffprobe timed out while reading {p.name}") from exc
    if proc.returncode != 0:
        reason = (proc.stderr or "").strip().splitlines()
        detail = reason[-1] if reason else "unknown ffprobe error"
        raise MediaError(f"Unreadable or unsupported media file {p.name}: {detail}")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError(f"ffprobe returned invalid JSON for {p.name}") from exc
    if not isinstance(data, dict) or not data.get("streams"):
        raise MediaError(f"No decodable streams found in {p.name}")
    return data


def _parse_rate(rate: Any) -> float:
    """Parse an ffprobe rate string like '30000/1001' into a float fps."""
    try:
        text = str(rate or "")
        if "/" in text:
            num_s, den_s = text.split("/", 1)
            num, den = float(num_s), float(den_s)
            if den == 0:
                return 0.0
            return num / den
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def fps_of_stream(stream: dict) -> tuple[float, str]:
    """Return (fps_float, fps_rate_string) for a video stream.

    Prefers r_frame_rate, falls back to avg_frame_rate; the string form is the
    exact rational and can be passed straight to ffmpeg's -r option.
    """
    for key in ("r_frame_rate", "avg_frame_rate"):
        raw = stream.get(key)
        fps = _parse_rate(raw)
        if 0.0 < fps <= 480.0:
            return fps, str(raw)
    return 30.0, "30"


def rotation_of_stream(stream: dict) -> int:
    """Extract rotation (degrees, one of 0/90/180/270) from stream side data
    or the legacy 'rotate' tag."""
    rot = 0.0
    for side in stream.get("side_data_list") or []:
        if isinstance(side, dict) and "rotation" in side:
            try:
                rot = float(side["rotation"])
                break
            except (TypeError, ValueError):
                continue
    if rot == 0.0:
        tag = (stream.get("tags") or {}).get("rotate")
        try:
            rot = float(tag) if tag is not None else 0.0
        except (TypeError, ValueError):
            rot = 0.0
    normalized = int(round(rot)) % 360
    if normalized < 0:
        normalized += 360
    # Snap to the nearest quarter turn.
    return min((0, 90, 180, 270), key=lambda q: min(abs(normalized - q), 360 - abs(normalized - q)))


def _duration_of(data: dict, vstream: dict, fps: float) -> float:
    fmt = data.get("format") or {}
    for source in (fmt.get("duration"), vstream.get("duration")):
        try:
            dur = float(source)
            if dur > 0:
                return dur
        except (TypeError, ValueError):
            continue
    try:
        nb = float(vstream.get("nb_frames"))
        if nb > 0 and fps > 0:
            return nb / fps
    except (TypeError, ValueError):
        pass
    return 0.0


def probe_media(path: str | Path):
    """Probe a media file and return a MediaInfo (policycut.core.models).

    Raises MediaError with a readable reason for corrupt/unsupported input.
    """
    p = Path(path)
    data = probe_raw(p)
    streams = data.get("streams") or []
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if vstream is None:
        raise MediaError(f"No video stream found in {p.name} (audio-only or unsupported file)")
    astream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(vstream.get("width") or 0)
    height = int(vstream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise MediaError(f"Video stream in {p.name} has invalid dimensions")

    fps, _ = fps_of_stream(vstream)
    duration = _duration_of(data, vstream, fps)
    if duration <= 0:
        raise MediaError(f"Could not determine duration of {p.name} (still image or corrupt file?)")

    fmt = data.get("format") or {}
    try:
        size_bytes = int(fmt.get("size"))
    except (TypeError, ValueError):
        size_bytes = p.stat().st_size

    fields = dict(
        filename=p.name,
        duration_s=round(duration, 3),
        width=width,
        height=height,
        fps=round(fps, 3),
        codec=str(vstream.get("codec_name") or "unknown"),
        has_audio=astream is not None,
        audio_codec=str(astream.get("codec_name")) if astream is not None else None,
        size_bytes=size_bytes,
        rotation=rotation_of_stream(vstream),
    )
    try:
        from policycut.core.models import MediaInfo  # local import: keeps probe importable standalone
        return MediaInfo(**fields)
    except ImportError:  # pragma: no cover - only during partial checkouts
        logger.warning("policycut.core.models unavailable; returning plain namespace MediaInfo")
        from types import SimpleNamespace
        return SimpleNamespace(**fields)


def audio_stream_params(path: str | Path) -> tuple[int, int]:
    """Return (sample_rate, channels) of the first audio stream, with sane
    defaults (48000, 2) when the fields are missing."""
    data = probe_raw(path)
    astream = next(
        (s for s in (data.get("streams") or []) if s.get("codec_type") == "audio"), None
    )
    if astream is None:
        raise MediaError(f"No audio stream found in {Path(path).name}")
    try:
        sr = int(astream.get("sample_rate") or 48000)
    except (TypeError, ValueError):
        sr = 48000
    try:
        ch = int(astream.get("channels") or 2)
    except (TypeError, ValueError):
        ch = 2
    return max(8000, sr), max(1, min(ch, 8))
