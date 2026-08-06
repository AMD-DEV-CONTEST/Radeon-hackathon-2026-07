from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from colorgraph.media.proxy import browser_proxy_filename

PLAYBACK_METRICS_SCHEMA = "colorgraph.preview-playback-metrics/v1"
_REPORT_LOCK = threading.Lock()
_MAX_PROFILE_SAMPLES = 240
_MAX_PROFILE_SESSIONS = 32


def _filetime_value(value: Any) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _windows_cpu_snapshot() -> tuple[int, int] | None:
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    idle = FileTime()
    kernel = FileTime()
    user = FileTime()
    getter = ctypes.windll.kernel32.GetSystemTimes
    getter.argtypes = [
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    getter.restype = wintypes.BOOL
    if not getter(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    return (
        _filetime_value(kernel) + _filetime_value(user),
        _filetime_value(idle),
    )


def _proc_cpu_snapshot() -> tuple[int, int] | None:
    try:
        values = (Path("/proc/stat").read_text(encoding="ascii").splitlines()[0]).split()
        ticks = [int(value) for value in values[1:]]
    except (OSError, ValueError, IndexError):
        return None
    if len(ticks) < 4:
        return None
    return sum(ticks), ticks[3] + (ticks[4] if len(ticks) > 4 else 0)


def _cpu_snapshot() -> tuple[int, int] | None:
    if sys.platform == "win32":
        return _windows_cpu_snapshot()
    return _proc_cpu_snapshot()


def _gpu_sample() -> dict[str, float | None]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {
            "gpu_utilization_percent": None,
            "gpu_decoder_percent": None,
            "gpu_memory_used_mb": None,
        }
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=utilization.gpu,utilization.decoder,memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=creation_flags,
        )
        values = [float(value.strip()) for value in result.stdout.splitlines()[0].split(",")]
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return {
            "gpu_utilization_percent": None,
            "gpu_decoder_percent": None,
            "gpu_memory_used_mb": None,
        }
    if len(values) != 3:
        return {
            "gpu_utilization_percent": None,
            "gpu_decoder_percent": None,
            "gpu_memory_used_mb": None,
        }
    return {
        "gpu_utilization_percent": values[0],
        "gpu_decoder_percent": values[1],
        "gpu_memory_used_mb": values[2],
    }


def sample_runtime_occupancy(interval_seconds: float = 0.08) -> dict[str, float | None]:
    """Take a short local system sample without adding a monitoring dependency."""

    before = _cpu_snapshot()
    time.sleep(max(0.02, min(interval_seconds, 0.25)))
    after = _cpu_snapshot()
    cpu_percent: float | None = None
    if before is not None and after is not None:
        total_delta = after[0] - before[0]
        idle_delta = after[1] - before[1]
        if total_delta > 0:
            cpu_percent = round(
                max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0)),
                3,
            )
    return {"cpu_percent": cpu_percent, **_gpu_sample()}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _artifact_metrics(
    *,
    previews_dir: Path,
    input_dir: Path,
    duration_seconds: float,
    cache_key: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    metadata = _load_json(previews_dir / f"graded-playback-{cache_key}.json")
    if metadata.get("cache_key") != cache_key:
        metadata = {}
    metadata_profile = metadata.get("profile")
    if isinstance(metadata_profile, dict):
        compared_fields = (
            "quality",
            "codec",
            "codec_profile",
            "bit_depth",
            "pixel_format",
            "width",
            "height",
            "fps",
            "color_range",
            "color_primaries",
            "color_transfer",
            "color_matrix",
            "mov_tag",
        )
        if any(metadata_profile.get(field) != profile.get(field) for field in compared_fields):
            raise ValueError("playback telemetry profile does not match the cached preview")

    graded_size = metadata.get("output_size")
    if not isinstance(graded_size, int) or graded_size <= 0:
        graded_size = None
    source_path = input_dir / browser_proxy_filename(
        profile["quality"],
        profile["codec"],
        int(profile["bit_depth"]),
    )
    try:
        source_size: int | None = source_path.stat().st_size
    except OSError:
        source_size = None
    source_duration = max(float(duration_seconds), 0.0)
    segment_start = metadata.get("start_seconds")
    segment_end = metadata.get("end_seconds")
    if (
        isinstance(segment_start, int | float)
        and isinstance(segment_end, int | float)
        and segment_end > segment_start
    ):
        graded_duration = float(segment_end - segment_start)
    else:
        graded_duration = source_duration
    render = metadata.get("render") if isinstance(metadata.get("render"), dict) else {}
    return {
        "source_proxy_size_bytes": source_size,
        "source_average_bitrate_bps": (
            round(source_size * 8 / source_duration)
            if source_size is not None and source_duration > 0
            else None
        ),
        "graded_proxy_size_bytes": graded_size,
        "graded_average_bitrate_bps": (
            round(graded_size * 8 / graded_duration)
            if graded_size is not None and graded_duration > 0
            else None
        ),
        "duration_seconds": graded_duration,
        "source_duration_seconds": source_duration,
        "segment_start_seconds": segment_start,
        "segment_end_seconds": segment_end,
        "render_elapsed_seconds": render.get("elapsed_seconds"),
        "render_processing_fps": render.get("processing_fps"),
        "render_device_runtime": render.get("device_runtime"),
        "render_device_name": render.get("device_name"),
        "render_encoder": render.get("encoder"),
    }


def _profile_summary(entry: dict[str, Any]) -> dict[str, Any]:
    samples = [sample for sample in entry.get("samples", []) if isinstance(sample, dict)]
    sessions = [
        session for session in entry.get("sessions", {}).values() if isinstance(session, dict)
    ]
    latest_by_session: dict[str, dict[str, Any]] = {}
    for sample in samples:
        session_id = sample.get("session_id")
        if isinstance(session_id, str):
            latest_by_session[session_id] = sample

    first_frames = [
        float(session["first_frame_wait_ms"])
        for session in sessions
        if isinstance(session.get("first_frame_wait_ms"), int | float)
    ]
    sync_errors = [
        float(sample["sync_error_ms"])
        for sample in samples
        if isinstance(sample.get("sync_error_ms"), int | float)
    ]
    cpu_values = [
        float(sample["cpu_percent"])
        for sample in samples
        if isinstance(sample.get("cpu_percent"), int | float)
    ]
    gpu_values = [
        float(sample["gpu_utilization_percent"])
        for sample in samples
        if isinstance(sample.get("gpu_utilization_percent"), int | float)
    ]
    decoder_values = [
        float(sample["gpu_decoder_percent"])
        for sample in samples
        if isinstance(sample.get("gpu_decoder_percent"), int | float)
    ]
    memory_values = [
        float(sample["gpu_memory_used_mb"])
        for sample in samples
        if isinstance(sample.get("gpu_memory_used_mb"), int | float)
    ]
    total_frames = sum(
        int(sample.get("total_video_frames", 0)) for sample in latest_by_session.values()
    )
    dropped_frames = sum(
        int(sample.get("dropped_video_frames", 0)) for sample in latest_by_session.values()
    )
    ready_samples = sum(
        1
        for sample in samples
        if int(sample.get("master_ready_state", 0)) >= 3
        and int(sample.get("graded_ready_state", 0)) >= 3
    )
    stable_samples = sum(
        1
        for sample in samples
        if int(sample.get("master_ready_state", 0)) >= 3
        and int(sample.get("graded_ready_state", 0)) >= 3
        and float(sample.get("sync_error_ms", float("inf"))) <= 50.0
    )
    buffering_events = sum(
        int(sample.get("buffering_events", 0)) for sample in latest_by_session.values()
    )
    return {
        "sample_count": len(samples),
        "session_count": len(sessions),
        "first_frame_wait_ms_p50": _percentile(first_frames, 0.5),
        "first_frame_wait_ms_p95": _percentile(first_frames, 0.95),
        "total_video_frames": total_frames,
        "dropped_video_frames": dropped_frames,
        "dropped_frame_ratio": dropped_frames / total_frames if total_frames > 0 else 0.0,
        "buffering_events": buffering_events,
        "sync_error_ms_mean": _mean(sync_errors),
        "sync_error_ms_p95": _percentile(sync_errors, 0.95),
        "sync_error_ms_max": max(sync_errors) if sync_errors else None,
        "dual_ready_sample_ratio": ready_samples / len(samples) if samples else 0.0,
        "stable_sample_ratio": stable_samples / len(samples) if samples else 0.0,
        "cpu_percent_mean": _mean(cpu_values),
        "cpu_percent_p95": _percentile(cpu_values, 0.95),
        "gpu_utilization_percent_mean": _mean(gpu_values),
        "gpu_utilization_percent_p95": _percentile(gpu_values, 0.95),
        "gpu_decoder_percent_mean": _mean(decoder_values),
        "gpu_decoder_percent_p95": _percentile(decoder_values, 0.95),
        "gpu_memory_used_mb_peak": max(memory_values) if memory_values else None,
    }


def record_playback_metrics(
    *,
    report_path: Path,
    previews_dir: Path,
    input_dir: Path,
    duration_seconds: float,
    cache_key: str,
    profile: dict[str, Any],
    telemetry: dict[str, Any],
    runtime: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    runtime_sample = runtime if runtime is not None else sample_runtime_occupancy()
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    profile_key = (
        f"{profile['quality']}-{profile['codec']}-"
        f"{profile['codec_profile']}-{profile['bit_depth']}bit-"
        f"{profile['width']}x{profile['height']}"
    )
    sample = {
        "recorded_at": now,
        **telemetry,
        **runtime_sample,
    }

    with _REPORT_LOCK:
        report = _load_json(report_path)
        if report.get("schema") != PLAYBACK_METRICS_SCHEMA:
            report = {
                "schema": PLAYBACK_METRICS_SCHEMA,
                "created_at": now,
                "updated_at": now,
                "profiles": {},
            }
        profiles = report.setdefault("profiles", {})
        entry = profiles.setdefault(
            profile_key,
            {
                "profile": profile,
                "cache_key": cache_key,
                "artifact": {},
                "sessions": {},
                "samples": [],
                "summary": {},
            },
        )
        entry["profile"] = profile
        entry["cache_key"] = cache_key
        entry["artifact"] = _artifact_metrics(
            previews_dir=previews_dir,
            input_dir=input_dir,
            duration_seconds=duration_seconds,
            cache_key=cache_key,
            profile=profile,
        )
        samples = entry.setdefault("samples", [])
        samples.append(sample)
        del samples[:-_MAX_PROFILE_SAMPLES]

        session_id = str(telemetry["session_id"])
        sessions = entry.setdefault("sessions", {})
        sessions[session_id] = {
            "recorded_at": now,
            "first_frame_wait_ms": telemetry.get("first_frame_wait_ms"),
        }
        if len(sessions) > _MAX_PROFILE_SESSIONS:
            oldest = sorted(
                sessions,
                key=lambda key: str(sessions[key].get("recorded_at", "")),
            )
            for key in oldest[: len(sessions) - _MAX_PROFILE_SESSIONS]:
                sessions.pop(key, None)

        entry["summary"] = _profile_summary(entry)
        report["updated_at"] = now
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = report_path.with_suffix(report_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, report_path)
        return {
            "schema": PLAYBACK_METRICS_SCHEMA,
            "profile_key": profile_key,
            "artifact": entry["artifact"],
            "summary": entry["summary"],
        }
