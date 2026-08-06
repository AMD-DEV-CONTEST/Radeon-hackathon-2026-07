from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
import pytest

from buildguard.config import (
    CameraConfig,
    RealtimeConfig,
    TemporalRuleConfig,
    load_settings,
)
from buildguard.exceptions import EndpointSecurityError
from buildguard.realtime.camera_manager import CameraManager, register_realtime_tools
from buildguard.realtime.clip_writer import ClipWriter, ensure_browser_compatible_clip
from buildguard.realtime.event_engine import (
    DatabaseRealtimeStore,
    EventEngine,
    InMemoryRealtimeStore,
)
from buildguard.realtime.file_source import LocalVideoSource
from buildguard.realtime.frame_buffer import BoundedFrameQueue, FrameBuffer
from buildguard.realtime.reconnect import ExponentialReconnect
from buildguard.realtime.rtsp_source import RtspVideoSource, validate_rtsp_endpoint
from buildguard.realtime.sampler import FixedFpsSampler, RiskAwareSampler
from buildguard.realtime.schemas import (
    CameraState,
    EventCandidate,
    EventState,
    SamplingMode,
    VideoFrame,
)
from buildguard.realtime.source import VideoSource
from buildguard.realtime.temporal_confirmation import MOfNConfirmation
from buildguard.realtime.tracker import ByteTrackTracker, SimpleIoUTracker
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.vision import Detection
from buildguard.security.confirmation import ConfirmationManager
from buildguard.security.permission_engine import PermissionEngine
from buildguard.storage.database import Database
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import ToolExecutionRequest
from buildguard.utils.time import utc_now

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def make_frame(
    sequence: int,
    seconds: float,
    *,
    camera_id: str = "camera-1",
    key_frame: bool = False,
    shape: tuple[int, int] = (48, 64),
    base_time: datetime = BASE_TIME,
) -> VideoFrame:
    height, width = shape
    image = np.full(
        (height, width, 3),
        (sequence * 17) % 255,
        dtype=np.uint8,
    )
    return VideoFrame(
        camera_id=camera_id,
        sequence=sequence,
        captured_at=base_time + timedelta(seconds=seconds),
        source_time_seconds=seconds,
        image=image,
        key_frame=key_frame,
    )


def make_detection(
    x1: float,
    *,
    label: str = "missing_helmet",
    confidence: float = 0.8,
) -> Detection:
    return Detection(
        label=label,
        confidence=confidence,
        bounding_box=BoundingBox(x1=x1, y1=5, x2=x1 + 20, y2=30),
        source_model="test-detector",
    )


def rules() -> dict[str, TemporalRuleConfig]:
    return {
        "helmet_missing": TemporalRuleConfig(m=3, n=5, alpha=0.5),
        "dangerous_zone": TemporalRuleConfig(m=2, n=3, alpha=0.6),
        "static_defect": TemporalRuleConfig(m=2, n=4, alpha=0.6),
        "emergency": TemporalRuleConfig(m=1, n=2, alpha=0.75),
    }


def realtime_config(cameras: list[CameraConfig] | None = None) -> RealtimeConfig:
    return RealtimeConfig(
        allowed_video_roots=[Path("workspace/cameras")],
        event_image_dir=Path("workspace/events/images"),
        event_clip_dir=Path("workspace/events/clips"),
        buffer_seconds=10,
        buffer_max_frames=100,
        buffer_memory_mb=8,
        inference_queue_size=4,
        event_queue_size=4,
        normal_fps=2,
        active_fps=5,
        suspected_fps=8,
        tracker_iou_threshold=0.3,
        tracker_max_age=2,
        tracker_min_hits=1,
        reconnect_failure_threshold=2,
        reconnect_initial_seconds=0,
        reconnect_multiplier=2,
        reconnect_max_seconds=2,
        event_cooldown_seconds=5,
        event_resolve_seconds=5,
        event_region_iou_threshold=0.4,
        evidence_before_seconds=1,
        evidence_after_seconds=1,
        save_event_clips=False,
        clip_codec="mp4v",
        clip_fps=5,
        event_class_map={"missing_helmet": "helmet_missing"},
        event_severity={"helmet_missing": "high"},
        temporal_rules=rules(),
        cameras=cameras or [],
    )


