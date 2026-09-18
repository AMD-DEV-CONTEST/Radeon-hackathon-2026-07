from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from buildguard.config import (
    CameraPolicyConfig,
    RealtimeOptimizationConfig,
    TemporalRuleConfig,
    load_settings,
)
from buildguard.realtime.calibration import ConformalEventCalibrator
from buildguard.realtime.frame_buffer import BoundedFrameQueue
from buildguard.realtime.sampler import AdaptiveMotionSampler
from buildguard.realtime.schemas import FramePriority, SamplingMode, VideoFrame
from buildguard.realtime.stream_clock import StreamClock
from buildguard.realtime.temporal_confirmation import MOfNConfirmation


BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def make_frame(sequence: int, *, key_frame: bool = False) -> VideoFrame:
    return VideoFrame(
        camera_id="camera-1",
        sequence=sequence,
        captured_at=BASE_TIME + timedelta(seconds=sequence),
        source_time_seconds=float(sequence),
        image=np.zeros((8, 8, 3), dtype=np.uint8),
        key_frame=key_frame,
    )


def test_competition_enables_video_optimization_without_changing_models() -> None:
    settings = load_settings(Path("configs/competition/app.yaml"))

    assert settings.realtime.optimization.enabled is True
    assert settings.realtime.optimization.observation_centric_tracking is True
    assert settings.realtime.tracker_algorithm == "bytetrack"


def test_stream_clock_paces_source_timestamps_with_monotonic_time() -> None:
    readings = iter([10.0, 10.25, 11.0])
    clock = StreamClock(pace=True, monotonic=lambda: next(readings))

    assert clock.delay_seconds(2.0) == 0
    assert clock.delay_seconds(3.0) == 0.75
    assert clock.delay_seconds(3.0) == 0


def test_deadline_queue_expires_normal_frames_and_protects_risk_frames() -> None:
    queue = BoundedFrameQueue(max_size=1)
    assert queue.put(make_frame(1), max_age_seconds=0.01)
    time.sleep(0.02)
    assert queue.put(
        make_frame(2),
        priority=FramePriority.SUSPECTED,
        max_age_seconds=0.5,
    )

    assert queue.get().sequence == 2
    assert queue.freshness_metrics()["expired_normal_frames"] == 1


def test_risk_feedback_enters_suspected_then_recovery_mode() -> None:
    optimization = RealtimeOptimizationConfig(
        enabled=True,
        suspected_hold_seconds=1,
        recovery_hold_seconds=2,
    )
    sampler = AdaptiveMotionSampler(CameraPolicyConfig(), optimization)

    sampler.update_feedback(
        timestamp_seconds=10,
        active_tracks=False,
        risk_score=0.8,
        uncertainty_score=0,
    )
    assert sampler.mode == SamplingMode.SUSPECTED
    sampler.update_feedback(
        timestamp_seconds=11.1,
        active_tracks=False,
        risk_score=0,
        uncertainty_score=0,
    )
    assert sampler.mode == SamplingMode.RECOVERY


def test_time_evidence_requires_duration_but_preserves_single_frame_emergency() -> None:
    confirmation = MOfNConfirmation(
        {"defect": TemporalRuleConfig(m=2, n=4, alpha=0.6)},
        time_evidence_enabled=True,
        evidence_min_positive_seconds=0.5,
        evidence_confirm_threshold=0.5,
    )
    first = confirmation.update(
        "defect",
        "track-1",
        detected=True,
        confidence=0.9,
        timestamp_seconds=0,
    )
    second = confirmation.update(
        "defect",
        "track-1",
        detected=True,
        confidence=0.9,
        timestamp_seconds=0.6,
    )
    assert first.confirmed is False
    assert second.confirmed is True
    assert second.positive_duration_seconds == 0.6

    emergency = MOfNConfirmation(
        {"emergency": TemporalRuleConfig(m=1, n=2, alpha=0.75)},
        time_evidence_enabled=True,
        evidence_min_positive_seconds=1,
        evidence_confirm_threshold=0.5,
    ).update(
        "emergency",
        "track-2",
        detected=True,
        confidence=0.9,
        timestamp_seconds=0,
    )
    assert emergency.confirmed is True


def test_calibration_artifact_produces_three_way_decisions(tmp_path: Path) -> None:
    artifact = tmp_path / "calibration.json"
    artifact.write_text(
        json.dumps(
            {
                "version": "2026-08-04",
                "dataset_sha256": "a" * 64,
                "target_error_rate": 0.05,
                "event_types": {
                    "missing_helmet": {
                        "negative_max": 0.3,
                        "positive_min": 0.7,
                        "sample_count": 100,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    calibrator = ConformalEventCalibrator.from_path(artifact, required=True)

    assert calibrator.decide("missing_helmet", 0.2) == "no_event"
    assert calibrator.decide("missing_helmet", 0.5) == "ambiguous"
    assert calibrator.decide("missing_helmet", 0.8) == "event"
    assert calibrator.decide("unknown", 0.8) == "uncalibrated"
