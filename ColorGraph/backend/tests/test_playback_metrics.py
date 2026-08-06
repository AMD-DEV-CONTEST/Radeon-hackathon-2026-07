from __future__ import annotations

import json

import pytest

from colorgraph.api.routes.operations import PreviewPlaybackTelemetryRequest
from colorgraph.media.proxy import browser_proxy_filename
from colorgraph.services.playback_metrics import (
    PLAYBACK_METRICS_SCHEMA,
    record_playback_metrics,
)


def _profile() -> dict:
    return {
        "quality": "1080p",
        "codec": "hevc",
        "codec_profile": "main10",
        "bit_depth": 10,
        "pixel_format": "yuv420p10le",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "color_range": "limited",
        "color_primaries": "bt709",
        "color_transfer": "bt709",
        "color_matrix": "bt709",
        "mov_tag": "hvc1",
    }


def _telemetry(session_id: str = "session-0001") -> dict:
    return {
        "session_id": session_id,
        "first_frame_wait_ms": 125.0,
        "total_video_frames": 600,
        "dropped_video_frames": 2,
        "sync_error_ms": 12.5,
        "buffering_events": 1,
        "master_ready_state": 4,
        "graded_ready_state": 4,
        "playing": True,
    }


def test_playback_metrics_persist_artifact_runtime_and_stability(tmp_path) -> None:
    previews_dir = tmp_path / "previews"
    input_dir = tmp_path / "input"
    previews_dir.mkdir()
    input_dir.mkdir()
    profile = _profile()
    cache_key = "1080p-hevc-10bit-" + ("a" * 24)
    graded_size = 3_000_000
    source_size = 2_000_000
    (previews_dir / f"graded-playback-{cache_key}.mp4").write_bytes(b"x" * graded_size)
    (input_dir / browser_proxy_filename("1080p", "hevc", 10)).write_bytes(
        b"x" * source_size
    )
    (previews_dir / f"graded-playback-{cache_key}.json").write_text(
        json.dumps(
            {
                "cache_key": cache_key,
                "output_size": graded_size,
                "profile": profile,
                "render": {
                    "elapsed_seconds": 8.5,
                    "processing_fps": 10.0,
                    "device_runtime": "cuda",
                    "device_name": "Test GPU",
                    "encoder": "hevc_nvenc",
                },
            }
        ),
        encoding="utf-8",
    )
    report_path = previews_dir / "playback-metrics.json"

    result = record_playback_metrics(
        report_path=report_path,
        previews_dir=previews_dir,
        input_dir=input_dir,
        duration_seconds=10.0,
        cache_key=cache_key,
        profile=profile,
        telemetry=_telemetry(),
        runtime={
            "cpu_percent": 18.0,
            "gpu_utilization_percent": 24.0,
            "gpu_decoder_percent": 7.0,
            "gpu_memory_used_mb": 1024.0,
        },
    )

    assert result["schema"] == PLAYBACK_METRICS_SCHEMA
    assert result["artifact"]["source_proxy_size_bytes"] == source_size
    assert result["artifact"]["source_average_bitrate_bps"] == 1_600_000
    assert result["artifact"]["graded_proxy_size_bytes"] == graded_size
    assert result["artifact"]["graded_average_bitrate_bps"] == 2_400_000
    assert result["summary"]["first_frame_wait_ms_p95"] == 125.0
    assert result["summary"]["dropped_frame_ratio"] == pytest.approx(2 / 600)
    assert result["summary"]["sync_error_ms_max"] == 12.5
    assert result["summary"]["stable_sample_ratio"] == 1.0
    assert result["summary"]["cpu_percent_mean"] == 18.0
    assert result["summary"]["gpu_decoder_percent_mean"] == 7.0

    stored = json.loads(report_path.read_text(encoding="utf-8"))
    assert stored["schema"] == PLAYBACK_METRICS_SCHEMA
    assert len(stored["profiles"]) == 1


def test_playback_telemetry_rejects_cache_profile_or_frame_mismatch() -> None:
    profile = _profile()
    valid = {
        **_telemetry(),
        "cache_key": "1080p-hevc-10bit-" + ("b" * 24),
        "profile": profile,
    }
    assert PreviewPlaybackTelemetryRequest.model_validate(valid).profile.codec == "hevc"

    with pytest.raises(ValueError, match="cache key does not match"):
        PreviewPlaybackTelemetryRequest.model_validate(
            {
                **valid,
                "cache_key": "1080p-h264-8bit-" + ("b" * 24),
            }
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        PreviewPlaybackTelemetryRequest.model_validate(
            {
                **valid,
                "total_video_frames": 1,
                "dropped_video_frames": 2,
            }
        )