def event_engine(tmp_path: Path) -> tuple[EventEngine, InMemoryRealtimeStore]:
    store = InMemoryRealtimeStore()
    writer = ClipWriter(
        tmp_path / "images",
        tmp_path / "clips",
        codec="mp4v",
        fps=5,
    )
    engine = EventEngine(
        store=store,
        writer=writer,
        severity_by_type={"helmet_missing": "high"},
        cooldown_seconds=5,
        resolve_seconds=3,
        region_iou_threshold=0.4,
        before_seconds=1,
        after_seconds=1,
        save_clips=False,
    )
    return engine, store


def test_synthetic_local_video_and_fixed_fps(tmp_path: Path) -> None:
    video_path = tmp_path / "synthetic.avi"
    fourcc = cast(Any, cv2.VideoWriter_fourcc)(*"MJPG")
    writer = cv2.VideoWriter(str(video_path), fourcc, 10, (64, 48))
    assert writer.isOpened()
    for index in range(10):
        writer.write(make_frame(index, index / 10).image)
    writer.release()

    source = LocalVideoSource("file-camera", video_path)
    assert source.open()
    frames = []
    while True:
        frame = source.read()
        if frame is None:
            break
        frames.append(frame)
    source.close()
    assert len(frames) == 10
    assert source.status().state == CameraState.STOPPED

    sampler = FixedFpsSampler(2)
    sampled = [
        timestamp
        for timestamp in [index / 10 for index in range(10)]
        if sampler.should_sample(timestamp)
    ]
    assert sampled == pytest.approx([0.0, 0.5])


def test_legacy_mp4_event_clip_gets_browser_compatible_webm(tmp_path: Path) -> None:
    source = tmp_path / "legacy.mp4"
    fourcc = cast(Any, cv2.VideoWriter_fourcc)(*"mp4v")
    writer = cv2.VideoWriter(str(source), fourcc, 5, (64, 48))
    assert writer.isOpened()
    for index in range(5):
        writer.write(make_frame(index, index / 5).image)
    writer.release()

    playable = ensure_browser_compatible_clip(source)

    assert playable.suffix == ".webm"
    capture = cv2.VideoCapture(str(playable))
    assert capture.isOpened()
    ok, frame = capture.read()
    capture.release()
    assert ok
    assert frame is not None


def test_realtime_yaml_contains_required_m_of_n_policies() -> None:
    settings = load_settings(Path("configs/app.yaml"))
    configured = settings.realtime.temporal_rules
    assert (configured["helmet_missing"].m, configured["helmet_missing"].n) == (3, 5)
    assert (configured["dangerous_zone"].m, configured["dangerous_zone"].n) == (2, 3)
    assert (configured["static_defect"].m, configured["static_defect"].n) == (2, 4)
    assert (configured["emergency"].m, configured["emergency"].n) == (1, 2)
    assert settings.realtime.reconnect_max_seconds == 30
    secret_camera = CameraConfig(
        camera_id="secret-rtsp",
        source_type="rtsp",
        rtsp_url="rtsp://operator:password@127.0.0.1/site",
    )
    assert "password" not in str(secret_camera.model_dump(mode="json"))


class _FakeCapture:
    def __init__(self, opened: bool, reads: list[tuple[bool, object]]) -> None:
        self.opened = opened
        self.reads = deque(reads)
        self.released = False

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, object]:
        return self.reads.popleft() if self.reads else (False, None)

    def release(self) -> None:
        self.released = True

    def get(self, _: int) -> float:
        return 0.0


def test_rtsp_reconnect_state_machine_and_local_policy() -> None:
    validate_rtsp_endpoint("rtsp://127.0.0.1:8554/site", [])
    with pytest.raises(EndpointSecurityError):
        validate_rtsp_endpoint("rtsp://8.8.8.8/site", [])
    delays: list[float] = []
    policy = ExponentialReconnect(
        0.25,
        2,
        2,
        sleeper=delays.append,
    )
    first = _FakeCapture(True, [(False, None), (False, None)])
    second = _FakeCapture(True, [(True, np.zeros((8, 8, 3), dtype=np.uint8))])
    captures = deque([first, second])

    def factory(_: str | int) -> _FakeCapture:
        return captures.popleft()

    source = RtspVideoSource(
        "rtsp-1",
        "rtsp://127.0.0.1:8554/site",
        allowed_lan_cidrs=[],
        failure_threshold=2,
        reconnect=policy,
        capture_factory=factory,
    )
    assert source.open()
    assert source.read() is None
    assert source.status().state == CameraState.DEGRADED
    assert source.read() is None
    assert source.status().state == CameraState.RECONNECTING
    assert source.reconnect()
    assert delays == [0.25]
    assert source.read() is not None
    assert source.status().state == CameraState.RUNNING
    source.close()


