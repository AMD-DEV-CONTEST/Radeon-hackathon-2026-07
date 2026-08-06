from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from colorgraph.config import settings
from colorgraph.domain.grade_graph import MediaInfo
from colorgraph.media.metadata import probe_color_metadata


class MediaProbeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VideoFrameTiming:
    pts_seconds: float
    duration_seconds: float | None


def _parse_frame_rate(value: str | None) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise MediaProbeError(f"invalid frame rate reported by ffprobe: {value}") from exc


def _run_ffprobe(path: Path) -> dict[str, Any]:
    command = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-read_intervals",
        "%+#8",
        "-show_streams",
        "-show_format",
        "-show_frames",
        "-show_entries",
        "stream:format:frame=side_data_list",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise MediaProbeError(f"ffprobe failed for {path}: {stderr.strip()}") from exc
    return json.loads(result.stdout)


def _run_frame_timing_probe(path: Path) -> dict[str, Any]:
    command = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        "frame=best_effort_timestamp_time,pts_time,pkt_duration_time,duration_time",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise MediaProbeError(
            f"ffprobe frame timing scan failed for {path}: {stderr.strip()}"
        ) from exc
    return json.loads(result.stdout)


def _parse_timestamp(value: object) -> float | None:
    if value in {None, "N/A"}:
        return None
    try:
        parsed = float(str(value))
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def probe_frame_timings(path: str | Path) -> list[VideoFrameTiming]:
    media_path = Path(path).resolve()
    if not media_path.is_file():
        raise MediaProbeError(f"media file does not exist: {media_path}")
    payload = _run_frame_timing_probe(media_path)
    timings: list[VideoFrameTiming] = []
    for frame in payload.get("frames", []):
        if not isinstance(frame, dict):
            continue
        pts = _parse_timestamp(frame.get("best_effort_timestamp_time"))
        if pts is None:
            pts = _parse_timestamp(frame.get("pts_time"))
        if pts is None:
            continue
        duration = _parse_timestamp(frame.get("duration_time"))
        if duration is None:
            duration = _parse_timestamp(frame.get("pkt_duration_time"))
        timings.append(
            VideoFrameTiming(
                pts_seconds=pts,
                duration_seconds=duration if duration is not None and duration > 0 else None,
            )
        )
    timings.sort(key=lambda timing: timing.pts_seconds)
    if not timings:
        raise MediaProbeError(f"ffprobe did not report video frame timestamps for {media_path}")
    if any(
        current.pts_seconds <= previous.pts_seconds
        for previous, current in zip(timings, timings[1:], strict=False)
    ):
        raise MediaProbeError(f"video frame timestamps are not strictly increasing: {media_path}")
    return timings


def probe_media(path: str | Path) -> MediaInfo:
    media_path = Path(path).resolve()
    if not media_path.is_file():
        raise MediaProbeError(f"media file does not exist: {media_path}")

    payload = _run_ffprobe(media_path)
    video_stream = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise MediaProbeError(f"no video stream found in {media_path}")

    format_info = payload.get("format", {})
    duration = float(video_stream.get("duration") or format_info.get("duration") or 0)
    fps = _parse_frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
    if fps <= 0:
        raise MediaProbeError("ffprobe did not report a usable frame rate")

    reported_frames = video_stream.get("nb_frames")
    frame_count = (
        int(reported_frames) if reported_frames not in {None, "N/A"} else round(duration * fps)
    )
    color_metadata = probe_color_metadata(video_stream, payload)
    return MediaInfo(
        path=str(media_path),
        duration_seconds=duration,
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        fps=fps,
        frame_count=max(frame_count, 0),
        codec=str(video_stream.get("codec_name") or "unknown"),
        **color_metadata,
    )