def test_reconnect_backoff_is_exponential_and_capped() -> None:
    policy = ExponentialReconnect(0.5, 2, 2, sleeper=lambda _: None)
    assert [policy.next().delay_seconds for _ in range(6)] == [
        0.5,
        1.0,
        2.0,
        2.0,
        2.0,
        2.0,
    ]
    policy.reset()
    assert policy.next().attempt == 1


def test_frame_buffer_duration_memory_and_critical_queue() -> None:
    buffer = FrameBuffer(duration_seconds=2, max_frames=10, max_memory_mb=1)
    for index in range(5):
        buffer.append(make_frame(index, float(index)))
    assert len(buffer) == 3
    assert buffer.latest() is not None
    assert buffer.latest().sequence == 4  # type: ignore[union-attr]
    assert buffer.memory_bytes <= 1024 * 1024

    frames = BoundedFrameQueue(2)
    frames.put(make_frame(0, 0))
    frames.put(make_frame(1, 1))
    frames.put(make_frame(2, 2))
    assert frames.dropped_normal_frames == 1
    assert frames.get(timeout=0).sequence == 1
    frames.put(make_frame(3, 3, key_frame=True))
    assert frames.get(timeout=0).sequence == 2
    assert frames.get(timeout=0).key_frame

    protected = BoundedFrameQueue(1)
    protected.put(make_frame(0, 0, key_frame=True))
    with pytest.raises(TimeoutError, match="Critical frame"):
        protected.put(make_frame(1, 1, key_frame=True), timeout=0)


def test_risk_aware_sampler_switches_rates() -> None:
    sampler = RiskAwareSampler(normal_fps=2, active_fps=5, suspected_fps=10)
    assert sampler.should_sample("camera", 0)
    assert not sampler.should_sample("camera", 0.2)
    sampler.set_mode("camera", SamplingMode.SUSPECTED)
    assert sampler.should_sample("camera", 0.2)
    sampler.set_mode("camera", SamplingMode.ACTIVE)
    assert not sampler.should_sample("camera", 0.3)
    assert sampler.should_sample("camera", 0.4)


def test_simple_iou_tracker_id_hits_and_max_age() -> None:
    tracker = SimpleIoUTracker(iou_threshold=0.3, max_age=1, minimum_hits=2)
    first = tracker.update([make_detection(5)], 0)
    second = tracker.update([make_detection(7)], 1)
    assert first[0].track_id == second[0].track_id
    assert not first[0].confirmed
    assert second[0].confirmed
    tracker.update([], 2)
    tracker.update([], 3)
    replacement = tracker.update([make_detection(7)], 4)
    assert replacement[0].track_id != first[0].track_id


def test_bytetrack_recovers_identity_from_low_confidence_detection() -> None:
    tracker = ByteTrackTracker(
        iou_threshold=0.3,
        high_confidence=0.6,
        low_confidence=0.1,
        max_age=2,
        minimum_hits=2,
    )
    first = tracker.update([make_detection(5, confidence=0.9)], 0)
    recovered = tracker.update([make_detection(7, confidence=0.3)], 1)
    assert first[0].track_id == recovered[0].track_id
    assert recovered[0].confirmed
    tracker.reset()
    assert tracker.update([make_detection(7, confidence=0.3)], 2) == []


def test_m_of_n_and_exponential_confidence_smoothing() -> None:
    confirmation = MOfNConfirmation(rules())
    first = confirmation.update(
        "helmet_missing", "track-1", detected=True, confidence=0.8
    )
    second = confirmation.update(
        "helmet_missing", "track-1", detected=True, confidence=0.6
    )
    third = confirmation.update(
        "helmet_missing", "track-1", detected=True, confidence=0.9
    )
    assert not first.confirmed
    assert not second.confirmed
    assert third.confirmed
    assert first.smoothed_confidence == pytest.approx(0.8)
    assert second.smoothed_confidence == pytest.approx(0.7)
    assert third.smoothed_confidence == pytest.approx(0.8)
    missing = confirmation.update(
        "helmet_missing", "track-1", detected=False, confidence=0
    )
    assert missing.smoothed_confidence == pytest.approx(0.4)
    confirmation.reset()
    sequence = [True, True, False, False, True]
    results = [
        confirmation.update(
            "helmet_missing",
            "track-2",
            detected=detected,
            confidence=0.8 if detected else 0,
        )
        for detected in sequence
    ]
    assert not any(result.confirmed for result in results[:-1])
    assert results[-1].confirmed
    assert confirmation.identities() == {("helmet_missing", "track-2")}


def test_event_dedup_acknowledge_and_resolution_evidence(tmp_path: Path) -> None:
    engine, store = event_engine(tmp_path)
    buffer = FrameBuffer(20, 100, 8)
    engine.register_buffer("camera-1", buffer)
    first_frame = make_frame(0, 0, key_frame=True)
    second_frame = make_frame(1, 1, key_frame=True)
    buffer.append(first_frame)
    buffer.append(second_frame)
    first = engine.process(
        EventCandidate(
            camera_id="camera-1",
            event_type="helmet_missing",
            track_id="track-1",
            bbox=make_detection(5).bounding_box,
            confidence=0.7,
            confirmed=True,
            frame=first_frame,
        )
    )
    second = engine.process(
        EventCandidate(
            camera_id="camera-1",
            event_type="helmet_missing",
            track_id="different-track",
            bbox=make_detection(6).bounding_box,
            confidence=0.9,
            confirmed=True,
            frame=second_frame,
        )
    )
    assert first.id == second.id
    assert len(engine.query(limit=20)) == 1
    assert second.start_frame_path is not None
    assert second.start_frame_path.is_file()
    assert second.max_confidence_frame_path is not None
    assert second.max_confidence_frame_path.is_file()
    acknowledged = engine.acknowledge(first.id)
    assert acknowledged.status == EventState.ACKNOWLEDGED
    assert engine.acknowledge(first.id).status == EventState.ACKNOWLEDGED
    resolved = engine.resolve_stale(BASE_TIME + timedelta(seconds=10))
    assert len(resolved) == 1
    assert resolved[0].status == EventState.RESOLVED
    assert resolved[0].end_frame_path is not None
    assert resolved[0].end_frame_path.is_file()
    assert store.events[first.id].status == EventState.RESOLVED
    with pytest.raises(ValueError, match="cannot be acknowledged"):
        engine.acknowledge(first.id)


def test_event_cooldown_creates_new_event_and_manual_close(tmp_path: Path) -> None:
    engine, _ = event_engine(tmp_path)
    first = engine.process(
        EventCandidate(
            camera_id="camera-1",
            event_type="helmet_missing",
            track_id="track-1",
            bbox=make_detection(5).bounding_box,
            confidence=0.8,
            confirmed=False,
            frame=make_frame(0, 0),
        )
    )
    second = engine.process(
        EventCandidate(
            camera_id="camera-1",
            event_type="helmet_missing",
            track_id="track-1",
            bbox=make_detection(5).bounding_box,
            confidence=0.8,
            confirmed=True,
            frame=make_frame(1, 6),
        )
    )
    assert first.id != second.id
    assert first.status == EventState.PENDING
    assert engine.close(first.id).status == EventState.RESOLVED


def test_camera_status_and_events_persist_to_sqlite(tmp_path: Path) -> None:
    database = Database(tmp_path / "realtime.db")
    database.initialize()
    store = DatabaseRealtimeStore(database)
    status = LocalVideoSource("persisted-camera", tmp_path / "missing.avi").status()
    store.save_camera_status(status)
    assert store.list_camera_statuses()[0].camera_id == "persisted-camera"
    engine = EventEngine(
        store=store,
        writer=ClipWriter(tmp_path / "images", tmp_path / "clips", codec="mp4v", fps=5),
        severity_by_type={"helmet_missing": "high"},
        cooldown_seconds=5,
        resolve_seconds=3,
        region_iou_threshold=0.4,
        before_seconds=1,
        after_seconds=1,
        save_clips=False,
    )
    event = engine.process(
        EventCandidate(
            camera_id="persisted-camera",
            event_type="helmet_missing",
            track_id="track-1",
            bbox=make_detection(5).bounding_box,
            confidence=0.9,
            confirmed=True,
            frame=make_frame(0, 0, camera_id="persisted-camera"),
        )
    )
    assert store.list_events()[0].id == event.id
    assert {"camera_statuses", "realtime_events"} <= set(database.check()["tables"])
    database.dispose()


class _FlakySource(VideoSource):
    def __init__(self, frames: list[VideoFrame]) -> None:
        super().__init__("camera-1", "local")
        self.items: deque[VideoFrame | Exception | None] = deque(
            [RuntimeError("single route failure"), *frames, None]
        )

    def open(self) -> bool:
        self._set_state(CameraState.RUNNING, reset_failures=True)
        return True

    def read(self) -> VideoFrame | None:
        item = self.items.popleft() if self.items else None
        if isinstance(item, Exception):
            raise item
        if item is None:
            self._set_state(CameraState.STOPPED)
            return None
        self._record_frame(item)
        return item

    def reconnect(self) -> bool:
        return True

    def close(self) -> None:
        self._set_state(CameraState.STOPPED)


def test_camera_manager_contains_single_route_failure_and_registers_tools(
    tmp_path: Path,
) -> None:
    base = utc_now()
    frames = [
        make_frame(0, 0, base_time=base),
        make_frame(1, 0.6, base_time=base),
        make_frame(2, 1.2, base_time=base),
    ]
    source = _FlakySource(frames)
    camera = CameraConfig(
        camera_id="camera-1",
        source_type="local",
        file_path=Path("ignored.avi"),
    )
    config = realtime_config([camera])
    config.temporal_rules["helmet_missing"] = TemporalRuleConfig(
        m=2, n=3, alpha=0.5
    )
    store = InMemoryRealtimeStore()
    engine = EventEngine(
        store=store,
        writer=ClipWriter(tmp_path / "images", tmp_path / "clips", codec="mp4v", fps=5),
        severity_by_type=config.event_severity,
        cooldown_seconds=config.event_cooldown_seconds,
        resolve_seconds=config.event_resolve_seconds,
        region_iou_threshold=config.event_region_iou_threshold,
        before_seconds=1,
        after_seconds=1,
        save_clips=False,
    )
    manager = CameraManager(
        config,
        store=store,
        event_engine=engine,
        inference=lambda _: [make_detection(5)],
        source_factory=lambda _: source,
    )
    manager.start("camera-1")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not engine.query(limit=20):
        time.sleep(0.01)
    manager.stop("camera-1")
    events = engine.query(limit=20)
    assert events
    assert all(event.status == EventState.RESOLVED for event in events)
    assert source.status().state == CameraState.STOPPED

    registry = ToolRegistry()
    register_realtime_tools(registry, manager)
    names = {item["name"] for item in registry.export_metadata("realtime")}
    assert names == {
        "start_camera_monitoring",
        "stop_camera_monitoring",
        "query_recent_events",
        "acknowledge_event",
        "close_event",
        "list_camera_status",
    }
    assert registry.get("start_camera_monitoring").definition.permission == "confirm"
    assert registry.get("stop_camera_monitoring").definition.permission == "confirm"
    permission = PermissionEngine(ConfirmationManager(ttl_seconds=60))
    request = ToolExecutionRequest(
        session_id="session",
        task_id="task",
        actor="operator",
        tool_name="start_camera_monitoring",
        arguments={"camera_id": "camera-1"},
    )
    decision = permission.check(
        registry.get("start_camera_monitoring").definition,
        request,
    )
    assert decision.decision == "confirm"
    assert decision.confirmation is not None
    permission.confirmations.decide(decision.confirmation.id, True)
    request.confirmation_id = decision.confirmation.id
    assert (
        permission.check(
            registry.get("start_camera_monitoring").definition,
            request,
        ).decision
        == "allow"
    )
